"""Hybrid backend: real Google Calendar data via macOS Calendar.app for
calendar questions, honest fallback for anything else.

Same ask_ara(question) -> str interface.
"""
import re
from datetime import datetime

from brain import route
import calendar_lookup


# --- General-knowledge patterns handled locally (instant, no network) ---

_TIME_Q = re.compile(
    r"\bwhat(?:'s|s|\s+is)?\s+the\s+time\b|"
    r"\bwhat\s+time\s+is\s+it\b|"
    r"\btime\s+is\s+it\b|"
    r"\bwhat\s+time\s+it\s+is\b|"
    r"\bcurrent\s+time\b|"
    r"\bgot\s+the\s+time\b|"
    r"\btell\s+me\s+the\s+time\b|"
    r"\btime\s+right\s+now\b",
    re.I,
)
_DATE_Q = re.compile(
    r"\bwhat(?:'s|s|\s+is)?\s+(?:the\s+|today'?s?\s+)?date\b|"
    r"\bwhat\s+day\s+is\s+(?:it|today)\b|"
    r"\btoday'?s\s+date\b",
    re.I,
)
_DAY_Q = re.compile(
    r"\bwhat\s+day\s+of\s+the\s+week\b|"
    r"\bwhich\s+day\s+(?:is\s+)?it\b",
    re.I,
)
_SELF_Q = re.compile(
    r"\bwho\s+are\s+you\b(?!\s+(?:doing|up|seeing|meeting))|"
    r"\bwhat\s+are\s+you\b(?!\s+(?:doing|up|seeing|meeting|planning))|"
    r"\bwhat\s+is\s+ara\b|"
    r"\btell\s+me\s+about\s+yourself\b|"
    r"\bwho\s+made\s+you\b",
    re.I,
)
# "What are you doing [time]" is a schedule question, not identity.
_SCHEDULE_Q = re.compile(
    r"\bwhat\s+are\s+you\s+(?:doing|up\s+to|planning)\b|"
    r"\bwhat(?:'s|s|\s+is)?\s+your\s+schedule\b|"
    r"\bany\s+plans\b",
    re.I,
)
_GREETING_Q = re.compile(
    r"\bhow\s+are\s+you\b|\bhow'?s\s+it\s+going\b|\bwhat'?s\s+up\b",
    re.I,
)


def _answer_general(q: str) -> str | None:
    now = datetime.now()
    if _TIME_Q.search(q):
        return f"It's {now.strftime('%-I:%M %p').lstrip('0')}."
    if _DAY_Q.search(q):
        return f"It's {now.strftime('%A')}."
    if _DATE_Q.search(q):
        return f"Today is {now.strftime('%A, %B %-d, %Y')}."
    if _SELF_Q.search(q):
        return ("I'm Ara — a live-call copilot. I listen to your calls, "
                "read your calendar, and answer in real time.")
    if _GREETING_Q.search(q):
        return "Good — listening in. Ask me anything."
    return None


# Anything that smells like a scheduling question routes to the live calendar.
_CAL_HINT = re.compile(
    r"\b("
    r"plans?|calendar|schedule|agenda|meeting|meetings|event|events|"
    r"booked|busy|free|available|availability|open|"
    r"tonight|today|tomorrow|weekend|this\s+week|next\s+week|"
    r"morning|afternoon|evening|night|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|tues|wed|thu|thurs|fri|sat|sun|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"when('?s| is)|what time|what day|which day"
    r")\b",
    re.I,
)


def send_message(_text: str) -> bool:
    return True


def ask_ara(question: str, timeout: int = 10) -> str | None:
    q = question.lstrip("?").strip()

    # If this is a Live-call-mode prompt, extract ONLY what the user actually
    # said (between Just said: "..."). Otherwise the calendar resolver will
    # match words like "connected" or "Drive" from the meta-prompt instead of
    # the real question.
    m = re.search(r'Just said:\s*"([^"]+)"', q)
    if m:
        q = m.group(1).strip()

    # 1. General-knowledge shortcuts (time, date, identity) — instant.
    g = _answer_general(q)
    if g:
        return g

    # 2. Schedule phrasings ("what are you doing today") → calendar.
    if _SCHEDULE_Q.search(q):
        ans = calendar_lookup.answer(q)
        if ans:
            return ans
        return "Nothing on your calendar for that window."

    connectors = route(q)

    if "Google Calendar" in connectors or _CAL_HINT.search(q):
        ans = calendar_lookup.answer(q)
        if ans:
            return ans
        return "No events on your calendar for that window."

    # Best-effort fallbacks — much friendlier than "outside my integrations."
    if connectors:
        return (f"I'd need {connectors[0]} live to answer that properly — "
                f"try asking about the calendar, the time, or the date.")
    return ("I can't answer that one right now — try asking about the "
            "calendar, the time, or what I am.")


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what are my plans tonight"
    print(ask_ara(q))
