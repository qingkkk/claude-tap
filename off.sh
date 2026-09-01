#!/usr/bin/env bash
# No args = disable the current directory; --global = disable globally; --all = disable everything.
D="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = "--all" ]; then
  python3 "$D/toggle.py" list | awk '{print $1}' | while read -r d; do
    [ -n "$d" ] && python3 "$D/toggle.py" off "$d"
  done
else
  exec python3 "$D/toggle.py" off "${1:-$PWD}"
fi
