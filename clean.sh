#!/usr/bin/env bash
# Prune captures/. Nothing is deleted without --yes.
#
#   ./clean.sh                    dry run: show what would go (default: sessions older than 14d)
#   ./clean.sh --days 7 --yes     delete sessions untouched for 7+ days
#   ./clean.sh --sse --yes        delete only the raw .sse.txt files (biggest, least needed)
#   ./clean.sh --all --yes        delete every capture
#
# Written for bash 3.2 (macOS default) — no mapfile / no associative arrays.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
C="${TAP_DIR:-$D/captures}"
DAYS=14; MODE=days; YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --days) DAYS="$2"; MODE=days; shift 2 ;;
    --sse)  MODE=sse; shift ;;
    --all)  MODE=all; shift ;;
    --yes|-y) YES=1; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done
[ -d "$C" ] || { echo "no capture dir: $C"; exit 0; }
before=$(du -sh "$C" 2>/dev/null | cut -f1 | tr -d ' ')
LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT

case "$MODE" in
  sse)  find "$C" -name '*.sse.txt' 2>/dev/null > "$LIST" ;;
  all)  find "$C" -mindepth 1 -maxdepth 1 2>/dev/null > "$LIST" ;;
  days) find "$C" -mindepth 1 -maxdepth 1 -type d ! -name by-title -mtime +"$DAYS" 2>/dev/null > "$LIST" ;;
esac

n=$(grep -c . "$LIST" 2>/dev/null); [ -n "$n" ] || n=0     # grep -c prints 0 but exits 1 on no match
if [ "$n" = 0 ]; then echo "nothing to clean (total $before)"; exit 0; fi
echo "would delete $n item(s), current total $before:"
while IFS= read -r h; do
  [ -n "$h" ] && echo "    $(du -sh "$h" 2>/dev/null | cut -f1 | tr -d ' ')  ${h#$C/}"
done < "$LIST"

if [ "$YES" != 1 ]; then
  echo; echo "dry run — add --yes to actually delete."; exit 0
fi
while IFS= read -r h; do [ -n "$h" ] && rm -rf "$h"; done < "$LIST"
# drop by-title symlinks that now point at deleted directories
if [ -d "$C/by-title" ]; then
  find "$C/by-title" -type l 2>/dev/null | while IFS= read -r l; do
    [ -e "$l" ] || rm -f "$l"
  done
fi
echo "done. $before -> $(du -sh "$C" 2>/dev/null | cut -f1 | tr -d ' ')"
