"""Hybrid backend: real Google Calendar data via macOS Calendar.app for
calendar questions, honest fallback for anything else.

Same ask_ara(question) -> str interface.
"""
import re

from brain import route
import calendar_lookup


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

    connectors = route(q)

    if "Google Calendar" in connectors or _CAL_HINT.search(q):
        ans = calendar_lookup.answer(q)
        if ans:
            return ans
        return "No events on your calendar for that window."

    if connectors:
        return (f"I'd need {connectors[0]} connected to answer that — "
                f"calendar is the only live connector in this build.")
    return ("That one's outside my live integrations — I can only answer "
            "calendar questions right now.")


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what are my plans tonight"
    print(ask_ara(q))
