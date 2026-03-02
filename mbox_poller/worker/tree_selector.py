# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

import re
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class TreeSelector:
    """Handles tree selection based on patch prefixes from worker configuration."""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.tree_selection = {}
        self.load_config()

    def load_config(self):
        """Load and validate worker configuration file."""
        if not self.config_file.exists():
            logger.critical(f"Worker config file not found: {self.config_file}")
            raise FileNotFoundError(f"Worker config file not found: {self.config_file}")

        try:
            with self.config_file.open('r') as f:
                config_data = json.load(f)

            if 'tree_selection' not in config_data:
                logger.critical(f"Worker config missing 'tree_selection' section: {self.config_file}")
                raise ValueError("Worker config missing 'tree_selection' section")

            self.tree_selection = config_data['tree_selection']

            # Validate tree selection entries
            for prefix, config in self.tree_selection.items():
                if not isinstance(config, dict):
                    raise ValueError(f"Tree selection '{prefix}' must be a dictionary")
                if 'remote' not in config or 'branch' not in config:
                    raise ValueError(f"Tree selection '{prefix}' missing 'remote' or 'branch'")
                if not config['remote'] or not config['branch']:
                    raise ValueError(f"Tree selection '{prefix}' has empty 'remote' or 'branch'")

            logger.info(f"Loaded tree selection config with {len(self.tree_selection)} entries")
            if 'default' in self.tree_selection:
                logger.info("Default tree selection available")
            else:
                logger.warning("No default tree selection configured")

        except (json.JSONDecodeError, OSError) as e:
            logger.critical(f"Failed to load worker config {self.config_file}: {e}")
            raise

    def extract_patch_prefix(self, subject: str) -> str:
        """Extract the patch prefix from a subject line using tokenization and elimination."""
        if not subject:
            return ""

        bracket_match = re.search(r'^\[([^\]]+)\]', subject.strip())
        if not bracket_match:
            return ""

        bracket_content = bracket_match.group(1)

        tokens = bracket_content.split()

        filtered_tokens = []

        for token in tokens:
            if token in ['PATCH', 'RFC']:
                continue

            if re.match(r'^[vV]\d+$', token):
                continue

            if re.match(r'^\d+/\d+$', token):
                continue

            filtered_tokens.append(token)

        tree_name = ' '.join(filtered_tokens).strip()

        return tree_name

    def select_tree(self, series_subject: str) -> dict:
        """
        Select the appropriate tree configuration based on series subject.
        Returns dict with 'remote' and 'branch' keys.
        Raises ValueError if no match and no default.
        """
        if not series_subject:
            logger.warning("Empty series subject for tree selection")
            if 'default' in self.tree_selection:
                logger.info("Using default tree selection for empty subject")
                return self.tree_selection['default'].copy()
            raise ValueError("No series subject available and no default tree selection configured")

        prefix = self.extract_patch_prefix(series_subject)
        logger.debug(f"Extracted prefix '{prefix}' from subject: {series_subject}")

        # Try exact match first
        if prefix and prefix in self.tree_selection:
            logger.info(f"Selected tree for prefix '{prefix}': {self.tree_selection[prefix]}")
            return self.tree_selection[prefix].copy()

        # Fall back to default
        if 'default' in self.tree_selection:
            logger.info(f"No match for prefix '{prefix}', using default tree selection")
            return self.tree_selection['default'].copy()

        # No match and no default
        available_prefixes = list(self.tree_selection.keys())
        raise ValueError(f"No tree selection match for prefix '{prefix}' and no default configured. "
                        f"Available prefixes: {available_prefixes}")
