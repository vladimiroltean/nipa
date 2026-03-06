#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright 2025-2026 NXP

set -e

# Check for environment variables ending in _FILE and export their contents as
# the variable without the _FILE suffix. This bridges Docker secrets into the
# Python application.

# Example: IMAP_SERVER_FILE=/run/secrets/imap_server
# becomes: export IMAP_SERVER=$(cat /run/secrets/imap_server)

file_env() {
	local var="$1"
	local file_var="${var}_FILE"
	local def="${2:-}"

	# Check if the _FILE variable is set
	if [ "${!file_var:-}" ]; then
		# If yes, read the value from the file
		val=$(< "${!file_var}")
	elif [ "${!var:-}" ]; then
		# Check if the normal variable is set
		val="${!var}"
	else
		# Otherwise, use the default
		val="$def"
	fi

	export "$var"="$val"
}

file_env 'IMAP_SERVER'
file_env 'IMAP_USER'
file_env 'IMAP_PASSWORD'
file_env 'IMAP_PASS_CMD'
file_env 'SMTP_SERVER'
file_env 'SMTP_PORT'
file_env 'SMTP_USER'
file_env 'SMTP_PASSWORD'
file_env 'SMTP_PASS_CMD'
file_env 'SMTP_FROM_ADDRESS'

exec "$@"
