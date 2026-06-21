#!/bin/bash
npx -y @modelcontextprotocol/server-filesystem /tmp > /dev/null 2>&1 &
# Wait for node process to spawn
sleep 5
# Find the node process running the mcp server
NODE_PID=$(pgrep -f "server-filesystem" | head -n 1)
if [ -z "$NODE_PID" ]; then
    echo "Could not find node process"
else
    echo "Node PID: $NODE_PID"
    cat /proc/$NODE_PID/status | grep VmRSS
    kill -9 $(pgrep -f "server-filesystem")
fi
