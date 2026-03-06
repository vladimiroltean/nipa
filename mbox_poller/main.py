# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import os
import sys
import signal
import logging
from pathlib import Path

from .constants import (
    LOG_LEVEL, ROLE, MANAGER_CONFIG_FILE, WORKER_CONFIG_FILE,
    HASH_SIZE, WORKER_INDEX, IMAP_SERVER, IMAP_USER, IMAP_PASSWORD,
    IMAP_PASS_CMD, IMAP_INBOX_FOLDER, BLACKLIST_FILE,
    SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS_CMD, SMTP_PASSWORD, SMTP_FROM_ADDRESS,
    NIPA_INGEST_SCRIPT_PATH, WORKTREE_BASE, NIPA_WORK_DIR
)
from .exceptions import GracefulShutdown
from .notifier import SmtpNotifier
from .worker.manager import JobManager
from .worker.tree_selector import TreeSelector
from .worker.loop import worker_loop
from .manager.manager import WorkerManager
from .manager.loop import manager_loop

# Configure logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Raises GracefulShutdown exception to trigger the main loop's finally block."""
    logger.info(f"Received signal {signal.Signals(signum).name}. Requesting graceful shutdown...")
    raise GracefulShutdown()

def main():
    imap_auth_ok = bool(os.environ.get('IMAP_PASSWORD') or os.environ.get('IMAP_PASS_CMD'))
    if not imap_auth_ok:
        logger.critical("Missing IMAP_PASSWORD or IMAP_PASS_CMD")
        sys.exit(1)
    if not os.environ.get('IMAP_SERVER') or not os.environ.get('IMAP_USER'):
        logger.critical("Missing IMAP_SERVER or IMAP_USER")
        sys.exit(1)

    if HASH_SIZE <= 0:
        logger.critical(f"HASH_SIZE must be set and be an integer > 0.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

    # Role-specific execution
    if ROLE == 'worker':
        # Worker-specific validation
        if WORKER_INDEX < 0:
            logger.critical(f"WORKER_INDEX must be set for 'worker' role.")
            sys.exit(1)
        if not (0 <= WORKER_INDEX < HASH_SIZE):
              logger.critical(f"WORKER_INDEX ({WORKER_INDEX}) is out of valid range [0, {HASH_SIZE-1}].")
              sys.exit(1)

        smtp_auth_ok = bool(os.environ.get('SMTP_PASSWORD') or os.environ.get('SMTP_PASS_CMD'))
        required_env_vars = ['SMTP_SERVER', 'SMTP_USER']
        missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
        if not smtp_auth_ok:
            missing_vars.append("SMTP_PASSWORD or SMTP_PASS_CMD")
        if missing_vars:
            logger.critical(f"Worker missing required env vars: {', '.join(missing_vars)}")
            sys.exit(1)

        if not NIPA_INGEST_SCRIPT_PATH.exists():
            logger.error(f"NIPA script not found: {NIPA_INGEST_SCRIPT_PATH}")
            sys.exit(1)
        if not WORKTREE_BASE.exists():
              logger.warning(f"Git worktree base directory not found: {WORKTREE_BASE}")

        # Ensure work dir exists
        try:
            NIPA_WORK_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured NIPA work directory exists: {NIPA_WORK_DIR}")
        except OSError as e:
            logger.error(f"Could not create NIPA work directory {NIPA_WORK_DIR}: {e}")
            sys.exit(1)

        # Load tree selector
        try:
            tree_selector = TreeSelector(WORKER_CONFIG_FILE)
        except (FileNotFoundError, ValueError) as e:
            logger.critical(f"Failed to load worker configuration: {e}")
            sys.exit(1)

        notifier = SmtpNotifier(SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
                                SMTP_PASS_CMD, SMTP_FROM_ADDRESS)
        job_manager = JobManager(NIPA_WORK_DIR, notifier, BLACKLIST_FILE,
                                 WORKER_INDEX, HASH_SIZE, tree_selector)
        job_manager.discover_and_reap_jobs()
        worker_loop(job_manager)

    elif ROLE == 'manager':
        # Manager-specific validation
        if not MANAGER_CONFIG_FILE.exists():
            logger.critical(f"Manager config file not found: {MANAGER_CONFIG_FILE}")
            sys.exit(1)

        # Start manager
        manager = WorkerManager(MANAGER_CONFIG_FILE, HASH_SIZE, IMAP_SERVER,
                                IMAP_USER, IMAP_PASSWORD, IMAP_PASS_CMD,
                                IMAP_INBOX_FOLDER, BLACKLIST_FILE)
        manager.load_config()
        manager_loop(manager)

    else:
        logger.critical(f"Invalid ROLE '{ROLE}'. Must be 'worker' or 'manager'.")
        sys.exit(1)

if __name__ == "__main__":
    main()
