# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

class GracefulShutdown(BaseException):
    """Custom exception to signal a graceful shutdown from SIGTERM/SIGHUP."""
    pass
