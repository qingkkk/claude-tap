# claude-tap

Capture what Claude Code actually sends to and receives from the Anthropic API, and read it
side by side in a local browser page.

[中文文档 →](README.zh-CN.md)

A [mitmproxy](https://mitmproxy.org) addon parks itself in front of `POST /v1/messages`, writes
every request **and** its streamed response to disk grouped by session, and a small read-only web
viewer pairs them up: request on the left, response on the right, one row per API call.

Responses are captured through a streaming callback — chunks are forwarded as they arrive, so the
typewriter effect in your terminal is unaffected.

## Quick start

```bash
./doctor.sh                       # check deps, generate the mitmproxy CA, check ports
./start.sh                        # start the proxy on 127.0.0.1:8080 (background)
./view.py                         # open the viewer at http://127.0.0.1:8899
source ./env.sh && claude         # THIS shell's claude goes through the proxy
```

`doctor.sh` is not optional the first time: mitmproxy's CA certificate does not exist until
mitmproxy has run once, and without it `claude` fails with a TLS error that says nothing about
certificates.

Only the shell you `source env.sh` in is affected. Nothing global changes.

To stop: `./stop.sh` (proxy), `Ctrl-C` or `kill $(cat .view.pid)` (viewer).

## What you get

```
captures/
  <session-id>/
    001-140846.json         request:  url, headers (secrets redacted), full body
    001-140846.resp.json    response: SSE reassembled into one message —
                            blocks (text/thinking/tool_use), usage, stop_reason,
                            status, elapsed_ms, ttfb_ms
    001-140846.sse.txt      raw SSE event stream (only with TAP_RAW_SSE=1)
    _index.jsonl            one line per request: token estimates, cache breakpoints
    _title.txt              the session's AI-generated title
  by-title/
    <title>--<id8> -> ../<session-id>    symlink, so you can find a session by name
```

Request and response share the same `NNN-HHMMSS` filename prefix. `NNN` is **arrival order, not
conversation turn** — see below.

## The viewer

`./view.py` serves three columns at `http://127.0.0.1:8899`:

| Column | Contents |
|---|---|
| Sessions | title, id, request count, composition (`main 42 · sub 2`) |
| Requests | grouped by turn, one row per API call: type tag, status, tokens, elapsed, tools called |
| Detail | meta bar, then **request on the left / response on the right** |

- Language selector top-right (**English by default**, 中文 available; remembered in `localStorage`)
- `j` / `k` move between requests
- Every `tool_use` in a response has a **see result →** button that jumps to the next request and
  highlights the matching `tool_result`
- `← prev in chain` follows `cc_prev_req` back through the same agent loop
- Auto-refreshes every 4s, so you can watch captures land live

### Request types

One session directory holds several kinds of API call, not just your conversation. The viewer tags
each one; side-channel calls are hidden by default.

| Tag | How it is identified | What it is |
|---|---|---|
| **main** | `You are Claude Code, Anthropic's official CLI` or `You are a Claude agent, built on` | the conversation itself (has tools, has `cc_prompt_id`) |
| **subagent** | billing header contains `cc_is_subagent=true` | an agent the main loop dispatched; indented, annotated with its specialty |
| title-gen | `You are naming a coding session` | small haiku call that produces `_title.txt` |
| security | `You are a security monitor for autonomous AI coding agents` | reviews each tool call, answers `<severity>N` |
| quota | no system prompt, `max_tokens<=1` | probe fired when a terminal opens |

Requests are grouped into **turns** by `cc_prompt_id` (one value per user message). Within a turn,
`cc_prev_req` links each agent loop into a chain — the main agent and each subagent keep separate
chains, which is why a subagent's "prev" points at the previous *subagent* request.

These markers come from Claude Code 2.1.252. A future CLI version may rename them, in which case
tags fall back to `?`.

## Scripts

| Script | Purpose |
|---|---|
| `doctor.sh` | preflight: deps, CA cert, ports, which hosts will be captured |
| `start.sh` / `stop.sh` | start / stop the mitmdump proxy in the background |
| `view.py` | the web viewer (read-only, binds `127.0.0.1` only) |
| `show.py` | same data in the terminal — `./show.py --list`, `./show.py <id-prefix> 003` |
| `watch.sh` | `tail -f` the proxy log, filtered to capture summaries |
| `clean.sh` | prune `captures/` — `--days N`, `--sse`, `--all`; dry run unless `--yes` |
| `env.sh` | `source` it to route only this shell's `claude` through the proxy |
| `on.sh` / `off.sh` | alternative: write the proxy env into a project's `.claude/settings.local.json` (or `--global`) |
| `restore.sh` | undo everything: remove injected config, unload the launchd service, stop the proxy |

`on.sh` persists configuration, so **`claude` in that directory will fail to connect whenever the
proxy is not running**. `off.sh` reverses it; `toggle.py list` shows what is currently patched.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `TAP_PORT` | `8080` | proxy port (`start.sh`, `env.sh`, `toggle.py` all read it) |
| `TAP_VIEW_PORT` | `8899` | viewer port |
| `TAP_DIR` | `./captures` | where captures go |
| `TAP_HOSTS` | — | comma-separated hosts to capture, overriding detection |
| `TAP_RAW_SSE` | off | also keep the raw `.sse.txt` event stream |
| `TAP_KEEP_AUTH` | off | **do not redact** `Authorization` / `Cookie` / `x-api-key` |

### Third-party gateways

By default `tap.py` captures `api.anthropic.com`, plus any host it finds in `ANTHROPIC_BASE_URL` /
`ANTHROPIC_API_URL` — checked both in the environment and in `~/.claude/settings.json`'s `env`
block. If your gateway is configured somewhere else, set `TAP_HOSTS=your.gateway.host`.
`doctor.sh` step 5 prints exactly which hosts are active, so you can confirm before wondering why
nothing is captured.

## Security

Captures contain your full conversations, your `CLAUDE.md`, and file contents the tools read.
Auth headers are redacted unless you set `TAP_KEEP_AUTH=1` — with that on, **real tokens land on
disk in plaintext**. `captures/`, `proxy.log`, and the pid files are gitignored. The viewer binds
`127.0.0.1` only; do not expose it.

## Limitations

- macOS-oriented: `launchctl` (optional service management), `lsof`, BSD `find` flags
- Request classification is tied to Claude Code 2.1.252's prompts and billing header
- Session titles come from `~/.claude/projects/*/<session-id>.jsonl`; if that layout changes, rows
  just show "(title pending)"
- `captures/` grows without bound — `clean.sh` is the answer, nothing runs automatically
