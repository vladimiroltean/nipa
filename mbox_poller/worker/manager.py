# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import logging
from pathlib import Path
from typing import Dict

from ..email_parser import EmailParser
from ..notifier import SmtpNotifier
from ..utils import should_process_job, run_sync_command
from ..constants import WORKTREE_BASE
from .tree_selector import TreeSelector
from .build_job import BuildJob

logger = logging.getLogger(__name__)

class JobManager(EmailParser):
    """Orchestrates all build jobs, discovering, starting, polling, and blacklisting."""

    TERMINAL_STATUSES = (
        'completed',
        'failed',
        'running',
        'failed_launch',
        'failed_no_reply_to',
        'failed_tree_selection'
    )

    def __init__(self, work_dir: Path, notifier: SmtpNotifier, blacklist_file: Path,
                 worker_index: int, hash_size: int, tree_selector: TreeSelector):
        super().__init__(blacklist_file)
        self.work_dir: Path = work_dir
        self.notifier: SmtpNotifier = notifier
        self.jobs: Dict[str, BuildJob] = {}
        self.worker_index: int = worker_index
        self.hash_size: int = hash_size
        self.tree_selector: TreeSelector = tree_selector

    def discover_and_reap_jobs(self):
        """
        On startup, loads pending jobs, cleans up stale ones, and loads the blacklist.
        In distributed mode, *only* loads pending jobs that belong to this worker.
        Stale jobs are cleaned up regardless of ownership to prevent orphans.
        """
        self._load_blacklist()

        logger.info("Checking for existing and orphaned jobs...")
        if not self.work_dir.exists():
            return

        processed_worktrees = set()

        for job_dir in self.work_dir.iterdir():
            if job_dir.is_dir() and (job_dir / "info.json").exists():
                job_id = job_dir.name
                try:
                    job = BuildJob(job_id, self.work_dir, self.tree_selector)
                    job_status = job.info.get('status')

                    build_id = job.info.get('build_id')
                    if build_id:
                        processed_worktrees.add(build_id)

                    # Clean up terminal job
                    if job_status in self.TERMINAL_STATUSES:
                        if job_status == 'running':
                            logger.warning(f"Found orphaned running job: {job_id} (likely from restart). Marking as failed.")
                            job.info['status'] = 'failed_restart'
                            job._save_state()

                            msg = (f"Build job for '{job.info.get('series_name', job_id)}' "
                                    f"was interrupted by system restart. Please resubmit the patch series.")
                            self.notifier.send_failure_notification(job.info, msg)
                            job.cleanup(None)
                        else:
                            logger.warning(f"Found orphaned/stale job: {job_id} (status: {job_status}). Cleaning up.")
                            job.cleanup(None) # No imap_conn, just clean dirs/worktree
                    elif job_status == 'pending':
                        # It's a pending job. Check ownership *before* loading.
                        if should_process_job(job_id, self.worker_index, self.hash_size):
                            logger.info(f"Discovered pending job (owned): {job_id}")
                            self.jobs[job_id] = job
                        else:
                            logger.debug(f"Discovered pending job (not owned): {job_id}. Ignoring.")

                    else:
                        logger.warning(f"Job {job_id} has unknown status: {job_status}. Ignoring.")

                except Exception as e:
                    logger.error(f"Failed to load/reap job {job_id}: {e}")

        # Clean up stale worktrees and their branches
        if WORKTREE_BASE.exists():
            logger.info("Checking for stale git worktrees...")
            try:
                success, stdout, _ = run_sync_command(["git", "worktree",
                                                       "list", "--porcelain"],
                                                      WORKTREE_BASE)
                actual_worktrees = set()
                if success:
                    for line in stdout.splitlines():
                        if line.startswith("worktree "):
                            try:
                                wt_path = Path(line.split(' ', 1)[1])
                                actual_worktrees.add(wt_path.name)
                            except Exception:
                                pass

                stale_prefix = "nipa-build-"
                for item in WORKTREE_BASE.iterdir():
                    item_name = item.name
                    if (item.is_dir() and item_name.startswith(stale_prefix) and
                        item_name not in processed_worktrees and
                        item_name in actual_worktrees):

                        logger.warning(f"Found stale worktree: {item_name}. Removing.")
                        run_sync_command(["git", "worktree", "remove", "--force", item_name],
                                         WORKTREE_BASE)
                        logger.info(f"Attempting to delete stale branch '{item_name}'...")
                        run_sync_command(["git", "branch", "-D", item_name],
                                         WORKTREE_BASE)

            except Exception as e:
                logger.error(f"Failed checking stale worktrees: {e}")
        logger.info("Orphan/stale check complete.")

    def process_email_batch(self, imap_conn):
        """Fetches and processes all new emails."""
        parsed_emails = self.fetch_and_parse_emails(imap_conn, fetch_body=True)

        for msg_uid, headers, raw_email_bytes, job_id, patch_info in parsed_emails:
            mark_as_seen = False
            try:
                # Skip emails that failed parsing
                if headers is None or job_id is None or patch_info is None:
                    mark_as_seen = True  # Mark non-patch emails as seen to avoid reprocessing
                    continue

                # Check hash-based ownership
                if not should_process_job(job_id, self.worker_index, self.hash_size):
                    mark_as_seen = False  # Don't mark as seen - not our job
                    logger.debug(f"Skipping job '{job_id}' (hash mismatch) for UID {msg_uid}.")
                    continue

                # Process the email
                patch_index, total_patches_subj = patch_info

                if job_id not in self.jobs:
                    self.jobs[job_id] = BuildJob(job_id, self.work_dir, self.tree_selector)

                job = self.jobs[job_id]
                if job.info['status'] != 'pending':
                    logger.warning(f"Received patch for non-pending job '{job_id}' (status: "
                                   f"{job.info['status']}). Skipping UID {msg_uid}.")
                    mark_as_seen = True  # Mark as seen since we processed it (even if rejected)
                    continue

                job.add_patch(msg_uid, patch_index, total_patches_subj, headers, raw_email_bytes)
                mark_as_seen = True  # Successfully processed

            except Exception as e:
                logger.exception(f"Failed processing email UID {msg_uid}")
                mark_as_seen = True  # Mark as seen to avoid infinite reprocessing of broken emails
            finally:
                if mark_as_seen:
                    try:
                        logger.debug(f"Marking UID {msg_uid} as seen.")
                        imap_conn.uid('store', msg_uid, '+FLAGS', '\\Seen')
                    except Exception as e_seen:
                        logger.error(f"Failed marking UID {msg_uid} as seen: {e_seen}")

    def manage_build_jobs(self, imap_conn):
        """Polls running jobs and starts new ones."""
        logger.debug("Checking for new complete jobs and polling running jobs...")

        for job_id, job in list(self.jobs.items()):
            try:
                status = job.info['status']

                if status == 'running':
                    if job.poll_status(self.notifier, imap_conn):
                        del self.jobs[job_id]

                elif status == 'pending':
                    if job.is_ready():
                        job.start_build(self.notifier)

                elif status in self.TERMINAL_STATUSES:
                    logger.warning(f"Reaping stale job from memory: {job_id} (status: {status})")
                    del self.jobs[job_id]

            except Exception as e:
                logger.exception(f"Failed managing job '{job_id}'")

    def terminate_all_jobs(self):
        """Called on script shutdown."""
        logger.info("Terminating all running jobs...")
        for job in self.jobs.values():
            job.terminate()
