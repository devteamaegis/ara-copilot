"""Intent router — classifies what was just said and suggests which Ara
connectors are likely relevant. The hint is passed through in the Ara prompt
so the agent on the other side knows which tool to reach for.

Lightweight keyword matching. Fast, dependency-free, good enough for a demo.
"""
import re


# Each category maps to (connector hints shown to Ara, keyword patterns).
CATEGORIES: dict[str, dict] = {
    "calendar": {
        "connectors": ["Google Calendar"],
        "patterns": [
            r"\bcalendar\b", r"\bschedule\b", r"\bschedul", r"\bmeeting\b",
            r"\bmeet(ing|ings|up)\b", r"\bappointment\b", r"\bplans?\b",
            r"\btonight\b", r"\btomorrow\b", r"\bthis (morning|afternoon|evening|week|weekend)\b",
            r"\bnext (week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\bwhat time\b", r"\bwhen (is|are|do|does|will)\b",
            r"\bfree (tonight|tomorrow|at|on)\b", r"\bavailable\b",
            r"\b(book|cancel|reschedule)\b",
        ],
    },
    "email": {
        "connectors": ["Gmail"],
        "patterns": [
            r"\bemail(s|ed|ing)?\b", r"\bgmail\b", r"\binbox\b", r"\bunread\b",
            r"\b(sent|replied|received|forwarded) (a|an|the)? (email|message|note)\b",
            r"\bsubject line\b", r"\bcc(d|'d)?\b", r"\bbcc\b",
        ],
    },
    "docs": {
        "connectors": ["Google Docs"],
        "patterns": [
            r"\bdoc(ument|s)?\b", r"\bdraft(ed|ing|s)?\b", r"\bwrote\b",
            r"\bmemo\b", r"\bproposal\b", r"\bbrief\b", r"\bnotes?\b",
            r"\bwrite-?up\b", r"\bshared (with|to) me\b",
        ],
    },
    "drive": {
        "connectors": ["Google Drive"],
        "patterns": [
            r"\bdrive\b", r"\bfolder\b", r"\bspreadsheet\b", r"\bsheet\b",
            r"\bfile\b", r"\battachment\b", r"\bupload(ed)?\b",
        ],
    },
    "notion": {
        "connectors": ["Notion"],
        "patterns": [r"\bnotion\b", r"\bwiki\b", r"\bnotion page\b"],
    },
    "slack": {
        "connectors": ["Slack"],
        "patterns": [r"\bslack\b", r"\b#[a-z0-9_-]+\b", r"\bchannel\b", r"\bdm(ed|'d)?\b"],
    },
    "linear": {
        "connectors": ["Linear"],
        "patterns": [r"\blinear\b", r"\bticket\b", r"\bissue\b", r"\bsprint\b",
                     r"\bbacklog\b", r"\b(bug|feature) (report|request)\b"],
    },
    "github": {
        "connectors": ["GitHub"],
        "patterns": [r"\bgithub\b", r"\bpull request\b", r"\bpr #\d", r"\bcommit\b",
                     r"\brepo(sitory)?\b", r"\bbranch\b", r"\bmerge\b"],
    },
    "crm": {
        "connectors": ["HubSpot", "Salesforce"],
        "patterns": [r"\bhubspot\b", r"\bsalesforce\b", r"\bcrm\b",
                     r"\b(lead|deal|opportunity|contact) (record|status|in crm)\b"],
    },
    "contacts": {
        "connectors": ["Contacts", "Gmail"],
        "patterns": [r"\bwho is\b", r"\btheir (phone|number|email|address)\b",
                     r"\bcontact (info|details)\b"],
    },
    "youtube": {
        "connectors": ["YouTube"],
        "patterns": [r"\byoutube\b", r"\bvideo (link|url)\b"],
    },
    "maps": {
        "connectors": ["Google Maps"],
        "patterns": [r"\bdirections\b", r"\bhow (do i|to) get to\b", r"\bmaps?\b",
                     r"\baddress of\b"],
    },
}


def route(text: str, max_connectors: int = 3) -> list[str]:
    """Return connector names ranked by relevance to the given text.

    Returns an empty list if nothing matches confidently.
    """
    if not text:
        return []
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for _cat, info in CATEGORIES.items():
        hits = sum(1 for p in info["patterns"] if re.search(p, text_lower))
        if hits:
            for c in info["connectors"]:
                scores[c] = scores.get(c, 0) + hits
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [name for name, _ in ranked[:max_connectors]]


def hint_sentence(text: str) -> str:
    """Return a short prompt-ready sentence hinting at which connectors to use,
    or '' if nothing clearly matches."""
    connectors = route(text)
    if not connectors:
        return ""
    if len(connectors) == 1:
        return f"Likely relevant tool: {connectors[0]}."
    return f"Likely relevant tools: {', '.join(connectors)}."


if __name__ == "__main__":
    import sys
    sample = " ".join(sys.argv[1:]) or "what time are my plans tonight"
    print("Input:", sample)
    print("Route:", route(sample))
    print("Hint :", hint_sentence(sample))
