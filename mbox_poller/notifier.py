# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import ssl
import smtplib
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from email.message import EmailMessage
from email.utils import parseaddr

logger = logging.getLogger(__name__)

class SmtpNotifier:
    """Handles all SMTP email sending logic and configuration."""

    def __init__(self, server, port, user, password, from_addr):
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.enabled = bool(server and user and password)
        if self.enabled:
             logger.info("SMTP configured to use standard password authentication.")
        else:
             logger.warning("SMTP is not fully configured (missing server, user, or password).")

    def send_email(self, to_address: str, subject: str, body: str,
                   cc_addresses: Optional[List[str]] = None,
                   attachment_path: Optional[Path] = None,
                   in_reply_to: Optional[str] = None):
        """Sends a status email via SMTP, with optional CC list, attachment, and In-Reply-To header."""
        if not self.enabled:
            logger.warning(f"SMTP not configured. Skipping email (Subject: {subject})")
            return

        cc_addresses = cc_addresses or []
        try:
            logger.info(f"Sending email To: {to_address} "
                        f"Cc: {', '.join(cc_addresses)} (Subject: {subject})")

            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = subject
            msg['From'] = self.from_addr
            msg['To'] = to_address
            if cc_addresses:
                msg['Cc'] = ', '.join(cc_addresses)
            if in_reply_to:
                msg['In-Reply-To'] = f"<{in_reply_to}>"
                logger.debug(f"Setting In-Reply-To: <{in_reply_to}>")

            if attachment_path and attachment_path.exists():
                try:
                    with attachment_path.open("rb") as fil:
                        msg.add_attachment(fil.read(), maintype='application',
                                           subtype='zip',
                                           filename=attachment_path.name)
                    logger.info(f"Attaching file: {attachment_path}")
                except Exception as e:
                    logger.error(f"Failed attaching file {attachment_path}: {e}")
                    msg.set_content(body + f"\n\n[Warning: Failed to attach results archive: {e}]")
            elif attachment_path:
                logger.warning(f"Attachment not found: {attachment_path}")

            context = ssl.create_default_context()
            with smtplib.SMTP(self.server, self.port) as server:
                server.starttls(context=context)

                logger.debug(f"Attempting standard LOGIN for user {self.user}")
                if not self.password:
                     raise ValueError("SMTP password required but not set")
                server.login(self.user, self.password)
                logger.info(f"Standard SMTP authentication successful for {self.user}.")

                server.send_message(msg)
            logger.info(f"Email sent successfully.")

        except smtplib.SMTPAuthenticationError:
            logger.error(f"SMTP Authentication (standard password) failed for user {self.user}.")
        except Exception as e:
            logger.error(f"Failed sending email (Subject: {subject}): {e}")

    def _get_recipients(self, info: dict) -> Tuple[Optional[str], List[str]]:
        """Extracts To (reply_to) and CC lists from job info."""
        reply_to = info.get('reply_to')
        if not reply_to:
            logger.warning(f"Job {info.get('job_id')} has no 'reply_to' address.")
            return None, []

        primary_recipient_email = parseaddr(reply_to)[1].lower()
        sender_email = parseaddr(self.from_addr)[1].lower()

        cc_list = []
        for email_addr in info.get('all_recipient_emails', []):
            if email_addr and email_addr != primary_recipient_email and email_addr != sender_email:
                cc_list.append(email_addr)
        return reply_to, cc_list

    def send_build_started(self, info: dict, git_info: dict):
        """Sends the 'Build Started' notification."""
        reply_to, cc_list = self._get_recipients(info)
        if not reply_to:
            return

        display_name = info.get('series_name', info.get('job_id', 'Unknown Job'))
        subject = f"Build Started: {display_name}"

        total_count = info.get('total_count', 0)
        patch_list_str = "Patch List:\n"
        patch_subjects = info.get('patch_subjects', {})
        sorted_indices = sorted(patch_subjects.keys(), key=int)
        for idx_str in sorted_indices:
            patch_list_str += f"{idx_str.zfill(2)}/{total_count}: {patch_subjects[idx_str]}\n"

        body = (
            f"Starting build for {total_count} patches: {display_name}\n\n"
            f"(Job ID: {info.get('job_id')})\n\n"
            f"{patch_list_str}\n"
            f"Remote: {git_info.get('remote')}\n"
            f"Branch: {git_info.get('branch')}\n"
            f"Worktree: {git_info.get('worktree_path')}\n"
            f"Git HEAD: {git_info.get('commit_info', '')}\n"
            f"Remote '{git_info.get('remote')}':\n{git_info.get('remote_info', '')}\n\n"
            "Result email will follow upon completion."
        )

        in_reply_to = info.get('series_name_message_id')
        self.send_email(reply_to, subject, body, cc_addresses=cc_list, in_reply_to=in_reply_to)

    def send_build_result(self, info: dict, return_code: int,
                          stdout_log: Path, stderr_log: Path,
                          archive_path: Optional[Path]):
        """Sends the 'Build Result' notification."""
        reply_to, cc_list = self._get_recipients(info)
        if not reply_to:
            return

        display_name = info.get('series_name', info.get('job_id', 'Unknown Job'))
        success = (return_code == 0)
        subject = f"Build {'Result' if success else 'Failure'}: {display_name}"

        stdout_data, stderr_data = "", ""
        try:
            if stdout_log and stdout_log.exists():
                stdout_data = stdout_log.read_text(errors='ignore')
        except Exception as e:
            logger.warning(f"Error reading stdout log {stdout_log}: {e}")
        try:
            if stderr_log and stderr_log.exists():
                stderr_data = stderr_log.read_text(errors='ignore')
        except Exception as e:
            logger.warning(f"Error reading stderr log {stderr_log}: {e}")

        body = (
            f"Build job finished for: {display_name}\n\n"
            f"(Job ID: {info.get('job_id')})\n"
            f"Return Code: {return_code}\n\n"
            f"--- STDOUT ---\n{stdout_data}\n\n"
            f"--- STDERR ---\n{stderr_data}"
        )

        self.send_email(reply_to, subject, body,
                        cc_addresses=cc_list, attachment_path=archive_path)

    def send_failure_notification(self, info: dict, error_msg: str,
                                  stdout_log: Optional[Path] = None,
                                  stderr_log: Optional[Path] = None):
        """Sends a generic failure email (e.g., launch failure, orphan)."""
        reply_to, cc_list = self._get_recipients(info)
        if not reply_to:
            return

        display_name = info.get('series_name', info.get('job_id', 'Unknown Job'))
        subject = f"Build Failed: {display_name}"

        stdout_data, stderr_data = "", ""
        if stdout_log:
            try: stdout_data = stdout_log.read_text(errors='ignore')
            except Exception: pass
        if stderr_log:
            try: stderr_data = stderr_log.read_text(errors='ignore')
            except Exception: pass

        body = (
            f"Job '{display_name}' FAILED.\n\n"
            f"(Job ID: {info.get('job_id')})\nError: {error_msg}\n\n"
            f"--- STDOUT ---\n{stdout_data}\n\n"
            f"--- STDERR ---\n{stderr_data}"
        )

        in_reply_to = info.get('series_name_message_id')
        self.send_email(reply_to, subject, body, cc_addresses=cc_list, in_reply_to=in_reply_to)
