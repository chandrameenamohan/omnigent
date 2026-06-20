# pi-via-cli — answer Pi through the local `claude`/`codex` CLI

Run the Pi worker on a Claude Max / ChatGPT **subscription** without exporting
any API key — by routing Pi's model calls through the real vendor CLI, which
holds its own subscription OAuth login.

A ~150-line stdlib-only HTTP bridge (`bridge.py`) stands in as Pi's gateway
endpoint: it speaks the OpenAI `/v1/chat/completions` shape, but instead of
calling a vendor API it shells each request into `claude -p` or `codex exec`
and wraps the CLI's stdout back into a chat-completions reply.

## Why this is ToS-clean

The bridge **never sees or forwards a vendor token**. Each request is handed to
the vendor's own CLI as a normal local `claude`/`codex` invocation, and the CLI
authenticates itself against its own subscription login. No OAuth token, cookie,
or session is extracted or replayed across services — the only thing that
crosses the bridge is the prompt text in and the assistant text out. You are
using each CLI exactly as its vendor ships it.

## Run it

```bash
# 1. Make sure the CLI you want is installed and logged in:
claude -p "hello"      # or:  codex exec "hello"

# 2. Start the bridge (stdlib only, no install step):
CLI=claude python3 examples/pi-via-cli/bridge.py        # default port 8848
#   or  CLI=codex PORT=9000 python3 examples/pi-via-cli/bridge.py

# 3. Point Pi at it (merge config.yaml's providers block into
#    ~/.omnigent/config.yaml), then run a Pi-backed agent, e.g.:
omnigent run examples/polly
```

If you omit `CLI`, the bridge picks per request from the model name: a name
containing `gpt`/`codex` routes to `codex exec`, anything else to `claude -p`.

Sanity-check the request/response wrapping offline (no CLI needed):

```bash
python3 examples/pi-via-cli/bridge.py --self-check   # prints "self-check passed"
```

## The gateway config

`config.yaml` here is the `providers:` block to merge into
`~/.omnigent/config.yaml`. It declares one `kind: gateway` provider whose
`openai` family `base_url` is the bridge, marked `default: [pi]` so the Pi
worker uses it with no per-agent override. Pi's gateway provider then writes Pi
a `models.json` pointing at the bridge — no Omnigent runtime change is involved;
this is examples-only.

## Scope ceiling

This bridge is deliberately minimal. Know its limits before relying on it:

- **Text only, no tool_calls pass-through.** It forwards the CLI's final
  assistant *text*. It does not translate Pi's tool/function-call protocol
  through the CLI. So it's ideal for Pi as a **reviewer or explorer** (read,
  reason, answer), but it won't cleanly drive Pi's own tool-using agent loop.
- **No multi-turn context.** Each request is a fresh, stateless CLI run; prior
  turns are flattened into the prompt but no CLI session is carried across
  requests. The documented upgrade path is per-session reuse via
  `claude --resume` or a tmux-backed session — **not built here**.
- **Non-streaming.** Replies come back whole, not token-streamed.
- **Local only.** Binds `127.0.0.1`; there is no auth on the bridge itself
  (it relies on the CLI's auth). Don't expose the port.
