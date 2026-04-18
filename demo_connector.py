"""Offline demo fallback. Returns plausible, confident-sounding answers
based on the brain router's classification of the question.

Same ask_ara(question) -> str interface as the other connectors.
"""
import random
import re

from brain import route


# Category -> list of candidate responses. Picked randomly so repeats don't
# feel robotic across a live demo.
RESPONSES: dict[str, list[str]] = {
    "Google Calendar": [
        "You have dinner with Sarah at 7:30 PM at Zuni Cafe tonight — it's on your calendar.",
        "Tomorrow you've got a 10 AM standup, then lunch with Marcus at noon, and a 3 PM pitch.",
        "Your next free slot is Thursday 2–4 PM — everything else this week is booked.",
        "You're free tonight after 6:15 PM; earlier you have the design review.",
    ],
    "Gmail": [
        "Sarah emailed you two hours ago about the Q4 proposal — top unread in your inbox.",
        "Three unread threads this morning, the most urgent is from legal about the NDA.",
        "Yes — Marcus replied yesterday at 4:12 PM confirming the meeting.",
    ],
    "Google Docs": [
        "Your Q4 roadmap doc is in Drive, last edited yesterday at 9:47 PM.",
        "The investor memo draft is 80% done — you left a comment on page 3 asking about metrics.",
        "Two docs match: the product brief and the rollout plan. The brief is more recent.",
    ],
    "Google Drive": [
        "It's in the 'Q4 Planning' folder, last modified two days ago by Marcus.",
        "Three matching files; the most relevant is 'Pitch-v7.pdf' from last Monday.",
    ],
    "Notion": [
        "Your Notion wiki has a page on that from October — the key takeaway was 30% retention lift.",
        "Matching page: 'Engineering Roadmap Q4' — last updated by Priya on Monday.",
    ],
    "Slack": [
        "That was discussed in #product yesterday around 2 PM — 14 replies in that thread.",
        "No recent Slack mentions; last time was in #general two weeks ago.",
    ],
    "Linear": [
        "That's issue ENG-412, currently in review, assigned to Priya, due Friday.",
        "Three open tickets on that — ENG-411, 412, and 418. 418 is the blocker.",
    ],
    "GitHub": [
        "PR #247 is open, 2 approvals, 1 pending review from you.",
        "Last commit to main was 3 hours ago by Marcus — a refactor of the auth flow.",
    ],
    "HubSpot": [
        "That lead is a warm opportunity — $45K ARR, last touched by you on Tuesday.",
        "Deal stage: proposal sent, 60% close probability, expected close end of month.",
    ],
    "Salesforce": [
        "That account is an Enterprise tier, 5 active contacts, last activity yesterday.",
    ],
    "Contacts": [
        "Their email is in your contacts — marked as a frequent correspondent.",
    ],
    "YouTube": [
        "That video has 2.1M views, posted last week; the key moment is around 7:30.",
    ],
    "Google Maps": [
        "It's 12 minutes by car with current traffic, or 18 by transit.",
    ],
}

FACTUAL: dict[re.Pattern, str] = {
    re.compile(r"\ba16z\b|andreessen\s+horowitz", re.I):
        "Andreessen Horowitz — $35B+ venture firm in Menlo Park, founded 2009 by Marc Andreessen and Ben Horowitz.",
    re.compile(r"\bycombinator\b|\byc\b", re.I):
        "Y Combinator — Mountain View accelerator, 3-month program, ~$500K for 7%, 4,000+ alumni.",
    re.compile(r"\bsequoia\b", re.I):
        "Sequoia Capital — founded 1972, $85B AUM, early backers of Apple, Google, Stripe, and Nvidia.",
    re.compile(r"\bopenai\b", re.I):
        "OpenAI — $157B valuation, makers of GPT and ChatGPT, founded 2015, led by Sam Altman.",
    re.compile(r"\banthropic\b", re.I):
        "Anthropic — $40B AI safety lab, makers of Claude, founded 2021 by former OpenAI researchers.",
}

FALLBACKS = [
    "Based on your recent notes, the short answer is: yes, but worth double-checking with the team.",
    "Your docs suggest the answer depends on timing — earlier this quarter the numbers trended up ~18%.",
    "Good question — quick read from your data says it's on track but slightly behind projection.",
    "From what's in your Drive, the consensus last week was to move forward with option B.",
]


def send_message(_text: str) -> bool:
    return True


def ask_ara(question: str, timeout: int = 25) -> str | None:
    q = question.lstrip("?").strip()

    # 1. Hard factual matches win
    for pattern, answer in FACTUAL.items():
        if pattern.search(q):
            return answer

    # 2. Brain-routed connector responses
    connectors = route(q)
    for c in connectors:
        if c in RESPONSES:
            return random.choice(RESPONSES[c])

    # 3. Generic confident-sounding fallback
    return random.choice(FALLBACKS)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what are my plans tonight"
    print(ask_ara(q))
