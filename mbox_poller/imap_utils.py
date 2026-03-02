# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import imaplib
import socket
import ssl
import logging
import subprocess
from typing import List
from .constants import EXPUNGE_EMAILS

logger = logging.getLogger(__name__)

def imap_cleanup(imap_conn):
    """Safely cleans up an IMAP connection."""
    if not imap_conn:
        return
    try:
        if imap_conn.state in ('SELECTED', 'AUTH'):
            imap_conn.close()
    except Exception:
        pass
    try:
        imap_conn.logout()
    except Exception:
        try:
            imap_conn.abort()
        except Exception:
            pass

def delete_emails_by_uid(imap_conn, uid_list: List[str]):
    """Marks emails deleted by UID and optionally expunges if EXPUNGE_EMAILS is true."""
    if not uid_list or not imap_conn:
        return
    if not EXPUNGE_EMAILS:
        logger.info("Skipping email deletion (EXPUNGE_EMAILS=false).")
        return

    try:
        # Process UIDs in chunks to avoid IMAP command length limits
        chunk_size = 1000
        for i in range(0, len(uid_list), chunk_size):
            chunk = uid_list[i:i + chunk_size]
            uid_str = ','.join(map(str, chunk))
            logger.info(f"Marking chunk of {len(chunk)} emails for deletion (UIDs: {uid_str})...")
            res_store, _ = imap_conn.uid('store', uid_str, '+FLAGS', '\\Deleted')
            if res_store != 'OK':
                 logger.warning(f"Failed marking emails deleted for chunk: {res_store}")

        logger.info(f"Expunging deleted emails...")
        res_expunge, data = imap_conn.expunge()
        if res_expunge == 'OK':
            logger.info(f"Expunge successful (response: {data}).")
        else:
             logger.warning(f"Expunge command failed/unexpected status: {res_expunge} {data}")

    except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error) as e:
        logger.error(f"IMAP error during email deletion: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during email deletion: {e}")

def connect_to_imap(server, user, password, pass_cmd, inbox_folder) -> imaplib.IMAP4_SSL:
    """
    Establishes and authenticates an IMAP connection.
    Raises exceptions on failure.
    """
    logger.info(f"Connecting to {server}...")
    try:
        imap_conn = imaplib.IMAP4_SSL(server)
        logger.debug(f"IMAP SSL connection established. Current state: {imap_conn.state}")
    except (imaplib.IMAP4.error, socket.error, ssl.SSLError) as e:
        logger.error(f"Failed during IMAP SSL connection/handshake: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during IMAP connection: {e}")
        raise

    # IMAP Authentication
    try:
        if pass_cmd:
            logger.info(f"Attempting IMAP XOAUTH2 authentication for {user}")
            import shlex
            process = subprocess.run(shlex.split(pass_cmd), shell=False, capture_output=True,
                                     text=True, check=False)

            if process.returncode != 0:
                stdout_output = process.stdout.strip() if process.stdout else "(no stdout)"
                stderr_output = process.stderr.strip() if process.stderr else "(no stderr)"

                # Check for specific network/connectivity issues
                network_error_indicators = [
                    'Connection refused',
                    'Unable to connect to proxy',
                    'Max retries exceeded',
                    'ProxyError',
                    'NewConnectionError',
                    'HTTPSConnectionPool',
                    'Network is unreachable',
                    'Temporary failure in name resolution'
                ]

                is_network_error = any(indicator in stderr_output for indicator in network_error_indicators)

                if is_network_error:
                    logger.error("OAuth2 authentication failed due to network connectivity issues")
                    # Raise a specific exception type for network errors
                    raise ConnectionError(f"OAuth2 authentication failed due to network connectivity: {stderr_output}")
                else:
                    logger.error(f"OAuth2 command failed with exit code {process.returncode}")
                    logger.error(f"Command stdout: {stdout_output}")
                    logger.error(f"Command stderr: {stderr_output}")
                    raise subprocess.CalledProcessError(process.returncode, pass_cmd,
                                                        process.stdout, process.stderr)

            access_token = process.stdout.strip()
            if not access_token:
                raise ValueError("Command returned empty access token for IMAP")

            auth_string = f"user={user}\1auth=Bearer {access_token}\1\1"
            imap_conn.authenticate('XOAUTH2', lambda x: auth_string.encode('utf-8'))
            logger.info(f"IMAP XOAUTH2 authentication successful for {user}.")
        else:
            logger.info(f"Attempting standard IMAP LOGIN for {user}")
            if not password:
                 raise ValueError("IMAP password required but not set (and IMAP_PASS_CMD not configured)")
            imap_conn.login(user, password)
            logger.info(f"Standard IMAP authentication successful for {user}.")

    except ConnectionError:
        # Re-raise network errors without wrapping them
        imap_cleanup(imap_conn)
        raise
    except (imaplib.IMAP4.error, subprocess.CalledProcessError, Exception) as e:
        logger.error(f"IMAP Authentication failed: {e}")
        imap_cleanup(imap_conn)
        raise

    if imap_conn.state != 'AUTH':
         logger.error(f"IMAP connection not in AUTH state after authentication (state: {imap_conn.state}).")
         imap_cleanup(imap_conn)
         raise imaplib.IMAP4.error("IMAP not in AUTH state.")

    logger.info(f"Selecting folder '{inbox_folder}'...")
    status, _ = imap_conn.select(inbox_folder)
    if status != 'OK':
        logger.error(f"Failed selecting folder '{inbox_folder}'. Response: {status}.")
        imap_cleanup(imap_conn)
        raise imaplib.IMAP4.error(f"Failed to select folder {inbox_folder}")

    if imap_conn.state != 'SELECTED':
         logger.error(f"IMAP not in SELECTED state after selecting folder (state: {imap_conn.state}).")
         imap_cleanup(imap_conn)
         raise imaplib.IMAP4.error("IMAP not in SELECTED state.")

    return imap_conn
