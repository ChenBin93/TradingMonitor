#!/bin/bash
# Kill all running OKX monitoring scanner processes

echo "=== OKX Monitor Cleanup ==="

# Find processes
PIDS=$(ps aux | grep -E "python.*src\.core\.main|python.*main\.py" | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "No scanner processes found."
else
    echo "Found PIDs: $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null
    echo "Killed."
fi

# Also kill any timeout wrappers
TPIDS=$(ps aux | grep "timeout.*src\.core" | grep -v grep | awk '{print $2}')
if [ -n "$TPIDS" ]; then
    echo "$TPIDS" | xargs kill -9 2>/dev/null
fi

echo "Done."
