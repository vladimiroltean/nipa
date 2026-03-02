# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import time
import logging
import imaplib
import socket
from .manager import WorkerManager
from ..imap_utils import connect_to_imap, imap_cleanup
from ..exceptions import GracefulShutdown
from ..constants import POLL_INTERVAL

logger = logging.getLogger(__name__)

def manager_loop(manager: WorkerManager):
    """ The main polling loop for the 'manager' role."""
    imap_conn = None
    try:
        while True:
            try:
                if not imap_conn or imap_conn.state == 'LOGOUT':
                    if imap_conn and imap_conn.state != 'LOGOUT':
                        imap_cleanup(imap_conn)

                    imap_conn = connect_to_imap(manager.imap_server, manager.imap_user,
                                                manager.imap_pass, manager.imap_pass_cmd,
                                                manager.imap_folder)
                    logger.info("Manager IMAP Connection ready.")

                manager.poll_and_start_workers(imap_conn)
                manager.check_all_machines_idle_status()

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
        logger.info("Manager shutting down...")
        if imap_conn:
            try: imap_conn.close(); imap_conn.logout()
            except Exception: pass
            logger.info("IMAP connection closed.")
        logger.info("Shutdown complete.")
