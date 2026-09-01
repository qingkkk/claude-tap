#!/usr/bin/env bash
# Undo everything: put the machine back the way it was before claude-tap.
#
#   restore.sh                surgical restore (recommended): remove injected keys, stop services
#   restore.sh --from-backup  additionally overwrite the global config from settings.json.bak
#   restore.sh --purge        additionally delete every capture under captures/
#
# Captures are kept by default -- deleting data requires an explicit --purge.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.claudetap.proxy"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${TAP_PORT:-8080}"
FROM_BACKUP=0; PURGE=0
for a in "$@"; do
  case "$a" in
    --from-backup) FROM_BACKUP=1 ;;
    --purge)       PURGE=1 ;;
    *) echo "unknown arg: $a"; exit 1 ;;
  esac
done
echo "=== claude-tap restore ==="

# 1. Disable every patched location (global + per-project), removing only our own keys
echo "[1/5] removing injected proxy config"
"$D/off.sh" --all 2>/dev/null | sed 's/^/      /'
if [ -f "$D/.patched.json" ] && grep -q '[^{}[:space:]]' "$D/.patched.json" 2>/dev/null; then
  echo "      !! leftovers remain, see $D/.patched.json"
else
  echo "      all removed"
fi

# 2. Optional: restore the whole global config from the backup
if [ "$FROM_BACKUP" = 1 ]; then
  if [ -f "$D/settings.json.bak" ]; then
    cp "$HOME/.claude/settings.json" "$D/settings.json.before-restore" 2>/dev/null
    cp "$D/settings.json.bak" "$HOME/.claude/settings.json"
    echo "[2/5] overwrote ~/.claude/settings.json from the backup"
    echo "      the version it replaced is saved at $D/settings.json.before-restore"
  else
    echo "[2/5] no settings.json.bak, skipping"
  fi
else
  echo "[2/5] skipping the full overwrite (pass --from-backup if you want it)"
fi

# 3. Unload the launchd service
echo "[3/5] unloading the launchd service"
if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && echo "      booted out $LABEL"
else
  echo "      service not loaded"
fi
if [ -f "$PLIST" ]; then rm -f "$PLIST" && echo "      deleted $PLIST"; else echo "      no plist"; fi

# 4. Stop the manually started proxy, confirm the port is free
echo "[4/5] stopping the proxy"
"$D/stop.sh" 2>/dev/null | sed 's/^/      /'
pkill -f "mitmdump.*claude-tap/tap.py" 2>/dev/null && echo "      cleaned up a stray process"
sleep 1
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "      !! port $PORT still in use:"; lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | sed 's/^/      /'
else
  echo "      port $PORT released"
fi

# 5. Capture data
n=$(find "$D/captures" -name '[0-9]*[0-9].json' 2>/dev/null | wc -l | tr -d ' ')
if [ "$PURGE" = 1 ]; then
  rm -rf "$D/captures"; echo "[5/5] deleted all captures ($n requests)"
else
  echo "[5/5] kept $n captured requests (pass --purge to delete, or rm -rf $D/captures)"
fi

echo
echo "Restore complete. Sanity check: open a new Claude Code window and have a conversation."
echo "The CA certificate was never installed into the system keychain, so there is nothing to clean up there."
