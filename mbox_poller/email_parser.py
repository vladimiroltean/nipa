# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import re
import time
import logging
import imaplib
import socket
from pathlib import Path
from typing import Optional, Tuple, List
from email.policy import default
from email.parser import BytesParser
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.utils import parseaddr

from .utils import sanitize_id
from .constants import BLACKLIST_RELOAD_INTERVAL

logger = logging.getLogger(__name__)

class EmailParser:
    """Handles common email fetching and parsing logic for both workers and managers."""

    def __init__(self, blacklist_file: Path):
        self.blacklist_file = blacklist_file
        self.blacklist: set[str] = set()
        self.last_blacklist_reload_time: float = 0.0

    def is_patch_email(self, subject_content: str) -> Optional[Tuple[int, int]]:
        """Check if an email subject indicates it's a patch email.

        Parameters
        ----------
        subject_content : str
            The email subject string to check.

        Returns
-------
        tuple of int
            (patch_index, total_patches) if it's a patch email, None otherwise.
        """
        if not subject_content:
            return None

        patch_regex = re.compile(r'^\[.*?(?:PATCH|RFC).*?(?:\s*(\d+)/(\d+))?\s*\]', re.IGNORECASE)
        match = patch_regex.search(subject_content)
        if not match:
            return None

        patch_index = int(match.group(1) or 1)
        total_patches_subj = int(match.group(2) or 1)
        return (patch_index, total_patches_subj)

    def get_thread_root_id(self, msg: EmailMessage) -> Optional[str]:
        """Determine the root Message-ID of an email thread.

        Uses References or Message-ID.

        Parameters
        ----------
        msg : EmailMessage
            The email message to analyze.

        Returns
        -------
        str
            The root Message-ID, or None if not found.
        """
        references = msg.get_all('references', [])
        if references:
            first_ref = references[0].split()[0]
            return first_ref.strip('<>')
        message_id = msg.get('message-id')
        return message_id.strip('<>') if message_id else None

    def _load_blacklist(self):
        """Loads sender email addresses from the blacklist file."""
        logger.info(f"Attempting to load blacklist from {self.blacklist_file}...")
        new_blacklist = set()
        try:
            if self.blacklist_file.exists():
                with self.blacklist_file.open('r', encoding='utf-8') as f:
                    for line in f:
                        email_addr = line.strip().lower()
                        if email_addr and not email_addr.startswith('#'):
                            new_blacklist.add(email_addr)
                logger.info(f"Loaded {len(new_blacklist)} addresses into blacklist.")
            else:
                logger.info("Blacklist file not found. Starting with an empty blacklist.")
        except OSError as e:
            logger.error(f"Error reading blacklist file {self.blacklist_file}: {e}")
            return
        except Exception as e:
             logger.error(f"Unexpected error loading blacklist: {e}")
             return

        self.blacklist = new_blacklist
        self.last_blacklist_reload_time = time.monotonic()

    def fetch_and_parse_emails(self, imap_conn, fetch_body: bool = False):
        """Fetch and parse UNSEEN emails from IMAP.

        Always uses BODY.PEEK to avoid marking emails as seen.

        Parameters
        ----------
        imap_conn : imaplib.IMAP4_SSL
            IMAP connection.
        fetch_body : bool, optional
            If True, also fetch the full email body (default is False).

        Returns
        -------
        list of tuples
            (uid, headers, raw_email_bytes, job_id, patch_info)
            or (uid, None, None, None, None) for emails that should be skipped.
        """
        try:
            status, messages = imap_conn.uid('search', None, 'UNSEEN')
            if status != 'OK':
                logger.error("IMAP search failed."); return []
            message_ids = messages[0].split()
            if not message_ids:
                logger.debug("No new emails."); return []

            logger.info(f"Found {len(message_ids)} new email(s).")

            # Reload blacklist if needed
            current_time = time.monotonic()
            if current_time - self.last_blacklist_reload_time > BLACKLIST_RELOAD_INTERVAL:
                self._load_blacklist()

            parsed_emails = []

            for msg_uid_bytes in message_ids:
                msg_uid = msg_uid_bytes.decode()
                try:
                    # Always use BODY.PEEK to avoid marking as seen
                    fetch_parts = '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID REFERENCES IN-REPLY-TO TO CC)])'
                    status, hdata = imap_conn.uid('fetch', msg_uid, fetch_parts)

                    # Find the actual header data in the response
                    header_tuple = None
                    if status == 'OK' and hdata:
                        for item in hdata:
                            if isinstance(item, tuple) and len(item) == 2:
                                response_key = item[0].upper()
                                if b'BODY' in response_key and b'HEADER.FIELDS' in response_key:
                                    header_tuple = item
                                    break

                    if not header_tuple:
                        logger.warning(f"Invalid header structure (tuple not found) for UID {msg_uid}. Response: {hdata}. Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    header_bytes = header_tuple[1]
                    if not isinstance(header_bytes, bytes):
                        logger.warning(f"No valid header data (bytes) for UID {msg_uid}. Got: {header_bytes!r}. Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    headers = BytesParser(policy=default).parsebytes(header_bytes)

                    # Check blacklist
                    try:
                        from_header = headers.get('From', '')
                        sender_name, sender_addr = parseaddr(from_header)
                        sender_addr_lower = sender_addr.lower()

                        if sender_addr_lower in self.blacklist:
                            logger.warning(f"Sender '{sender_addr}' is blacklisted. Skipping UID {msg_uid}.")
                            parsed_emails.append((msg_uid, None, None, None, None))
                            continue
                    except Exception as e:
                        logger.error(f"Error during blacklist check for UID {msg_uid}: {e}")

                    # Check if it's a patch email
                    subject_content = str(make_header(decode_header(headers.get('subject', '')))).strip()
                    if not subject_content:
                        logger.warning(f"No subject for UID {msg_uid}. Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    patch_info = self.is_patch_email(subject_content)
                    if not patch_info:
                        logger.debug(f"Not patch email (UID {msg_uid}, Subj: '{subject_content}'). Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    # Get job ID
                    thread_root_id = self.get_thread_root_id(headers)
                    if not thread_root_id:
                        logger.warning(f"No thread root ID for UID {msg_uid}. Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    job_id = sanitize_id(thread_root_id)
                    if not job_id:
                        logger.error(f"Cannot sanitize thread ID: {thread_root_id}. Skipping.")
                        parsed_emails.append((msg_uid, None, None, None, None))
                        continue

                    # Fetch full email body if requested (always with PEEK)
                    raw_email_bytes = None
                    if fetch_body:
                        status, mdata = imap_conn.uid('fetch', msg_uid, '(BODY.PEEK[])')
                        if status != 'OK' or not mdata or not isinstance(mdata[0], tuple) or len(mdata[0]) < 2 or not isinstance(mdata[0][1], bytes):
                            logger.error(f"Failed fetching valid body for UID {msg_uid}. Response: {mdata}. Skipping.")
                            parsed_emails.append((msg_uid, None, None, None, None))
                            continue
                        raw_email_bytes = mdata[0][1]

                    parsed_emails.append((msg_uid, headers, raw_email_bytes, job_id, patch_info))

                except Exception as e:
                    logger.exception(f"Failed processing email UID {msg_uid}")
                    parsed_emails.append((msg_uid, None, None, None, None))

            return parsed_emails

        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error) as e:
            if "AccessTokenExpired" in str(e):
                logger.warning(f"IMAP session invalidated (token expired?): {e}. Re-raising to trigger reconnect.")
            else:
                logger.error(f"IMAP/Socket error in email processing: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in email processing")
            return []
