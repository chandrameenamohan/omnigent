#!/usr/bin/env python3
"""bridge.py — answer Pi's gateway calls through the local claude/codex CLI.

Pi's gateway provider writes Pi a models.json aimed at a localhost
OpenAI-compatible /v1 endpoint (see config.yaml). This bridge IS that endpoint:
each POST /v1/chat/completions flattens the request's messages into a single
prompt, shells it into the real vendor CLI (`claude -p <prompt>` or
`codex exec <prompt>`), and wraps the CLI's stdout back into an OpenAI
chat-completions JSON reply.

ToS-clean: the CLI consumes its OWN subscription login — no token is replayed.

Scope ceiling: passes final assistant TEXT only (no tool_calls pass-through),
and multi-turn context is discarded per request — every call is a fresh,
stateless CLI invocation. See README.md.

  CLI=claude python3 bridge.py            # default port 8848
  CLI=codex  PORT=9000 python3 bridge.py
  python3 bridge.py --self-check          # offline self-check, no CLI needed

Stdlib only — no dependencies, no web framework.
"""

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# How to shell each CLI for a one-shot, stateless prompt.
CLI_ARGV = {
    "claude": lambda prompt: ["claude", "-p", prompt],
    "codex": lambda prompt: ["codex", "exec", prompt],
}


def pick_cli(model):
    """Pick the CLI: explicit CLI env wins, else infer from the model name."""
    env = os.environ.get("CLI")
    if env:
        return env
    name = (model or "").lower()
    return "codex" if ("gpt" in name or "codex" in name) else "claude"


def flatten(messages):
    """Flatten OpenAI `messages` into one prompt string.

    Content may be a string or a list of {type, text} parts (vision shape);
    both collapse to text — this bridge only moves text.
    """
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content") or ""  # None/falsy -> "", not the literal "None"
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def run_cli(cli, prompt):
    """Shell the prompt into the CLI, return its stdout. Patched out by demo()."""
    argv = CLI_ARGV[cli](prompt)
    out = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"{cli} exited {out.returncode}")
    return out.stdout.strip()


def chat_response(text, model):
    """Wrap CLI text in a (non-streaming) OpenAI chat-completions object."""
    return {
        "id": "chatcmpl-bridge",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        # ponytail: token counts not tracked; the CLI bills its own subscription.
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def handle_chat(req):
    """Core request->prompt->CLI->response wrapping (the self-checked path)."""
    model = req.get("model", "")
    cli = pick_cli(model)
    prompt = flatten(req.get("messages", []))
    text = run_cli(cli, prompt)
    return chat_response(text, model or cli)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/v1/models":
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": m, "object": "model", "owned_by": "cli-bridge"}
                        for m in CLI_ARGV
                    ],
                },
            )
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, handle_chat(req))
        except Exception as e:  # surface CLI/JSON failures as an OpenAI error
            self._json(500, {"error": {"message": str(e)}})

    def log_message(self, format, *args):
        pass  # quiet by default


def demo():
    """Self-check: request->prompt->response wrapping, with the CLI stubbed.

    Fails if the prompt flattening, CLI selection, or JSON shaping breaks.
    """
    global run_cli
    real = run_cli
    # Pop CLI up front so cli-selection asserts hold even when the operator has
    # it set; restore in finally. (Also exercises the model-name fallback.)
    old_cli = os.environ.pop("CLI", None)
    captured = {}

    def fake(cli, prompt):
        captured["cli"] = cli
        captured["prompt"] = prompt
        return "the answer is 42"

    run_cli = fake
    try:
        resp = handle_chat(
            {
                "model": "claude-sonnet",
                "messages": [
                    {"role": "system", "content": "be terse"},
                    {"role": "user", "content": "what is 6*7?"},
                    # list-style content (vision shape) must flatten to text too
                    {"role": "user", "content": [{"type": "text", "text": "show work"}]},
                ],
            }
        )

        # The EXACT flattened prompt — full equality catches reordered turns
        # and wrong separators.
        assert captured["prompt"] == (
            "system: be terse\n\nuser: what is 6*7?\n\nuser: show work"
        ), captured["prompt"]
        assert captured["cli"] == "claude", captured["cli"]

        # Response must serialize and carry the chat-completions fields.
        assert json.loads(json.dumps(resp)) == resp  # JSON round-trips
        assert resp["id"] == "chatcmpl-bridge"
        assert resp["object"] == "chat.completion"
        assert isinstance(resp["created"], int)
        assert resp["model"] == "claude-sonnet"
        choice = resp["choices"][0]
        assert choice["index"] == 0
        assert choice["message"] == {"role": "assistant", "content": "the answer is 42"}
        assert choice["finish_reason"] == "stop"
        assert set(resp["usage"]) == {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        }, resp["usage"]

        # CLI selection by model name (CLI env popped above).
        assert pick_cli("gpt-5.5") == "codex"
        assert pick_cli("codex-mini") == "codex"
        assert pick_cli("claude-opus-4-8") == "claude"
    finally:
        run_cli = real
        if old_cli is not None:
            os.environ["CLI"] = old_cli

    print("self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        demo()
    else:
        port = int(os.environ.get("PORT", "8848"))
        cli = os.environ.get("CLI", "(by model name)")
        print(f"cli-bridge: claude/codex on http://127.0.0.1:{port}/v1  (CLI={cli})")
        HTTPServer(("127.0.0.1", port), Handler).serve_forever()
