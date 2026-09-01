#!/usr/bin/env bash
# Watch what is being captured, live -- only the [tap] summary lines, mitmproxy's own
# connection noise filtered out. Use it to confirm "is this window actually being captured".
D="$(cd "$(dirname "$0")" && pwd)"
echo "Watching $D/proxy.log (Ctrl-C to quit). Send a message in a captured window and a line appears here."
tail -f "$D/proxy.log" | grep --line-buffered '^\[tap\]'
