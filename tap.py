"""mitmproxy addon: capture Anthropic /v1/messages requests AND responses, grouped by session.

Start:  ~/code/claude-tap/start.sh      Stop: ~/code/claude-tap/stop.sh
View:   ~/code/claude-tap/view.py       request/response side by side in a browser
Output: captures/<session-id>/NNN-HHMMSS.json       the request
        captures/<session-id>/NNN-HHMMSS.resp.json  the response (SSE reassembled into one message)
        captures/<session-id>/NNN-HHMMSS.sse.txt    raw SSE event stream, needs TAP_RAW_SSE=1
        captures/by-title/<ai-title>--<id8>  ->  symlink to the directory above

Responses go through a stream callback: chunks are forwarded as they arrive, nothing is buffered,
so the typewriter effect in the terminal is unaffected.
A request and its response share the same NNN-HHMMSS filename prefix.
Auth headers are redacted by default. To keep real tokens: TAP_KEEP_AUTH=1
"""
import gzip, json, os, re, time, pathlib, urllib.parse, zlib

BASE = pathlib.Path(os.environ.get("TAP_DIR", str(pathlib.Path(__file__).parent / "captures")))
BYTITLE = BASE / "by-title"
PROJECTS = pathlib.Path.home() / ".claude" / "projects"
PATH_HINT = "/v1/messages"
KEEP_AUTH = os.environ.get("TAP_KEEP_AUTH") == "1"
RAW_SSE = os.environ.get("TAP_RAW_SSE") == "1"
SECRET_HEADERS = ("authorization", "cookie", "x-api-key", "proxy-authorization")
TAIL = 400_000          # only read this many trailing bytes of a transcript when hunting the title


def _hosts():
    """Which hosts to capture. TAP_HOSTS (comma separated) wins; otherwise the official domain
    plus any third-party gateway we can find. A gateway may be configured in the environment or
    in ~/.claude/settings.json's env block, so check both."""
    if os.environ.get("TAP_HOSTS"):
        return tuple(h.strip() for h in os.environ["TAP_HOSTS"].split(",") if h.strip())
    hosts, urls = {"api.anthropic.com"}, []
    for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_URL"):
        if os.environ.get(var):
            urls.append(os.environ[var])
    try:
        cfg = json.loads((pathlib.Path.home() / ".claude" / "settings.json").read_text())
        for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_URL"):
            if (cfg.get("env") or {}).get(var):
                urls.append(cfg["env"][var])
    except Exception:
        pass
    for u in urls:
        h = urllib.parse.urlparse(u if "//" in u else "//" + u).hostname
        if h:
            hosts.add(h)
    return tuple(sorted(hosts))


HOSTS = _hosts()

PENDING = {}            # flow.id -> request-phase context, picked up when the response arrives


def load(loader):
    """Print one line when mitmproxy loads the addon, so it is clear what is being captured.
    In a hook rather than at module level, so doctor.sh importing tap.py to probe HOSTS is quiet."""
    print(f"[tap] capturing {', '.join(HOSTS)}{PATH_HINT}  ->  {BASE}"
          + ("  (raw SSE on)" if RAW_SSE else ""))


def _tok(o):
    """Rough token estimate: characters / 3.6"""
    return int(len(json.dumps(o, ensure_ascii=False)) / 3.6)


def _clean(headers):
    return {k: (f"{v[:10]}…[REDACTED by tap.py]"
                if not KEEP_AUTH and k.lower() in SECRET_HEADERS else v)
            for k, v in headers.items()}


def _ai_title(sid):
    """Take the last ai-title from the tail of ~/.claude/projects/*/<sid>.jsonl. None if absent."""
    for p in PROJECTS.glob(f"*/{sid}.jsonl"):
        try:
            with open(p, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - TAIL))
                tail = fh.read().decode("utf-8", "ignore")
            t = None
            for line in tail.splitlines():
                if '"ai-title"' in line:
                    try:
                        t = json.loads(line).get("aiTitle") or t
                    except Exception:
                        pass
            return t
        except Exception:
            return None
    return None


def _slug(s):
    s = re.sub(r"[/\\\x00-\x1f]", "-", s).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return s[:60] or "untitled"


def _link(sid, d):
    """Maintain the by-title/<title>--<id8> symlink; if the title changed, drop the old one."""
    title = _ai_title(sid)
    if not title:
        return None
    BYTITLE.mkdir(parents=True, exist_ok=True)
    want = BYTITLE / f"{_slug(title)}--{sid[:8]}"
    for old in BYTITLE.glob(f"*--{sid[:8]}"):
        if old != want and old.is_symlink():
            old.unlink()
    if not want.exists():
        want.symlink_to(pathlib.Path("..") / sid)
    (d / "_title.txt").write_text(title + "\n")
    return title


