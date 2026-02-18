#!/bin/bash
# Script to reprocess series by deleting results and sending to poller socket

# Configuration
RESULTS_DIR="/srv/docker/nipa-run/results"
SOCKET_PATH="/srv/docker/nipa-run/nipa-poller.sock"
TIMEOUT=130  # Wait up to 130 seconds (just over 2 minutes)

if [ $# -eq 0 ]; then
	echo "Usage: $0 <series_id> [series_id ...]"
	echo "Example: $0 1054248 1053821 1053498"
	exit 1
fi

if [ ! -S "$SOCKET_PATH" ]; then
	echo "Error: Socket $SOCKET_PATH does not exist or is not a socket"
	exit 1
fi

# Check if results directory exists
if [ ! -d "$RESULTS_DIR" ]; then
	echo "Warning: Results directory $RESULTS_DIR does not exist"
fi

# Delete result directories
echo "Deleting result directories..."
for series_id in "$@"; do
	result_path="$RESULTS_DIR/$series_id"
	if [ -d "$result_path" ]; then
		echo "  Deleting: $result_path"
		rm -rf "$result_path"
	else
		echo "  Not found: $result_path (skipping)"
	fi
done

# Construct semicolon-separated string
series_string=$(IFS=';'; echo "$*")
echo ""
echo "Sending series to poller: $series_string"
echo ""

# Send to socket and wait for response
echo "$series_string" | nc -U -w $TIMEOUT "$SOCKET_PATH"

if [ $? -eq 0 ]; then
	echo ""
	echo "Successfully sent request to poller"
else
	echo ""
	echo "Error: Failed to communicate with poller socket"
	exit 1
fi
