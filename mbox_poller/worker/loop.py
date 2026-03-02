# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import time
import logging
import imaplib
import socket
from .manager import JobManager
from .api import WorkerAPIServer
from ..imap_utils import connect_to_imap, imap_cleanup
from ..exceptions import GracefulShutdown
from ..constants import (
    IMAP_SERVER, IMAP_USER, IMAP_PASSWORD, IMAP_PASS_CMD,
    IMAP_INBOX_FOLDER, POLL_INTERVAL, NIPA_WORK_DIR, WORKER_API_PORT
)

logger = logging.getLogger(__name__)

def worker_loop(manager: JobManager):
    """ The main polling loop for the 'worker' role."""
    imap_conn = None
    api_server = None
    api_server_started = False

    try:
        while True:
            try:
                if not imap_conn or imap_conn.state == 'LOGOUT':
                    if imap_conn and imap_conn.state != 'LOGOUT':
                        imap_cleanup(imap_conn)

                    imap_conn = connect_to_imap(IMAP_SERVER, IMAP_USER,
                                                IMAP_PASSWORD, IMAP_PASS_CMD,
                                                IMAP_INBOX_FOLDER)
                    logger.info("Worker IMAP Connection ready.")

                manager.process_email_batch(imap_conn)
                manager.manage_build_jobs(imap_conn)

                # Start the API server after the first processing cycle
                if not api_server_started:
                    api_server = WorkerAPIServer(NIPA_WORK_DIR, WORKER_API_PORT)
                    api_server.start()
                    api_server_started = True

                logger.debug(f"Sleeping for {POLL_INTERVAL} seconds...")
                time.sleep(POLL_INTERVAL)

            except ConnectionError as e:
                logger.warning(f"Network connectivity issue: {e}")
                logger.info("Will retry with longer delay to allow network recovery...")
                if imap_conn:
                    imap_cleanup(imap_conn)
                imap_conn = None
                time.sleep(300)  # 5 minute delay for network issues
            except (imaplib.IMAP4.abort, socket.error, imaplib.IMAP4.error) as e:
                if "AccessTokenExpired" in str(e):
                    logger.info(f"IMAP session invalidated (e.g., token expired): {e}. Reconnecting in 60s...")
                else:
                    logger.error(f"IMAP/Socket error: {e}. Reconnecting in 60s...")

                if imap_conn:
                    imap_cleanup(imap_conn)
                imap_conn = None; time.sleep(60)
            except Exception as e:
                logger.exception("Unexpected error in loop iteration")
                if imap_conn:
                    imap_cleanup(imap_conn)
                imap_conn = None; time.sleep(60)

    except (KeyboardInterrupt, GracefulShutdown):
        logger.info("\nShutdown requested.")

    finally:
        logger.info("Worker shutting down...")

        if api_server:
            api_server.stop()

        if imap_conn:
            try: imap_conn.close(); imap_conn.logout()
            except Exception: pass
            logger.info("IMAP connection closed.")

        manager.terminate_all_jobs()
        logger.info("Shutdown complete.")