# ---------------------------------------------------------------- request

def request(flow):
    if flow.request.host not in HOSTS or PATH_HINT not in flow.request.path:
        return
    try:
        body = json.loads(flow.request.get_content() or b"{}")
    except Exception as e:
        print(f"[tap] cannot parse {flow.request.pretty_url}: {e}")
        return

    sid = flow.request.headers.get("X-Claude-Code-Session-Id", "no-session")
    d = BASE / sid
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("[0-9]*[0-9].json"))) + 1     # increments within a session, survives restarts
    stem = f"{n:03d}-{time.strftime('%H%M%S')}"
    f = d / f"{stem}.json"

    sys_, msgs, tools = body.get("system") or [], body.get("messages") or [], body.get("tools") or []
    marks = json.dumps(body, ensure_ascii=False).count('"cache_control"')

    f.write_text(json.dumps({
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": sid,
        "url": flow.request.pretty_url,
        "headers": _clean(flow.request.headers),
        "body": body,
    }, ensure_ascii=False, indent=2))

    try:
        title = _link(sid, d)                          # a failed title lookup must never break capture
    except Exception as e:
        title = None
        print(f"[tap] title lookup failed for {sid[:8]}: {e}")

    with open(d / "_index.jsonl", "a") as fh:
        fh.write(json.dumps({
            "file": f.name, "at": time.strftime("%H:%M:%S"), "title": title,
            "model": body.get("model"),
            "system_blocks": len(sys_), "system_tok": _tok(sys_),
            "tools": len(tools), "tools_tok": _tok(tools),
            "messages": len(msgs), "messages_tok": _tok(msgs),
            "cache_breakpoints": marks, "total_tok": _tok(body),
        }, ensure_ascii=False) + "\n")

    PENDING[flow.id] = {"dir": d, "stem": stem, "sid": sid, "n": n,
                        "t0": time.time(), "t_first": None,
                        "chunks": bytearray(), "streamed": bool(body.get("stream"))}

    print(f"[tap] -> {sid[:8]} #{n} [{title or 'title pending'}] {body.get('model')} "
          f"system={len(sys_)}blk/{_tok(sys_)}tok tools={len(tools)}/{_tok(tools)}tok "
          f"messages={len(msgs)}/{_tok(msgs)}tok total~{_tok(body)}tok breakpoints={marks}")


# ---------------------------------------------------------------- response

def responseheaders(flow):
    """Attach a stream callback: forward every chunk untouched, keep a copy in memory."""
    ctx = PENDING.get(flow.id)
    if ctx is None:
        return
    ctx["status"] = flow.response.status_code
    ctx["resp_headers"] = _clean(flow.response.headers)
    ctx["encoding"] = (flow.response.headers.get("content-encoding") or "").lower()
    ctx["ctype"] = flow.response.headers.get("content-type") or ""
    ctx["t_headers"] = time.time()

    def sink(chunk: bytes) -> bytes:
        if chunk:
            if ctx["t_first"] is None:
                ctx["t_first"] = time.time()
            ctx["chunks"] += chunk
        return chunk

    flow.response.stream = sink


def response(flow):
    _finalize(flow.id, None)


def error(flow):
    _finalize(flow.id, str(flow.error) if getattr(flow, "error", None) else "connection error")


def _decompress(raw, enc):
    """mitmproxy does not decompress while streaming, so do it here. Return raw if it fails."""
    if not raw or not enc or enc == "identity":
        return raw
    try:
        if enc == "gzip":
            return gzip.decompress(raw)
        if enc == "deflate":
            return zlib.decompress(raw, -zlib.MAX_WBITS)
        if enc == "br":
            import brotli
            return brotli.decompress(raw)
        if enc == "zstd":
            import zstandard
            return zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    except Exception as e:
        print(f"[tap] {enc} decompression failed, storing raw bytes: {e}")
    return raw


