# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import os
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, IO
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses

from ..utils import sanitize_id, run_sync_command
from ..imap_utils import delete_emails_by_uid
from ..constants import (
    WORKTREE_BASE, NIPA_INGEST_SCRIPT_PATH, PYTHON_EXECUTABLE,
    CLEANUP_WORKTREE
)
from .tree_selector import TreeSelector
from ..notifier import SmtpNotifier

logger = logging.getLogger(__name__)

class BuildJob:
    """Represents a single build job (a patch series) and its lifecycle."""

    def __init__(self, job_id: str, base_work_dir: Path, tree_selector: TreeSelector):
        self.job_id: str = job_id
        self.work_dir: Path = base_work_dir / job_id
        self.patch_dir: Path = self.work_dir / "patches"
        self.info_file: Path = self.work_dir / "info.json"
        self.results_dir: Path = self.work_dir / "results"
        self.stdout_log: Path = self.work_dir / "build_stdout.log"
        self.stderr_log: Path = self.work_dir / "build_stderr.log"
        self.venv_dir: Path = self.work_dir / "venv"
        self.tree_selector: TreeSelector = tree_selector

        self.info: dict = self._load_state()
        self.info['job_id'] = job_id
        self.process: Optional[subprocess.Popen] = None
        self._stdout_f: Optional[IO] = None
        self._stderr_f: Optional[IO] = None

    def _log_msg(self, msg: str):
        """Appends a message to both log files."""
        try:
            with self.stdout_log.open('a', encoding='utf-8') as f:
                f.write(msg)
        except Exception as e:
            logger.warning(f"Failed writing stdout log {self.stdout_log}: {e}")
        try:
            if self.stderr_log != self.stdout_log:
                with self.stderr_log.open('a', encoding='utf-8') as f:
                    f.write(msg)
        except Exception as e:
            logger.warning(f"Failed writing stderr log {self.stderr_log}: {e}")

    def _log_command_result(self, cmd_list: List[str], stdout: str, stderr: str, success: bool):
        """Appends the result of a synchronous command to the logs."""
        msg = (f"\n--- Command: {' '.join(cmd_list)} ({'OK' if success else 'FAIL'}) ---\n"
               f"STDOUT:\n{stdout}\n"
               f"STDERR:\n{stderr}\n")
        self._log_msg(msg)

    def _load_state(self) -> dict:
        """Loads job info from JSON, ensuring essential keys/types."""
        defaults = {"status": "pending", "uids": [], "patch_subjects": {}, "all_recipient_emails": []}
        if not self.info_file.exists():
            return defaults
        try:
            with self.info_file.open('r') as f:
                info = json.load(f)
            info.setdefault('status', 'pending')
            info.setdefault('uids', [])
            info.setdefault('patch_subjects', {})
            info.setdefault('all_recipient_emails', [])
            # Type correction
            if not isinstance(info.get('uids'), list): info['uids'] = []
            if not isinstance(info.get('patch_subjects'), dict): info['patch_subjects'] = {}
            if not isinstance(info.get('all_recipient_emails'), list): info['all_recipient_emails'] = []
            return info
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning(f"Error loading {self.info_file}: {e}. Using defaults.")
            return defaults

    def _save_state(self):
        """Saves current job info dictionary to JSON file."""
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            with self.info_file.open('w') as f:
                json.dump(self.info, f, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"Failed saving {self.info_file}: {e}")

    def add_patch(self, uid: str, index: int, total_subj: int,
                  headers: EmailMessage, raw_email_bytes: bytes):
        """Adds a new patch to this job, updating its state."""
        self.patch_dir.mkdir(parents=True, exist_ok=True)

        current_total = self.info.get('total_count')
        if index == 1 and current_total != total_subj:
            if current_total is not None:
                logger.warning(f"Count change '{self.job_id}': {current_total}->{total_subj}")
            self.info['total_count'] = total_subj
        elif current_total is None:
            self.info['total_count'] = total_subj
            logger.warning(f"First patch for '{self.job_id}' is {index}. Using count {total_subj}.")
        display_total = self.info.get('total_count', 1)

        subject_content = str(make_header(decode_header(headers.get('subject', '')))).strip()
        if uid not in self.info['uids']:
            self.info['uids'].append(uid)
        if 'reply_to' not in self.info:
            try: self.info['reply_to'] = headers['From']
            except Exception: pass

        # Series name logic: 0/N (cover letter) takes precedence, otherwise 1/N
        message_id = headers.get('message-id')
        if message_id:
            message_id = message_id.strip('<>')

        if index == 0:
            # Cover letter always sets the series name
            self.info['series_name'] = subject_content
            if message_id:
                self.info['series_name_message_id'] = message_id
        elif index == 1 and 'series_name' not in self.info:
            # First patch only sets series name if no cover letter has been processed
            self.info['series_name'] = subject_content
            if message_id:
                self.info['series_name_message_id'] = message_id

        self.info['patch_subjects'][str(index)] = subject_content

        recipients = set(self.info.get('all_recipient_emails', []))
        for header_name in ['To', 'Cc']:
            for name, addr in getaddresses(headers.get_all(header_name, [])):
                if addr: recipients.add(addr.lower())
        self.info['all_recipient_emails'] = sorted(list(recipients))

        patch_file = self.patch_dir / f"patch_{index:03d}"
        if patch_file.exists():
            logger.warning(f"Overwriting {patch_file.name} for job '{self.job_id}'.")
        patch_file.write_bytes(raw_email_bytes)

        self._save_state()
        logger.info(f"Saved patch {index}/{display_total} for job '{self.job_id}'")

    def is_ready(self) -> bool:
        """Checks if the job is pending and has all patches."""
        if self.info['status'] != 'pending':
            return False

        total_count = self.info.get('total_count')
        if not total_count or total_count <= 0:
            return False

        try:
            expected_patches = {f"patch_{i:03d}" for i in range(1, total_count + 1)}
            if not self.patch_dir.exists():
                return False

            patch_files = set(f.name for f in self.patch_dir.iterdir() if f.is_file())

            if not expected_patches.issubset(patch_files):
                logger.debug(f"Job '{self.job_id}' incomplete "
                             f"({len(patch_files)}/{total_count}).")
                return False
            return True
        except FileNotFoundError:
            return False

    def _setup_git_worktree(self) -> Optional[dict]:
        """Sets up git worktree, returns dict of info or None on failure."""
        build_timestamp = time.strftime("%Y%m%d-%H%M%S")
        display_name = self.info.get('series_name', self.job_id)

        # Select tree configuration based on series name
        try:
            series_subject = self.info.get('series_name', '')
            tree_config = self.tree_selector.select_tree(series_subject)
            git_remote = tree_config['remote']
            git_branch = tree_config['branch']
            logger.info(f"Selected tree - Remote: {git_remote}, Branch: {git_branch}")
        except ValueError as e:
            logger.error(f"Tree selection failed for job '{self.job_id}': {e}")
            self._log_msg(f"\n--- Tree Selection Error ---\n{e}\n")
            return None

        build_id_prefix = "nipa-build-"
        build_id = f"{build_id_prefix}{build_timestamp}-{sanitize_id(display_name)}"[:150]

        worktree_path = WORKTREE_BASE / build_id

        self.info['build_id'] = build_id
        self.info['selected_remote'] = git_remote
        self.info['selected_branch'] = git_branch
        self._save_state()

        git_info = {
            'build_id': build_id,
            'worktree_path': str(worktree_path),
            'remote': git_remote,
            'branch': git_branch,
            'commit_info': None,
            'remote_info': None
        }

        # Run Git Setup

        # Fetch first, from the main repo dir (WORKTREE_BASE)
        cmd = ["git", "fetch", "--force", git_remote, git_branch]
        success, stdout, stderr = run_sync_command(cmd, WORKTREE_BASE)
        self._log_command_result(cmd, stdout, stderr, success)
        if not success: return None

        # Create the worktree, pointing to the remote branch ref
        remote_branch_ref = f"{git_remote}/{git_branch}"
        cmd = ["git", "worktree", "add", build_id, remote_branch_ref]
        success, stdout, stderr = run_sync_command(cmd, WORKTREE_BASE)
        self._log_command_result(cmd, stdout, stderr, success)
        if not success: return None

        # Create/reset the local branch `build_id` to point to the fetched ref
        cmd = ["git", "checkout", "-B", build_id, remote_branch_ref]
        success, stdout, stderr = run_sync_command(cmd, worktree_path)
        self._log_command_result(cmd, stdout, stderr, success)
        if not success: return None

        # Get Commit and Remote Info
        cmd = ["git", "log", "-1", "--pretty=format:%H %s", "HEAD"]
        success, stdout, stderr = run_sync_command(cmd, worktree_path)
        self._log_command_result(cmd, stdout, stderr, success)
        if success:
            git_info['commit_info'] = stdout
        else:
            return None # Fatal

        cmd = ["git", "remote", "show", git_remote]
        success, stdout, stderr = run_sync_command(cmd, worktree_path)
        self._log_command_result(cmd, stdout, stderr, success)
        if success:
            git_info['remote_info'] = stdout

        logger.info(f"Git setup successful for job '{self.job_id}'.")
        return git_info

    def _create_venv_env(self) -> dict:
        """Create environment dict with proper venv settings for subprocess calls."""
        env = os.environ.copy()
        venv_bin = self.venv_dir / "bin"

        # Add venv bin directory to PATH
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")

        # Set VIRTUAL_ENV to venv directory path
        env["VIRTUAL_ENV"] = str(self.venv_dir)

        # Remove PYTHONHOME if set (can interfere with venv)
        env.pop("PYTHONHOME", None)

        return env

    def start_build(self, notifier: SmtpNotifier):
        """Starts the build process (git setup + Popen)."""
        logger.info(f"Starting build for job '{self.job_id}'")

        if not self.info.get('reply_to'):
            logger.error(f"No reply address '{self.job_id}'. Failing.")
            self.info['status'] = 'failed_no_reply_to'
            self._save_state()
            self.cleanup(None)
            return

        try:
            self._stdout_f = self.stdout_log.open('w', encoding='utf-8')
            self._stderr_f = self.stderr_log.open('w', encoding='utf-8')
            self.results_dir.mkdir(exist_ok=True)

            git_info = self._setup_git_worktree()
            if not git_info:
                raise Exception("Git setup failed (see logs for details)")

            # Create job-specific venv
            self._log_msg(f"\n--- Creating Python venv in {self.venv_dir} ---\n")
            venv_cmd = [PYTHON_EXECUTABLE, "-m", "venv", str(self.venv_dir)]
            success, stdout, stderr = run_sync_command(venv_cmd, self.work_dir)
            self._log_command_result(venv_cmd, stdout, stderr, success)
            if not success:
                raise Exception("Failed to create Python venv")

            venv_python = self.venv_dir / "bin" / "python"
            venv_pip = self.venv_dir / "bin" / "pip"

            # Install dependencies in venv
            self._log_msg("\n--- Installing dependencies in venv ---\n")
            pip_cmd = [
                str(venv_pip), "install",
                "dtschema", "yamllint", "requests", "ply", "GitPython"
            ]
            success, stdout, stderr = run_sync_command(pip_cmd, self.work_dir)
            self._log_command_result(pip_cmd, stdout, stderr, success)
            if not success:
                raise Exception("Failed to install dependencies in venv")

            command = [
                str(venv_python), str(NIPA_INGEST_SCRIPT_PATH),
                "--mdir", str(self.patch_dir),
                "--tree", git_info['worktree_path'],
                "--result-dir", str(self.results_dir),
                "--noninteractive"
            ]
            self._log_msg(f"\n--- Running NIPA: {' '.join(command)} ---\n\n")

            # Create venv-aware environment for the subprocess
            venv_env = self._create_venv_env()

            self.process = subprocess.Popen(command, stdout=self._stdout_f,
                                            stderr=self._stderr_f, text=True,
                                            encoding='utf-8', errors='ignore',
                                            env=venv_env)

            self.info['status'] = 'running'
            self.info['pid'] = self.process.pid
            self._save_state()

            notifier.send_build_started(self.info, git_info)

        except Exception as e:
            logger.error(f"Failed launching job {self.job_id}: {e}")
            self.info['status'] = 'failed_launch'
            self._save_state()

            if self._stdout_f and not self._stdout_f.closed: self._stdout_f.close()
            if self._stderr_f and not self._stderr_f.closed: self._stderr_f.close()

            notifier.send_failure_notification(self.info, str(e), self.stdout_log, self.stderr_log)
            self.cleanup(None)

    def poll_status(self, notifier: SmtpNotifier, imap_conn) -> bool:
        """
        Polls the running Popen object.
        Returns True if the job finished, False otherwise.
        """
        if self.info['status'] != 'running':
            return False

        return_code = self.process.poll()
        if return_code is not None:
            logger.info(f"Job '{self.job_id}' finished (code: {return_code}).")
            self.handle_completion(return_code, notifier, imap_conn)
            return True

        return False

    def _archive_results(self) -> Optional[Path]:
        """Creates a zip archive of the results dir."""
        if not self.results_dir.is_dir():
            logger.info("No results directory found. Skipping archive.")
            return None

        base_archive_name = self.work_dir / 'results'
        try:
            archive_path_str = shutil.make_archive(str(base_archive_name), 'zip',
                                                   self.results_dir)
            archive_path = Path(archive_path_str)
            logger.info(f"Created results archive: {archive_path}")
            return archive_path
        except Exception as e:
            logger.error(f"Failed creating results archive: {e}")
            return None

    def handle_completion(self, return_code: int, notifier: SmtpNotifier, imap_conn):
        """Archives, notifies, and cleans up a finished job."""
        if self._stdout_f and not self._stdout_f.closed:
            self._stdout_f.close()
        if self._stderr_f and not self._stderr_f.closed:
            self._stderr_f.close()

        archive_path = self._archive_results()

        notifier.send_build_result(self.info, return_code,
                                  self.stdout_log, self.stderr_log, archive_path)

        self.info['status'] = 'completed' if return_code == 0 else 'failed'
        self.cleanup(imap_conn)

    def cleanup(self, imap_conn):
        """Handles cleanup: emails(opt), worktree(opt), branch(always), and job dir(always)."""
        build_id = self.info.get('build_id')
        uids_to_delete = self.info.get('uids', [])
        logger.info(f"Starting cleanup job '{self.job_id}'.")

        if imap_conn and uids_to_delete:
            delete_emails_by_uid(imap_conn, uids_to_delete)

        worktree_path = WORKTREE_BASE / build_id if build_id else None
        if CLEANUP_WORKTREE and build_id and worktree_path:
            logger.info(f"Cleaning worktree '{build_id}'...")
            if worktree_path.exists():
                success, _, stderr = run_sync_command(["git", "worktree", "remove",
                                                       "--force", build_id],
                                                      WORKTREE_BASE)
                if not success:
                    logger.warning(f"git worktree remove failed: {stderr}")
            else:
                logger.warning(f"Worktree path {worktree_path} not found.")
        elif build_id:
            logger.info(f"Skipping worktree cleanup for {build_id} (CLEANUP_WORKTREE=false)")

        if build_id and WORKTREE_BASE.exists():
            logger.info(f"Attempting to delete branch '{build_id}'...")
            success, _, stderr = run_sync_command(["git", "branch", "-D", build_id],
                                                  WORKTREE_BASE)
            if success:
                logger.info(f"Branch '{build_id}' deleted successfully.")
            else:
                logger.warning(f"Failed to delete branch '{build_id}': {stderr}")

        try:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
                logger.info(f"Cleaned job directory '{self.job_id}'.")
        except Exception as e:
            logger.error(f"Failed cleaning job directory {self.work_dir}: {e}")

    def terminate(self):
        """Forcefully terminates the running process on script shutdown."""
        if self.process and self.process.poll() is None:
            logger.info(f"Terminating job: {self.job_id} (PID: {self.process.pid})")
            if self._stdout_f and not self._stdout_f.closed: self._stdout_f.close()
            if self._stderr_f and not self._stderr_f.closed: self._stderr_f.close()

            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"Job {self.job_id} did not terminate, killing...")
                self.process.kill()
            logger.info(f"Job {self.job_id} terminated.")
