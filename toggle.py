#!/usr/bin/env python3
"""Turn the capture proxy config on/off in a directory's .claude/settings.local.json.

on.sh / off.sh call this. It only touches the keys it added; your own config is left alone.
State is recorded in ~/code/claude-tap/.patched.json, so `off` can restore precisely and no
patched directory is forgotten.
"""
import json, os, sys, pathlib

HERE = pathlib.Path(__file__).parent
STATE = HERE / ".patched.json"
PORT = os.environ.get("TAP_PORT", "8080")
KEYS = {
    "HTTPS_PROXY": f"http://127.0.0.1:{PORT}",
    "HTTP_PROXY": f"http://127.0.0.1:{PORT}",
    "NODE_EXTRA_CA_CERTS": str(pathlib.Path.home() / ".mitmproxy/mitmproxy-ca-cert.pem"),
}

load = lambda p, d: json.loads(p.read_text()) if p.exists() and p.read_text().strip() else d
save = lambda p, o: p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n")


def main():
    action = sys.argv[1]
    state = load(STATE, {})

    if action == "list":
        if not state:
            print("no directory currently has the capture config enabled")
        for d, info in state.items():
            print(f"  {d}  ({'pre-existing file, keys added' if info['existed'] else 'file created by on.sh'})")
        return

    arg = sys.argv[2]
    if arg in ("--global", "-g", "global", "GLOBAL"):   # GLOBAL is how `list` prints it; off --all reuses that
        target = pathlib.Path("GLOBAL")
        f = pathlib.Path.home() / ".claude" / "settings.json"   # applies to every Claude Code session
    else:
        target = pathlib.Path(arg).expanduser().resolve()
        if not target.is_dir():
            sys.exit(f"no such directory: {target}")
        f = target / ".claude" / "settings.local.json"

    if action == "on":
        existed = f.exists()
        cfg = load(f, {})
        env = cfg.setdefault("env", {})
        clash = {k: env[k] for k in KEYS if k in env and env[k] != KEYS[k]}
        if clash:
            sys.exit(f"!!  {f} already has different values for these keys, not overwriting: {clash}\n"
                     f"    Resolve them by hand first.")
        env.update(KEYS)
        f.parent.mkdir(parents=True, exist_ok=True)
        save(f, cfg)
        state[str(target)] = {"file": str(f), "existed": existed, "keys": list(KEYS)}
        save(STATE, state)
        print(f"enabled: {target}")
        print(f"   wrote {f}")
        scope = "every Claude Code session" if str(target) == "GLOBAL" else "any Claude Code window opened in this directory"
        print(f"   scope: {scope}")
        how = "--global" if str(target) == "GLOBAL" else target
        print(f"   !! while the proxy is down, claude cannot connect at all -- disable with: off.sh {how}")

    elif action == "off":
        info = state.pop(str(target), None)
        if not f.exists():
            save(STATE, state)
            sys.exit(f"{f} does not exist, nothing to disable")
        cfg = load(f, {})
        env = cfg.get("env", {})
        for k in (info or {}).get("keys", list(KEYS)):
            if env.get(k) == KEYS[k]:
                env.pop(k)
        if not env:
            cfg.pop("env", None)
        if not cfg and info and not info["existed"]:
            f.unlink()
            print(f"disabled: {target}\n   removed {f} (it was created by on.sh)")
        else:
            save(f, cfg)
            print(f"disabled: {target}\n   removed the proxy keys from {f}, rest of the config kept")
        save(STATE, state)


main()
