"""Drop-in replacement for ara_connector — calls Anthropic Claude.

Same ask_ara(question, timeout) -> str|None interface. Requires
ANTHROPIC_API_KEY env var.
"""
import json
import os
import urllib.request

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("LLM_MODEL", "claude-3-5-haiku-20241022")

SYSTEM = (
    "You are a live-call copilot earpiece. Answer what was just said on the "
    "call concisely: ONE sentence, under 25 words, no preamble. Be specific, "
    "confident, and useful. If it's a question, answer directly. If it's a "
    "claim, add a sharp fact or counterpoint."
)


def send_message(_text: str) -> bool:  # kept for API parity; unused
    return True


def ask_ara(question: str, timeout: int = 25) -> str | None:
    if not API_KEY:
        return "(missing ANTHROPIC_API_KEY — export it and restart)"
    q = question.lstrip("?").strip()
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 120,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": q}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            parts = data.get("content", [])
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            return text.strip() or None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[llm] HTTP {e.code}: {body}")
        return None
    except Exception as e:
        print(f"[llm] error: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what is a16z"
    print(ask_ara(q))
