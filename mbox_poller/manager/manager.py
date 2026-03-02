# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import json
import time
import logging
import sys
import shlex
import subprocess
from pathlib import Path
from typing import List

from ..email_parser import EmailParser
from ..utils import run_sync_command, get_assigned_worker

logger = logging.getLogger(__name__)

class WorkerManager(EmailParser):
    """
    Handles the 'manager' role logic: polls inbox, finds jobs,
    and starts the correct machine if it's not running.
    """
    def __init__(self, config_path: Path, hash_size: int,
                 imap_server: str, imap_user: str,
                 imap_pass: str, imap_pass_cmd: str, imap_folder: str,
                 blacklist_file: Path):
        super().__init__(blacklist_file)
        self.config_path: Path = config_path
        self.hash_size: int = hash_size
        self.machines: List[dict] = []
        self.imap_server = imap_server
        self.imap_user = imap_user
        self.imap_pass = imap_pass
        self.imap_pass_cmd = imap_pass_cmd
        self.imap_folder = imap_folder
        self.idle_check_interval = 300  # Check for idle workers every 5 minutes
        self.last_idle_check = 0

    def load_config(self):
        """Loads the manager.json config file with new hierarchical structure."""
        logger.info(f"Loading manager config from {self.config_path}")
        try:
            with self.config_path.open('r') as f:
                config_data = json.load(f)

            if not isinstance(config_data, list):
                logger.critical(f"Manager config is not a list. Check {self.config_path}")
                sys.exit(1)

            if len(config_data) != self.hash_size:
                logger.critical(f"Manager config has {len(config_data)} machines, "
                                f"but HASH_SIZE is {self.hash_size}. Must have exactly HASH_SIZE machines.")
                sys.exit(1)

            # Validate machine structure
            required_machine_commands = ['start', 'stop', 'status']

            for machine_idx, machine in enumerate(config_data):
                # Validate machine-level commands
                for cmd in required_machine_commands:
                    if not machine.get(cmd):
                        logger.critical(f"Machine config {machine_idx} is missing '{cmd}' command.")
                        sys.exit(1)

                # Validate workers section
                workers = machine.get('workers', {})
                if not isinstance(workers, dict):
                    logger.critical(f"Machine config {machine_idx} 'workers' must be a dictionary.")
                    sys.exit(1)

                if not workers:
                    logger.critical(f"Machine config {machine_idx} has no workers defined.")
                    sys.exit(1)

                # Validate each worker
                for worker_name, worker_config in workers.items():
                    if not worker_config.get('idle-check'):
                        logger.critical(f"Worker '{worker_name}' in machine {machine_idx} is missing 'idle-check' command.")
                        sys.exit(1)

            self.machines = config_data
            logger.info(f"Successfully loaded config for {len(self.machines)} machines.")

            # Log the machine configuration for debugging
            for machine_idx, machine in enumerate(self.machines):
                workers_list = list(machine.get('workers', {}).keys())
                logger.info(f"  Machine {machine_idx}: {len(workers_list)} workers ({', '.join(workers_list)})")

        except FileNotFoundError:
            logger.critical(f"Manager config file not found: {self.config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.critical(f"Failed to parse manager config {self.config_path}: {e}")
            sys.exit(1)

    def get_assigned_machine(self, job_id: str) -> int:
        """
        Determines the assigned machine index for a job_id.
        Uses the same hashing as workers, but maps to machines.
        """
        return get_assigned_worker(job_id, self.hash_size)

    def check_and_start_machine(self, machine_index: int):
        """Runs status check for a machine, and starts it if it's down."""
        if not (0 <= machine_index < len(self.machines)):
            logger.error(f"Invalid machine_index {machine_index} requested. Cannot check status.")
            return

        machine_config = self.machines[machine_index]

        try:
            status_cmd = shlex.split(machine_config.get('status'))
            logger.info(f"Checking machine {machine_index} status...")
            success, stdout, stderr = run_sync_command(status_cmd, cwd=Path('.'))

            if not success:
                logger.error(f"Machine status command failed for machine {machine_index} (return code non-zero). stderr: {stderr}")
                return

            try:
                status_data = json.loads(stdout.strip())
                machine_status = status_data.get('status', '').lower()
                machine_name = status_data.get('name', f'machine-{machine_index}')

                logger.info(f"Machine {machine_index} ({machine_name}) status: {machine_status}")

                if machine_status == 'running':
                    logger.info(f"Machine {machine_index} is running.")
                elif machine_status == 'stopped':
                    logger.warning(f"Machine {machine_index} is stopped. Starting...")
                    start_cmd_str = machine_config.get('start')
                    start_cmd = shlex.split(start_cmd_str)

                    logger.info(f"Running start command for machine {machine_index}: {start_cmd_str}")
                    subprocess.Popen(start_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif machine_status == 'stopping':
                    logger.info(f"Machine {machine_index} is stopping. Waiting for it to complete shutdown...")
                else:
                    logger.warning(f"Machine {machine_index} has unknown status: {machine_status}")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON output from machine status command for machine {machine_index}: {e}")
                logger.error(f"Raw stdout: {stdout}")
            except KeyError as e:
                logger.error(f"Missing expected field in machine status JSON for machine {machine_index}: {e}")
                logger.error(f"Raw stdout: {stdout}")

        except Exception as e:
            logger.error(f"Failed to check/start machine {machine_index}: {e}")

    def check_machine_idle_and_stop(self, machine_idx: int):
        """Check if all workers on a machine are idle and stop the machine if so."""
        if not (0 <= machine_idx < len(self.machines)):
            return

        machine_config = self.machines[machine_idx]

        status_cmd = shlex.split(machine_config.get('status'))
        success, stdout, stderr = run_sync_command(status_cmd, cwd=Path('.'))

        if not success:
            return

        try:
            status_data = json.loads(stdout.strip())
            if status_data.get('status', '').lower() != 'running':
                return

        except json.JSONDecodeError:
            return

        all_workers_idle = True
        workers_checked = 0

        for worker_name, worker_config in machine_config.get('workers', {}).items():
            workers_checked += 1
            idle_cmd = shlex.split(worker_config.get('idle-check'))
            success, stdout, stderr = run_sync_command(idle_cmd, cwd=Path('.'))

            if not success:
                logger.debug(f"Failed to check idle status for worker '{worker_name}' on machine {machine_idx} - assuming not idle")
                all_workers_idle = False
                continue

            try:
                idle_data = json.loads(stdout.strip())
                is_idle = idle_data.get('idle', False)

                if not is_idle:
                    logger.debug(f"Worker '{worker_name}' on machine {machine_idx} is busy")
                    all_workers_idle = False
                else:
                    logger.debug(f"Worker '{worker_name}' on machine {machine_idx} is idle")

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse idle check response for worker '{worker_name}' on machine {machine_idx}: {e}")
                all_workers_idle = False

        if workers_checked == 0:
            logger.warning(f"No workers configured for machine {machine_idx}")
            return

        if all_workers_idle:
            logger.info(f"All {workers_checked} workers on machine {machine_idx} are idle. Stopping machine...")
            stop_cmd = shlex.split(machine_config.get('stop'))
            subprocess.Popen(stop_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            logger.debug(f"Machine {machine_idx} has busy workers, keeping it running.")

    def check_all_machines_idle_status(self):
        """Check idle status for all machines if it's time."""
        current_time = time.monotonic()
        if current_time - self.last_idle_check < self.idle_check_interval:
            return

        logger.info("Checking idle status for all machines...")
        for machine_idx in range(len(self.machines)):
            self.check_machine_idle_and_stop(machine_idx)

        self.last_idle_check = current_time

    def poll_and_start_workers(self, imap_conn):
        """
        Polls inbox for UNSEEN emails, finds assigned machines,
        and triggers status checks/starts.
        DOES NOT MARK EMAILS AS SEEN.
        """
        parsed_emails = self.fetch_and_parse_emails(imap_conn, fetch_body=False)

        machines_to_check = set()
        job_ids_processed_this_run = set()

        for msg_uid, headers, raw_email_bytes, job_id, patch_info in parsed_emails:
            try:
                # Skip emails that failed parsing or aren't patch emails
                if headers is None or job_id is None or patch_info is None:
                    continue

                # Avoid duplicate processing of the same job
                if job_id in job_ids_processed_this_run:
                    continue

                job_ids_processed_this_run.add(job_id)

                assigned_machine = self.get_assigned_machine(job_id)
                logger.debug(f"Job '{job_id}' (from UID {msg_uid}) assigned to machine {assigned_machine}.")
                machines_to_check.add(assigned_machine)

            except Exception as e:
                logger.exception(f"Failed processing email UID {msg_uid} in manager")

        if machines_to_check:
            logger.info(f"New patch jobs found for machines: {machines_to_check}")
            for machine_index in machines_to_check:
                self.check_and_start_machine(machine_index)
