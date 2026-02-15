# SPDX-License-Identifier: GPL-2.0
#
# Copyright (C) 2019 Netronome Systems, Inc.

"""The phy module

Collection of files and code which is specific to the linux-phy process.
"""

from .tree_match import series_tree_name_direct, \
    series_ignore_missing_tree_name, \
    series_tree_name_should_be_local, \
    series_is_a_fix_for, \
    series_needs_async

current_tree = 'phy-fixes'
next_tree = 'phy-next'
