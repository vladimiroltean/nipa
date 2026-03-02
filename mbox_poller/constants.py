# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import os
import sys
import logging
from pathlib import Path

# Configuration

LOG_LEVEL_STR = os.environ.get('LOG_LEVEL', 'INFO').upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

ROLE = os.environ.get('ROLE', 'worker').lower()
MANAGER_CONFIG_FILE = Path(os.environ.get('MANAGER_CONFIG_FILE', '/data/manager.json'))
WORKER_CONFIG_FILE = Path(os.environ.get('WORKER_CONFIG_FILE', '/data/worker.json'))

HASH_SIZE_STR = os.environ.get('HASH_SIZE')
WORKER_INDEX_STR = os.environ.get('WORKER_INDEX')
HASH_SIZE = int(HASH_SIZE_STR) if HASH_SIZE_STR and HASH_SIZE_STR.isdigit() else 0
WORKER_INDEX = int(WORKER_INDEX_STR) if WORKER_INDEX_STR and WORKER_INDEX_STR.isdigit() else -1
WORKER_API_PORT = int(os.environ.get('WORKER_API_PORT', 8080))

IMAP_SERVER = os.environ.get('IMAP_SERVER')
IMAP_USER = os.environ.get('IMAP_USER')
IMAP_PASS_CMD = os.environ.get('IMAP_PASS_CMD') # Command to get OAuth2 token
IMAP_PASSWORD = os.environ.get('IMAP_PASSWORD') # Needed if IMAP_PASS_CMD not set
IMAP_INBOX_FOLDER = os.environ.get('IMAP_INBOX_FOLDER', 'INBOX')
EXPUNGE_EMAILS = os.environ.get('EXPUNGE_EMAILS', 'false').lower() in ('true', '1', 'yes')

POLL_INTERVAL = 60 # seconds

SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
SMTP_FROM_ADDRESS = os.environ.get('SMTP_FROM_ADDRESS', 'nipa-builder@example.com')

CLEANUP_WORKTREE = os.environ.get('CLEANUP_WORKTREE', 'false').lower() in ('true', '1', 'yes')

BLACKLIST_FILE = Path(os.environ.get('BLACKLIST_FILE', '/data/blacklist.txt'))
BLACKLIST_RELOAD_INTERVAL = 300 # seconds (5 minutes)

NIPA_INGEST_SCRIPT_PATH = Path(os.environ.get('NIPA_INGEST_SCRIPT_PATH', '/nipa/ingest_mdir.py'))
WORKTREE_BASE = Path(os.environ.get('WORKTREE_BASE', '/linux')) # Mount point for the main git repo
NIPA_WORK_DIR = Path(os.environ.get('NIPA_WORK_DIR', '/data'))  # Persistent storage for job data
PYTHON_EXECUTABLE = sys.executable # Assumes this script is run with python3