def _parse_sse(text):
    """Reassemble an SSE event stream into one message: blocks / usage / stop_reason."""
    out = {"blocks": [], "usage": {}, "events": 0, "errors": []}
    blocks = {}
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except Exception:
            continue
        out["events"] += 1
        t = ev.get("type")
        if t == "message_start":
            m = ev.get("message") or {}
            out["id"], out["model"], out["role"] = m.get("id"), m.get("model"), m.get("role")
            out["usage"].update(m.get("usage") or {})
        elif t == "content_block_start":
            b = dict(ev.get("content_block") or {})
            if b.get("type") == "tool_use":
                b["_json"] = ""
            blocks[ev.get("index")] = b
        elif t == "content_block_delta":
            dl = ev.get("delta") or {}
            dt = dl.get("type") or ""
            b = blocks.setdefault(ev.get("index"), {"type": dt.replace("_delta", "") or "?"})
            if dt == "text_delta":
                b["text"] = b.get("text", "") + dl.get("text", "")
            elif dt == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + dl.get("thinking", "")
            elif dt == "signature_delta":
                b["signature"] = (b.get("signature") or "") + dl.get("signature", "")
            elif dt == "input_json_delta":
                b["_json"] = b.get("_json", "") + dl.get("partial_json", "")
            elif dt == "citations_delta":
                b.setdefault("citations", []).append(dl.get("citation"))
        elif t == "message_delta":
            d_ = ev.get("delta") or {}
            out["stop_reason"] = d_.get("stop_reason")
            out["stop_sequence"] = d_.get("stop_sequence")
            out["usage"].update(ev.get("usage") or {})
        elif t == "error":
            out["errors"].append(ev.get("error") or ev)
    for i in sorted(blocks, key=lambda x: (x is None, x)):
        b = blocks[i]
        if "_json" in b:                               # tool_use input arrives as JSON fragments
            s = b.pop("_json")
            if s.strip():
                try:
                    b["input"] = json.loads(s)
                except Exception:
                    b["input_partial"] = s             # keep the half JSON if the stream was cut
        out["blocks"].append(b)
    return out


def _parse_json_body(text):
    """Non-streaming response (e.g. the small haiku call that generates the session title)."""
    try:
        m = json.loads(text)
    except Exception:
        return {"blocks": [], "usage": {}, "events": 0, "errors": [], "unparsed": text[:4000]}
    if isinstance(m, dict) and m.get("type") == "error":
        return {"blocks": [], "usage": {}, "events": 0, "errors": [m.get("error") or m]}
    return {"id": m.get("id"), "model": m.get("model"), "role": m.get("role"),
            "blocks": m.get("content") or [], "usage": m.get("usage") or {},
            "stop_reason": m.get("stop_reason"), "stop_sequence": m.get("stop_sequence"),
            "events": 0, "errors": []}


def _finalize(fid, err):
    ctx = PENDING.pop(fid, None)
    if ctx is None:
        return
    now = time.time()
    raw = _decompress(bytes(ctx["chunks"]), ctx.get("encoding", ""))
    text = raw.decode("utf-8", "replace")
    is_sse = "event-stream" in ctx.get("ctype", "")
    parsed = _parse_sse(text) if is_sse else _parse_json_body(text)

    u = parsed.get("usage") or {}
    out = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": ctx["sid"],
        "request_file": f"{ctx['stem']}.json",
        "status": ctx.get("status"),
        "transport_error": err,
        "content_type": ctx.get("ctype"),
        "sse": is_sse,
        "bytes": len(raw),
        "elapsed_ms": int((now - ctx["t0"]) * 1000),
        "ttfb_ms": int((ctx["t_first"] - ctx["t0"]) * 1000) if ctx["t_first"] else None,
        "headers": ctx.get("resp_headers", {}),
        **parsed,
    }
    (ctx["dir"] / f"{ctx['stem']}.resp.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    if RAW_SSE and raw:
        (ctx["dir"] / f"{ctx['stem']}.sse.txt").write_text(text)

    kinds = ",".join(b.get("type", "?") for b in parsed.get("blocks") or []) or "-"
    tools = [b.get("name") for b in parsed.get("blocks") or [] if b.get("type") == "tool_use"]
    bad = f" !!{err or parsed['errors'][0]}" if (err or parsed.get("errors")) else ""
    print(f"[tap] <- {ctx['sid'][:8]} #{ctx['n']} {ctx.get('status')} "
          f"in={u.get('input_tokens','?')} out={u.get('output_tokens','?')} "
          f"cache_read={u.get('cache_read_input_tokens',0)} write={u.get('cache_creation_input_tokens',0)} "
          f"stop={parsed.get('stop_reason')} {out['elapsed_ms']/1000:.1f}s "
          f"ttfb={(out['ttfb_ms'] or 0)/1000:.1f}s blocks={kinds}"
          + (f" tool={'/'.join(t for t in tools if t)}" if tools else "") + bad)
