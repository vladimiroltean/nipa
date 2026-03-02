# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import json
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger(__name__)

class WorkerAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for worker idle-check API."""

    def __init__(self, work_dir: Path, *args, **kwargs):
        self.work_dir = work_dir
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Handle GET requests for idle check."""
        if self.path == '/idle-check':
            try:
                is_idle = self._check_if_idle()
                response = {
                    "idle": is_idle,
                    "timestamp": time.time()
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))

            except Exception as e:
                logger.error(f"Error checking idle status: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _check_if_idle(self) -> bool:
        """Check if worker has any running jobs."""
        if not self.work_dir.exists():
            return True

        try:
            for job_dir in self.work_dir.iterdir():
                if job_dir.is_dir():
                    info_file = job_dir / "info.json"
                    if info_file.exists():
                        try:
                            with info_file.open('r') as f:
                                info = json.load(f)
                                if info.get('status') == 'running':
                                    logger.debug(f"Found running job: {job_dir.name}")
                                    return False
                        except (json.JSONDecodeError, OSError):
                            continue

            return True

        except Exception as e:
            logger.error(f"Error scanning work directory: {e}")
            return True

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


class WorkerAPIServer:
    """Simple HTTP server for worker API endpoints."""

    def __init__(self, work_dir: Path, port: int):
        self.work_dir = work_dir
        self.port = port
        self.server = None
        self.thread = None
        self.is_running = False

    def start(self):
        """Start the API server in a background thread."""
        try:
            # Create a custom handler class with work_dir bound
            handler_class = lambda *args, **kwargs: WorkerAPIHandler(self.work_dir, *args, **kwargs)

            self.server = HTTPServer(('0.0.0.0', self.port), handler_class)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.is_running = True
            logger.info(f"Worker API server started on port {self.port}")

        except Exception as e:
            logger.error(f"Failed to start worker API server: {e}")

    def stop(self):
        """Stop the API server."""
        if self.server and self.is_running:
            self.server.shutdown()
            if self.thread:
                self.thread.join(timeout=5)
            self.is_running = False
            logger.info("Worker API server stopped")
