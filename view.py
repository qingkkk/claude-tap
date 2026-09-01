#!/usr/bin/env python3
"""claude-tap viewer: pick a session -> pick a request -> request/response side by side.

Start:  ~/code/claude-tap/view.py            # defaults to http://127.0.0.1:8899
        ~/code/claude-tap/view.py 9001       # different port
Read-only, binds 127.0.0.1 only. Data is scanned from captures/ on every request, so refreshing
the page while capturing shows whatever just landed.
"""
import json, os, re, sys, pathlib, http.server, socketserver, urllib.parse, webbrowser

HERE = pathlib.Path(__file__).parent
BASE = pathlib.Path(os.environ.get("TAP_DIR", str(HERE / "captures")))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("TAP_VIEW_PORT", 8899))


# A session directory holds several kinds of request. Subagents are identified by
# cc_is_subagent=true in the billing header (authoritative — Claude Code sets it itself);
# the rest are matched on system-prompt needles. Order matters: the title-generating request's
# system[1] is ALSO "You are Claude Code...", so the special cases must match first.
# A main agent has two identity strings: one for the interactive CLI, one for SDK/print mode
# (claude -p). Both are "main" — they differ only in cc_entrypoint (cli / sdk-cli), which is shown
# as a badge rather than a separate tag.
# classify() returns the kind only; display text is translated in the frontend (viewer.html I18N).
KINDS = [
    ("title", "You are naming a coding session"),
    ("guard", "You are a security monitor for autonomous AI coding agents"),
    ("main",  "You are Claude Code, Anthropic's official CLI"),
    ("main",  "You are a Claude agent, built on"),
]


def classify(b):
    """Return (kind, note, entrypoint, prompt_id). note is for subagents: their specialty line."""
    sysb = b.get("system") or []
    if isinstance(sysb, str):
        sysb = [{"text": sysb}]
    blob = "\n".join((x.get("text") or "") if isinstance(x, dict) else str(x) for x in sysb)
    head = sysb[0].get("text", "") if sysb and isinstance(sysb[0], dict) else ""
    ep = re.search(r"cc_entrypoint=([^;\s]+)", head)
    ep = ep.group(1) if ep else ""
    pid = re.search(r"cc_prompt_id=([^;\s]+)", head)
    pid = pid.group(1) if pid else ""

    if "cc_is_subagent=true" in head:              # an agent the main loop dispatched
        # the last system block is usually this agent's specialty; use it as the note
        spec = next((x.get("text","").strip() for x in reversed(sysb)
                     if (x.get("text") or "").strip().startswith("You are ")), "")
        return "sub", (spec.splitlines() or [""])[0][:90], ep, pid

    for kind, needle in KINDS:
        if needle in blob:
            return kind, "", ep, pid
    if not sysb and (b.get("max_tokens") or 0) <= 1:
        return "quota", "", ep, pid
    return "other", "", ep, pid


def sessions():
    if not BASE.exists():
        return []
    out = []
    for d in BASE.iterdir():
        if not d.is_dir() or d.name == "by-title" or d.is_symlink():
            continue
        reqs = sorted(d.glob("[0-9]*[0-9].json"))
        if not reqs:
            continue
        title = (d / "_title.txt").read_text().strip() if (d / "_title.txt").exists() else ""
        kinds = {}
        for f in reqs:
            try:
                k = classify(json.loads(f.read_text(errors="replace"))["body"])[0]
            except Exception:
                k = "other"
            kinds[k] = kinds.get(k, 0) + 1
        out.append({"id": d.name, "title": title, "count": len(reqs), "kinds": kinds,
                    "mtime": max(f.stat().st_mtime for f in reqs)})
    return sorted(out, key=lambda s: s["mtime"], reverse=True)


def _index_rows(d):
    """Index _index.jsonl by filename, so it lines up with the request files on disk."""
    rows = {}
    p = d / "_index.jsonl"
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
                rows[r.get("file")] = r
            except Exception:
                pass
    return rows


def _prev_req(b):
    """The request's own cc_prev_req: id of the previous request in the same agent loop."""
    s = b.get("system") or []
    head = s[0].get("text", "") if s and isinstance(s[0], dict) else ""
    m = re.search(r"cc_prev_req=([^;\s]+)", head)
    return m.group(1) if m else ""


def _request_id(d, stem):
    """A request's own id only shows up in the response's request-id header."""
    rp = d / f"{stem}.resp.json"
    if not rp.exists():
        return ""
    try:
        h = json.loads(rp.read_text(errors="replace")).get("headers") or {}
        return next((v for k, v in h.items() if k.lower() == "request-id"), "")
    except Exception:
        return ""


