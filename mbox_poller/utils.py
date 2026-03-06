# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import re
import shlex
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Tuple, List

logger = logging.getLogger(__name__)

def get_oauth2_token(pass_cmd: str, service_name: str) -> str:
    """
    Executes a command to retrieve an OAuth2 access token.
    Handles network errors and command failures.
    """
    logger.info(f"Retrieving OAuth2 token for {service_name} using: {pass_cmd}")
    try:
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
                logger.error(f"OAuth2 authentication for {service_name} failed due to network connectivity issues")
                raise ConnectionError(f"OAuth2 authentication failed due to network connectivity: {stderr_output}")
            else:
                logger.error(f"OAuth2 command for {service_name} failed with exit code {process.returncode}")
                logger.error(f"Command stdout: {stdout_output}")
                logger.error(f"Command stderr: {stderr_output}")
                raise subprocess.CalledProcessError(process.returncode, pass_cmd,
                                                    process.stdout, process.stderr)

        access_token = process.stdout.strip()
        if not access_token:
            raise ValueError(f"Command returned empty access token for {service_name}")

        return access_token

    except Exception as e:
        if not isinstance(e, (ConnectionError, subprocess.CalledProcessError, ValueError)):
            logger.error(f"Unexpected error retrieving OAuth2 token for {service_name}: {e}")
        raise

def sanitize_id(identifier: str) -> str:
    """Cleans a string (Message-ID, Subject) for use as a directory/file name component."""
    s = str(identifier or "")
    s = re.sub(r'^(re|fwd?):\s*', '', s, flags=re.IGNORECASE)
    s = s.strip('<>')
    s = re.sub(r'[\s/\|?*:"<>@]+', '_', s)
    s = re.sub(r'[^a-zA-Z0-9_.-]', '_', s)
    s = s[:150]
    return s.strip('_.-')

def get_assigned_worker(job_id: str, hash_size: int) -> int:
    """
    Determines the assigned worker index for a job_id.
    Uses MD5 for stable hashing across all workers.
    """
    if not job_id:
        raise ValueError("Cannot assign worker for empty job_id")

    hash_obj = hashlib.md5(job_id.encode('utf-8'))
    hash_int = int.from_bytes(hash_obj.digest()[:8], 'little')
    return hash_int % hash_size

def should_process_job(job_id: str, worker_index: int, hash_size: int) -> bool:
    """
    Determines if this worker should process a job based on its hash.
    """
    if not job_id:
        return False

    assigned_worker = get_assigned_worker(job_id, hash_size)
    is_owner = (assigned_worker == worker_index)

    logger.debug(f"Job '{job_id}' hash maps to worker {assigned_worker} ({'us' if is_owner else 'not us'})")

    return is_owner

def run_sync_command(command: List[str], cwd: Path) -> Tuple[bool, str, str]:
    """
    Executes a synchronous shell command, capturing output.
    Returns (bool_success, stdout_str, stderr_str).
    """
    cmd_str = ' '.join(command)
    logger.info(f"Running sync command: {cmd_str} in {cwd}")
    try:
        process = subprocess.run(command, cwd=cwd, capture_output=True,
                                 text=True, check=False)
        stdout = process.stdout.strip() if process.stdout else ""
        stderr = process.stderr.strip() if process.stderr else ""

        if process.returncode != 0:
            logger.error(f"Command failed (code {process.returncode}): {cmd_str}")
            logger.error(f"STDERR: {stderr}")
            return False, stdout, stderr

        logger.info(f"Sync command succeeded.")
        return True, stdout, stderr
    except FileNotFoundError:
        err_msg = f"Command not found: {command[0]}"
        logger.error(err_msg)
        return False, "", err_msg
    except Exception as e:
        err_msg = f"Exception running command {cmd_str}: {e}"
        logger.error(err_msg)
        return False, "", err_msg
