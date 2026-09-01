#!/usr/bin/env bash
# Stop the background mitmdump started by start.sh.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
PID="$D/.proxy.pid"; PORT="${TAP_PORT:-8080}"

if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
  kill "$(cat "$PID")" && echo "Stop signal sent, pid=$(cat "$PID")"
  rm -f "$PID"
else
  echo "No running proxy recorded in $PID"
  rm -f "$PID"
fi
sleep 1
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is still listening:"; lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
else
  echo "Proxy stopped, port $PORT released"
fi
n=$(find "$D/captures" -name '[0-9]*[0-9].json' 2>/dev/null | wc -l | tr -d ' ')
s=$(find "$D/captures" -maxdepth 1 -type d ! -name captures ! -name by-title 2>/dev/null | wc -l | tr -d ' ')
echo "   captured so far: $n requests across $s session directories"