def _group(items):
    """Group by cc_prompt_id (one user message = one turn), then use cc_prev_req to link each
    agent loop into a chain. Main-agent chain is depth=0, subagent chains depth=1 (indented).
    Side-channel requests (title/security/quota) have no prompt_id, so they are attached to the
    turn they fired in rather than piled up separately, which would lose their context."""
    by_rid = {i["request_id"]: i for i in items if i.get("request_id")}
    for i in items:
        prev = by_rid.get(i.get("prev_req") or "")
        i["prev_stem"] = prev["stem"] if prev else ""
        i["depth"] = 1 if i["kind"] == "sub" else 0

    groups, cur, turn = [], None, 0
    for i in items:                                # items are already sorted by filename = arrival
        pid = i.get("prompt_id") or ""
        if pid and (cur is None or cur["prompt_id"] != pid):
            turn += 1
            cur = {"prompt_id": pid, "turn": turn, "stems": []}
            groups.append(cur)
        elif cur is None:                           # side request before any turn started
            cur = {"prompt_id": "", "turn": None, "stems": []}
            groups.append(cur)
        cur["stems"].append(i["stem"])
    return groups


def session_detail(sid):
    d = BASE / sid
    if not d.is_dir():
        return {"error": "no such session"}
    rows, items = _index_rows(d), []
    for f in sorted(d.glob("[0-9]*[0-9].json")):
        stem = f.stem
        r = rows.get(f.name, {})
        try:
            body = json.loads(f.read_text(errors="replace"))["body"]
            kind, note, ep, pid = classify(body)
        except Exception:
            body, (kind, note, ep, pid) = {}, ("other", "", "", "")
        it = {"stem": stem, "kind": kind, "note": note,
              "entrypoint": ep, "prompt_id": pid,
              "request_id": _request_id(d, stem), "prev_req": _prev_req(body),
              "at": r.get("at", ""), "model": r.get("model"),
              "total_tok": r.get("total_tok"), "messages": r.get("messages"),
              "tools": r.get("tools"), "cache_breakpoints": r.get("cache_breakpoints"),
              "has_resp": False}
        rp = d / f"{stem}.resp.json"
        if rp.exists():
            try:
                resp = json.loads(rp.read_text(errors="replace"))
                u = resp.get("usage") or {}
                it.update(has_resp=True, status=resp.get("status"),
                          stop_reason=resp.get("stop_reason"),
                          in_tok=u.get("input_tokens"), out_tok=u.get("output_tokens"),
                          cache_read=u.get("cache_read_input_tokens"),
                          cache_write=u.get("cache_creation_input_tokens"),
                          elapsed_ms=resp.get("elapsed_ms"), ttfb_ms=resp.get("ttfb_ms"),
                          err=bool(resp.get("errors") or resp.get("transport_error")),
                          kinds=[b.get("type") for b in resp.get("blocks") or []],
                          tool_names=[b.get("name") for b in resp.get("blocks") or []
                                      if b.get("type") == "tool_use"])
            except Exception as e:
                it.update(has_resp=True, status=None, err=True, parse_error=str(e))
        items.append(it)
    title = (d / "_title.txt").read_text().strip() if (d / "_title.txt").exists() else ""
    return {"id": sid, "title": title, "items": items, "groups": _group(items)}


def pair(sid, stem):
    d = BASE / sid
    if not d.is_dir() or "/" in stem or ".." in stem:
        return {"error": "bad path"}
    req = d / f"{stem}.json"
    if not req.exists():
        return {"error": "no such request"}
    out = {"request": json.loads(req.read_text(errors="replace")), "response": None}
    rp = d / f"{stem}.resp.json"
    if rp.exists():
        try:
            out["response"] = json.loads(rp.read_text(errors="replace"))
        except Exception as e:
            out["response"] = {"parse_error": str(e)}
    k = classify(out["request"].get("body") or {})
    out["kind"], out["note"], out["entrypoint"], out["prompt_id"] = k
    out["raw_sse"] = (d / f"{stem}.sse.txt").exists()
    return out


class H(http.server.SimpleHTTPRequestHandler):
    def _send(self, obj, ctype="application/json; charset=utf-8"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        one = lambda k: (q.get(k) or [""])[0]
        try:
            if u.path in ("/", "/index.html"):
                return self._send((HERE / "viewer.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/sessions":
                return self._send(sessions())
            if u.path == "/api/session":
                return self._send(session_detail(one("sid")))
            if u.path == "/api/pair":
                return self._send(pair(one("sid"), one("stem")))
            if u.path == "/api/sse":                       # raw SSE (only with TAP_RAW_SSE=1)
                p = BASE / one("sid") / f"{one('stem')}.sse.txt"
                miss = b"(no raw SSE stored; restart the proxy with TAP_RAW_SSE=1)"
                return self._send(p.read_bytes() if p.exists() else miss,
                                  "text/plain; charset=utf-8")
        except Exception as e:
            return self._send({"error": repr(e)})
        self.send_error(404)

    def log_message(self, *a):
        pass


class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = daemon_threads = True


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/"
    print(f"claude-tap viewer: {url}   (captures in {BASE}, Ctrl-C to quit)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    S(("127.0.0.1", PORT), H).serve_forever()
