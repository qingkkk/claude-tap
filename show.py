#!/usr/bin/env python3
"""Inspect a request captured by tap.py, split into TOOLS / SYSTEM / MESSAGES.

Usage:
  ./show.py                  # newest request of the newest session
  ./show.py --list           # list every session and request
  ./show.py 8c29             # newest request of a session (id prefix or title keyword)
  ./show.py Proxy            # title match works too
  ./show.py 8c29 003         # the 3rd request of that session
  ./show.py --full           # do not truncate long text
  ./show.py --tools          # only list tool names
"""
import json, sys, os, pathlib

BASE = pathlib.Path(os.environ.get("TAP_DIR", str(pathlib.Path(__file__).parent / "captures")))
flags = {a for a in sys.argv[1:] if a.startswith("-")}
pos = [a for a in sys.argv[1:] if not a.startswith("-")]
full, only_tools = "--full" in flags, "--tools" in flags

if not BASE.exists() or not any(BASE.iterdir()):
    sys.exit(f"nothing captured yet: {BASE}")

sessions = sorted([d for d in BASE.iterdir() if d.is_dir() and d.name != "by-title" and not d.is_symlink()],
                  key=lambda d: d.stat().st_mtime)
title_of = lambda d: (d / "_title.txt").read_text().strip() if (d / "_title.txt").exists() else ""

if "--list" in flags:
    for d in sessions:
        rows = [json.loads(l) for l in open(d / "_index.jsonl")] if (d / "_index.jsonl").exists() else []
        print(f"\n=== [{title_of(d) or 'title pending'}]  {d.name}  ({len(rows)} requests)")
        for r in rows:
            rp = d / (r['file'][:-5] + ".resp.json")          # the response with the same prefix
            tail = ""
            if rp.exists():
                try:
                    v = json.loads(rp.read_text())
                    u = v.get("usage") or {}
                    tail = (f"  -> {v.get('status')} out={u.get('output_tokens')} "
                            f"cache_read={u.get('cache_read_input_tokens', 0)} "
                            f"stop={v.get('stop_reason')} {(v.get('elapsed_ms') or 0)/1000:.1f}s")
                except Exception:
                    tail = "  -> (response file unreadable)"
            print(f"  {r['file']}  {r['at']}  {r['model']}  "
                  f"sys={r['system_tok']} tools={r['tools_tok']} msg={r['messages_tok']} "
                  f"total~{r['total_tok']}tok  breakpoints={r['cache_breakpoints']}{tail}")
    sys.exit()

sess = next((d for d in reversed(sessions)
             if d.name.startswith(pos[0]) or pos[0].lower() in title_of(d).lower()), None) if pos else sessions[-1]
if sess is None:
    sys.exit(f"no session matching {pos[0]}, available: {[d.name[:8] for d in sessions]}")
files = sorted(sess.glob("[0-9]*[0-9].json"))     # excludes NNN-HHMMSS.resp.json
if not files:
    sys.exit(f"no request files under {sess.name}")
seq = pos[1] if len(pos) > 1 else None
path = next((f for f in files if f.name.startswith(seq)), None) if seq else files[-1]
if path is None:
    sys.exit(f"no request {seq}, available: {[f.name[:3] for f in files]}")

d = json.loads(path.read_text())
b = d["body"]
cut = (lambda s: s) if full else (lambda s: s if len(s) <= 2000 else s[:2000] + f"\n  …({len(s)-2000} more chars, use --full)")
text_of = lambda x: x if isinstance(x, str) else (x.get("text") or json.dumps(x, ensure_ascii=False)) if isinstance(x, dict) else json.dumps(x, ensure_ascii=False)

print(f"=== [{title_of(sess) or 'title pending'}]  session {d.get('session_id')}  {path.name}  {d.get('captured_at')}")
print(f"{d['url']}")
print(f"model={b.get('model')} max_tokens={b.get('max_tokens')} stream={b.get('stream')}")
print(f"beta: {d['headers'].get('anthropic-beta','-')}\n")

tools = b.get("tools") or []
print(f"=== TOOLS ({len(tools)})")
print("  " + ", ".join(t.get("name", "?") for t in tools) + "\n")
if only_tools:
    sys.exit()

sysblocks = b.get("system") or []
if isinstance(sysblocks, str):
    sysblocks = [{"text": sysblocks}]
print(f"=== SYSTEM ({len(sysblocks)} blocks)")
for i, s in enumerate(sysblocks):
    cc = " [cache_control]" if isinstance(s, dict) and s.get("cache_control") else ""
    print(f"--- system[{i}]{cc}")
    print("  " + cut(text_of(s)).replace("\n", "\n  ") + "\n")

msgs = b.get("messages") or []
print(f"=== MESSAGES ({len(msgs)})")
for i, m in enumerate(msgs):
    content = m.get("content")
    blocks = content if isinstance(content, list) else [content]
    kinds = [(x.get("type") if isinstance(x, dict) else "text") for x in blocks]
    cc = " [cache_control]" if '"cache_control"' in json.dumps(m) else ""
    print(f"--- [{i}] {m.get('role')} ({', '.join(kinds)}){cc}")
    for x in blocks:
        print("  " + cut(text_of(x)).replace("\n", "\n  "))
    print()
