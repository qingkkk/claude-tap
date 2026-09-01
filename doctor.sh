#!/usr/bin/env bash
# Preflight check. Run this FIRST, before start.sh.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
PORT="${TAP_PORT:-8080}"
VIEW_PORT="${TAP_VIEW_PORT:-8899}"
CA="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
fail=0
ok(){   printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad(){  printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); }
warn(){ printf '  \033[33m!\033[0m %s\n' "$1"; }

echo "=== claude-tap doctor ==="

echo "[1] python3"
if command -v python3 >/dev/null; then ok "$(python3 --version 2>&1)"; else bad "python3 not found"; fi

echo "[2] mitmproxy"
if command -v mitmdump >/dev/null; then
  ok "$(mitmdump --version 2>&1 | head -1)"
else
  bad "mitmdump not found. Install one of:"
  echo "        brew install mitmproxy        # macOS"
  echo "        pipx install mitmproxy        # any platform"
fi

echo "[3] mitmproxy CA certificate"
if [ -f "$CA" ]; then
  ok "$CA"
elif command -v mitmdump >/dev/null; then
  warn "not generated yet — generating (mitmproxy runs for 3s)..."
  mitmdump --listen-port 0 >/dev/null 2>&1 &
  gen=$!; sleep 3; kill "$gen" 2>/dev/null; wait "$gen" 2>/dev/null
  [ -f "$CA" ] && ok "generated: $CA" || bad "still missing. Run 'mitmdump' once by hand, then Ctrl-C."
else
  bad "cannot generate without mitmproxy"
fi

echo "[4] ports"
for p in "$PORT:proxy" "$VIEW_PORT:viewer"; do
  n="${p%%:*}"; what="${p##*:}"
  if lsof -nP -iTCP:"$n" -sTCP:LISTEN >/dev/null 2>&1; then
    who=$(lsof -nP -iTCP:"$n" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}')
    if [ "$what" = proxy ] && [ -f "$D/.proxy.pid" ] && kill -0 "$(cat "$D/.proxy.pid")" 2>/dev/null; then
      ok "$n ($what) — our own proxy is running"
    elif [ "$what" = viewer ] && [ -f "$D/.view.pid" ] && kill -0 "$(cat "$D/.view.pid")" 2>/dev/null; then
      ok "$n ($what) — our own viewer is running"
    else
      bad "$n ($what) taken by $who"
    fi
  else
    ok "$n ($what) free"
  fi
done

echo "[5] which hosts will be captured"
python3 - "$D" <<'PY'
import importlib.util, json, os, pathlib, sys
spec = importlib.util.spec_from_file_location("tap", pathlib.Path(sys.argv[1]) / "tap.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
    print(f"  \033[32m✓\033[0m {', '.join(m.HOSTS)}{m.PATH_HINT}")
except Exception as e:
    print(f"  \033[31m✗\033[0m cannot load tap.py: {e}")
    sys.exit(1)
gw = []
for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_URL"):
    if os.environ.get(var):
        gw.append(f"{var}={os.environ[var]} (env)")
try:
    cfg = json.loads((pathlib.Path.home() / ".claude" / "settings.json").read_text())
    for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_URL"):
        if (cfg.get("env") or {}).get(var):
            gw.append(f"{var}={cfg['env'][var]} (~/.claude/settings.json)")
except Exception:
    pass
for g in gw:
    print(f"  \033[33m!\033[0m gateway detected and included: {g}")
if not gw:
    print("     no third-party gateway configured — official endpoint only.")
    print("     If you use one, set TAP_HOSTS=your.gateway.host or export ANTHROPIC_BASE_URL.")
PY

echo "[6] running services"
if [ -f "$D/.proxy.pid" ] && kill -0 "$(cat "$D/.proxy.pid")" 2>/dev/null; then
  ok "proxy running (pid $(cat "$D/.proxy.pid"))"
else
  warn "proxy not running — start it with $D/start.sh"
fi
if [ -f "$D/.view.pid" ] && kill -0 "$(cat "$D/.view.pid")" 2>/dev/null; then
  ok "viewer running (pid $(cat "$D/.view.pid")) http://127.0.0.1:$VIEW_PORT/"
else
  warn "viewer not running — start it with $D/view.py"
fi

echo "[7] capture dir"
if [ -d "$D/captures" ]; then
  ok "$(du -sh "$D/captures" 2>/dev/null | cut -f1) in $(find "$D/captures" -maxdepth 1 -type d ! -name captures ! -name by-title 2>/dev/null | wc -l | tr -d ' ') sessions — prune with ./clean.sh"
else
  warn "captures/ not created yet (appears on first capture)"
fi

echo
if [ "$fail" = 0 ]; then
  echo "All good. Next:  $D/start.sh   then   source $D/env.sh && claude"
else
  echo "$fail problem(s) above — fix them first."; exit 1
fi
