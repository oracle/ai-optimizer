#!/bin/bash
## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:ignore streamlit

OCI_DIR="/app/.oci"
CONFIG_FILE="${OCI_DIR}/config"

# Process the OCI config file to change the path of the key_file
KEY_FILE_PATH=$(grep '^key_file=' "$CONFIG_FILE" | cut -d'=' -f2)
KEY_FILE_NAME=$(basename "$KEY_FILE_PATH")
sed -i.bak "s|key_file=.*|key_file=${OCI_DIR}/${KEY_FILE_NAME}|g" "$CONFIG_FILE"

if [ -d /app/server ] && [ -d /app/client ]; then
    echo "Starting Application (Client and Server)"
    exec streamlit run ./launch_client.py
fi

if [ -d /app/server ] && [ ! -d /app/client ]; then
    echo "Starting Server"
    python ./launch_server.py
fi

if [ ! -d /app/server ] && [ -d /app/client ]; then
    echo "Starting Client"
    if [ -z "$API_SERVER_KEY" ] || [ -z "$API_SERVER_URL" ] || [ -z "$API_SERVER_PORT" ]; then
        echo "Error: Not all API_SERVER variables are set; unable to start the Client."
        exit 1
    fi
    exec streamlit run ./launch_client.py
fi