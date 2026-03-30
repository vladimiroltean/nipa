#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0

"""NIPA Sashiko Poller - Bridge Sashiko AI reviews to Patchwork checks

Polls Patchwork for new series, correlates them with Sashiko reviews
using Message-IDs, and posts check results back to Patchwork.
"""

import argparse
import configparser
import json
import os
import sys
import time
import socket
import traceback
from datetime import datetime, timedelta, UTC
from typing import Dict, List, Optional, Tuple
import requests
from email import message_from_string

from core import NIPA_DIR, log_init, log, log_open_sec, log_end_sec
from pw import Patchwork, PwSeries


class PwSashikoPoller:
    """Poll Patchwork for series and correlate with Sashiko reviews"""

    def __init__(self):
        """Initialize poller

        Args:
            config_path: Path to configuration file
        """
        self.config = configparser.ConfigParser()
        self.config.read(['nipa.config', 'pw.config'])

        # Sashiko configuration
        self.sashiko_url = self.config.get('sashiko', 'url', fallback='https://sashiko.dev').rstrip('/')
        self.check_name = self.config.get('sashiko', 'check_name', fallback='sashiko')

        # Polling configuration
        self.poll_interval = self.config.getint('sashiko', 'poll_interval', fallback=120)
        self.state_file = self.config.get('sashiko', 'state_file',
                                          fallback='pw-sashiko-poller.state')

        # Initialize logging
        log_dir = self.config.get('log', 'dir', fallback=NIPA_DIR)
        log_init(self.config.get('log', 'type', fallback='org'),
                 self.config.get('log', 'file', fallback=os.path.join(log_dir, 'pw-sashiko-poller.org')),
                 force_single_thread=True)

        # Initialize Patchwork client
        self.patchwork = Patchwork(self.config)

        # State
        self.last_event_ts: Optional[str] = None
        self.processed_series: set = set()  # Series IDs we've processed
        self.queue: List[int] = []          # Series IDs waiting for Sashiko review

        self.load_state()

        # Local socket for manual re-processing
        self._local_sock = None
        self._start_lock_sock()

    def _start_lock_sock(self) -> None:
        socket_path = self.config.get('sashiko', 'local_sock_path', fallback=None)
        if not socket_path:
            return

        if os.path.exists(socket_path):
            os.unlink(socket_path)

        self._local_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._local_sock.setblocking(False)
        self._local_sock.bind(socket_path)
        self._local_sock.listen(5)

        log(f"Socket listener started on {socket_path}", "")

    def _check_local_sock(self) -> None:
        if not self._local_sock:
            return

        try:
            conn, _ = self._local_sock.accept()
        except BlockingIOError:
            return

        log_open_sec("Processing local socket connection")
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                data += chunk
                if len(chunk) < 4096:
                    break

            if data:
                data = data.decode("utf-8")
                series_ids = []
                items = data.split(";")
                for item in items:
                    item = item.strip()
                    if not item:
                        continue

                    # We accept "series [tree]; series [tree]; ..."
                    # tree is ignored for sashiko but kept for compatibility
                    parts = item.rsplit(" ", 1)
                    try:
                        s_id = int(parts[0].strip())
                        series_ids.append(s_id)
                        log("Processing", s_id)
                    except ValueError:
                        log("Invalid number in tuple", item)
                        continue

                for series_id in series_ids:
                    try:
                        pw_series = self.patchwork.get("series", series_id)
                        if self.process_series(pw_series):
                            self.processed_series.add(series_id)
                            if series_id in self.queue:
                                self.queue.remove(series_id)
                            self.save_state()
                        elif series_id not in self.queue:
                            self.queue.append(series_id)
                            self.save_state()
                        conn.sendall(f"OK: {series_id}\n".encode("utf-8"))
                    except Exception as e:
                        log("Error processing series", str(e))
                        conn.sendall(f"ERROR: {series_id}: {e}\n".encode("utf-8"))
            else:
                conn.sendall(b"DONE\n")
        except Exception as e:
            log("Error processing socket request", str(e))
        finally:
            conn.close()
            log_end_sec()

    def load_state(self):
        """Load state from disk"""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            self.last_event_ts = state.get('last_event_ts')
            self.processed_series = set(state.get('processed_series', []))
            self.queue = state.get('queue', [])

            log(f"Loaded state: {len(self.processed_series)} processed, {len(self.queue)} pending")
        except Exception as e:
            log(f"Error loading state: {e}")

    def save_state(self):
        """Save state to disk"""
        # Trim processed series to last 1000
        processed_list = list(self.processed_series)
        if len(processed_list) > 1000:
            processed_list = processed_list[-1000:]
            self.processed_series = set(processed_list)

        state = {
            'last_event_ts': self.last_event_ts,
            'processed_series': processed_list,
            'queue': self.queue,
            'last_save': datetime.now(UTC).isoformat()
        }

        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            log(f"Error saving state: {e}")

    def get_since_timestamp(self) -> str:
        """Get timestamp to poll from"""
        three_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)

        if self.last_event_ts:
            try:
                last_ts = datetime.fromisoformat(self.last_event_ts)
                if last_ts > three_days_ago:
                    return self.last_event_ts
            except ValueError:
                pass

        return three_days_ago.strftime('%Y-%m-%dT%H:%M:%S')

    def get_message_id(self, series: PwSeries) -> Optional[str]:
        """Extract the root Message-ID of the series for Sashiko lookup"""
        if series.cover_letter:
            msg = message_from_string(series.cover_letter)
            msgid = msg.get('Message-ID')
            if msgid:
                return msgid.strip('<>')

        if series.patches:
            # PwSeries ensures patches are available if received_all is True
            msg = message_from_string(series.patches[0].raw_patch)
            msgid = msg.get('Message-ID')
            if msgid:
                return msgid.strip('<>')

        return None

    def post_patchwork_checks(self, series: PwSeries, sashiko_data: Dict) -> bool:
        """Post Sashiko review results as Patchwork checks"""
        msgid = sashiko_data.get('message_id')
        sashiko_url = f"{self.sashiko_url}/#/patchset/{msgid}"

        # Build map of part_index to review results
        patch_reviews = {}
        reviews = sashiko_data.get('reviews', [])
        patches = sashiko_data.get('patches', [])

        # Create map: patch_id -> part_index
        id_to_index = {p['id']: p['part_index'] for p in patches}

        for r in reviews:
            pid = r.get('patch_id')
            idx = id_to_index.get(pid)
            if idx:
                # We might have multiple reviews, take the latest one
                patch_reviews[idx] = r.get('inline_review', '')
                if (patch_reviews[idx]):
                    patch_reviews[idx] = patch_reviews[idx].strip()

        try:
            for i, patch in enumerate(series.patches):
                idx = i + 1
                patch_id = patch.id

                review_text = patch_reviews.get(idx, "")

                if not review_text and sashiko_data.get('status') != 'Reviewed':
                     # If status is not "Reviewed", and we don't have a review for this patch,
                     # we should probably wait.
                     log(f"  Patch {idx} has no review yet, and status is {sashiko_data.get('status')}")
                     return False

                if not review_text:
                     state = 'success'
                     desc = 'Sashiko AI review completed, no issues found'
                elif "No issues found" in review_text:
                     state = 'success'
                     desc = 'Sashiko AI review completed, no issues found'
                else:
                     state = 'warning'
                     desc = 'Sashiko AI review found potential issues'

                log(f"  Patch {idx} (id={patch_id}): {state}")
                self.patchwork.post_check(patch=patch_id, name=self.check_name,
                                         state=state, url=sashiko_url, desc=desc)

            log(f"Posted checks for {len(series.patches)} patches in series {series.id}")
            return True

        except Exception as e:
            log(f"Error posting checks: {e}")
            return False

    def process_series(self, pw_series_data: Dict) -> bool:
        """Process a single series and correlate with Sashiko"""
        series_id = pw_series_data['id']
        name = pw_series_data.get('name', 'Unknown')

        log_open_sec(f"Processing series {series_id}: {name}")

        try:
            # Initialize PwSeries which fetches cover/patches
            series = PwSeries(self.patchwork, pw_series_data)
            msgid = self.get_message_id(series)

            if not msgid:
                log("Could not extract Message-ID")
                log_end_sec()
                return True # Nothing more we can do

            log(f"Message-ID: {msgid}")

            # Query Sashiko API
            api_url = f"{self.sashiko_url}/api/patch?id={msgid}"
            response = requests.get(api_url, timeout=30)

            if response.status_code == 404:
                log("Series not found on Sashiko yet")
                log_end_sec()
                return False # Retry later

            response.raise_for_status()
            data = response.json()

            if data.get('failed_reason'):
                log(f"Sashiko failed: {data['failed_reason']}")
                log_end_sec()
                return True # Mark as processed

            status = data.get('status')
            if status != 'Reviewed':
                log(f"Sashiko status is {status}, not Reviewed yet")
                log_end_sec()
                return False # Retry later

            # All good, post checks
            if self.post_patchwork_checks(series, data):
                log_end_sec()
                return True
            else:
                log("Failed to post checks")
                log_end_sec()
                return False

        except Exception as e:
            log(f"Error processing series: {e}")
            traceback.print_exc()
            log_end_sec()
            return False

    def poll_once(self):
        """Run one polling iteration"""
        since = self.get_since_timestamp()

        log_open_sec(f"Polling patchwork since {since}")

        try:
            json_resp, new_since = self.patchwork.get_new_series(since=since)
            log(f"Found {len(json_resp)} series")

            if new_since:
                ts = datetime.fromisoformat(new_since)
                ts += timedelta(microseconds=1)
                self.last_event_ts = ts.isoformat()

            for pw_series in json_resp:
                series_id = pw_series['id']

                if series_id in self.processed_series:
                    continue

                if not pw_series.get('received_all', True):
                    log(f"Series {series_id} incomplete, skipping")
                    continue

                if series_id not in self.queue:
                    self.queue.append(series_id)

            if self.queue:
                log(f"Processing queue: {len(self.queue)} series pending")

            still_pending = []
            for series_id in self.queue:
                try:
                    pw_series = self.patchwork.get("series", series_id)
                    if self.process_series(pw_series):
                        self.processed_series.add(series_id)
                    else:
                        still_pending.append(series_id)
                except Exception as e:
                    log(f"Error processing series {series_id} from queue: {e}")
                    still_pending.append(series_id)

            self.queue = still_pending
            self.save_state()

            # Check local socket for manual commands
            self._check_local_sock()

        except Exception as e:
            log(f"Error during poll: {e}")
            traceback.print_exc()

        log_end_sec()

    def run(self):
        """Run polling loop"""
        log(f"Starting pw_sashiko_poller")
        log(f"  Sashiko URL: {self.sashiko_url}")
        log(f"  Check name: {self.check_name}")
        log(f"  Poll interval: {self.poll_interval}s")

        while True:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                log("Shutting down...")
                self.save_state()
                break
            except Exception as e:
                log(f"Error in main loop: {e}")
                traceback.print_exc()

            time.sleep(self.poll_interval)


def main():
    try:
        poller = PwSashikoPoller()
        poller.run()
        return 0
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
