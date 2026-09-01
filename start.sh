#!/usr/bin/env bash
# Start mitmdump in the background, bound to 127.0.0.1 only.
# Captures land in ./captures/<session-id>/ via tap.py.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
PID="$D/.proxy.pid"; LOG="$D/proxy.log"; PORT="${TAP_PORT:-8080}"

if launchctl print "gui/$UID/com.claudetap.proxy" >/dev/null 2>&1; then
  echo "The launchd service com.claudetap.proxy already manages this proxy; no need to start it by hand."
  echo "  restart:   launchctl kickstart -k gui/$UID/com.claudetap.proxy"
  echo "  uninstall: $D/restore.sh"; exit 1
fi
if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
  echo "Already running (pid $(cat "$PID")). To restart, run $D/stop.sh first."; exit 1
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is taken by another process:"; lsof -nP -iTCP:"$PORT" -sTCP:LISTEN; exit 1
fi
if ! command -v mitmdump >/dev/null; then
  echo "mitmdump not found. Run $D/doctor.sh for install instructions."; exit 1
fi

mkdir -p "$D/captures"
nohup mitmdump --listen-host 127.0.0.1 --listen-port "$PORT" -s "$D/tap.py" >>"$LOG" 2>&1 &
echo $! > "$PID"
sleep 2
if ! kill -0 "$(cat "$PID")" 2>/dev/null; then
  echo "Failed to start, see the log: $LOG"; tail -20 "$LOG"; rm -f "$PID"; exit 1
fi
echo "Proxy started in the background  pid=$(cat "$PID")  127.0.0.1:$PORT"
echo "   captures:  $D/captures/<session-id>/"
echo "   live log:  tail -f $LOG"
echo "   viewer:    $D/view.py            # request/response side by side, http://127.0.0.1:8899"
echo "   route claude through it (this shell only): source $D/env.sh && claude"
echo "   stop:      $D/stop.sh"
