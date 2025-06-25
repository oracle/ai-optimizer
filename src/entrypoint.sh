#!/bin/bash
## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:ignore streamlit

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