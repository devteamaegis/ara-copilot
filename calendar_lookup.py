"""Read events from macOS Calendar.app (which includes your Google Calendar if
it's synced via System Settings → Internet Accounts) and answer natural-language
questions about any day in the next ~2 weeks.

Pure AppleScript — no OAuth, no API keys. First run triggers a macOS prompt for
Automation → Calendar; grant it.
"""
import re
import subprocess
from datetime import datetime, timedelta


# Look 21 days ahead so "next Friday", "this weekend", "in two weeks" all resolve.
_LOOKAHEAD_DAYS = 21

_APPLESCRIPT = f'''
set out to ""
set today to current date
set hours of today to 0
set minutes of today to 0
set seconds of today to 0
set lookahead to today + ({_LOOKAHEAD_DAYS} * days)

tell application "Calendar"
    set cal_list to every calendar
    set out to "TOTAL_CALS|||" & (count of cal_list) & linefeed
    repeat with cal in cal_list
        try
            set cal_name to name of cal
            set evts to (every event of cal whose start date is greater than or equal to today and start date is less than lookahead)
            set ec to (count of evts)
            set out to out & "CAL|||" & cal_name & "|||" & ec & linefeed
            repeat with evt in evts
                set loc to ""
                try
                    set l to location of evt
                    if l is not missing value then set loc to l
                end try
                set out to out & "EVT|||" & (summary of evt) & "|||" & ((start date of evt) as string) & "|||" & ((end date of evt) as string) & "|||" & loc & "|||" & cal_name & linefeed
            end repeat
        on error errMsg
            set out to out & "ERR|||" & errMsg & linefeed
        end try
    end repeat
end tell
return out
'''


WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _parse_apple_date(s: str) -> datetime | None:
    # AppleScript dates look like: "Saturday, April 18, 2026 at 7:30:00 PM"
    for fmt in ("%A, %B %d, %Y at %I:%M:%S %p",
                "%A, %B %d, %Y at %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def get_events(verbose: bool = False) -> list[dict]:
    try:
        r = subprocess.run(["osascript", "-e", _APPLESCRIPT],
                           capture_output=True, text=True, timeout=20)
    except Exception as e:
        print(f"[calendar] osascript failed: {e}")
        return []
    if r.returncode != 0:
        print(f"[calendar] applescript error: {r.stderr.strip()}")
        return []

    events: list[dict] = []
    cal_summary: list[str] = []
    errors: list[str] = []
    total_cals = "?"

    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("TOTAL_CALS|||"):
            total_cals = line.split("|||", 1)[1].strip()
            continue
        if line.startswith("CAL|||"):
            parts = line.split("|||")
            if len(parts) >= 3:
                cal_summary.append(f"{parts[1]} ({parts[2]} events)")
            continue
        if line.startswith("ERR|||"):
            errors.append(line.split("|||", 1)[1])
            continue
        if line.startswith("EVT|||"):
            parts = line.split("|||")
            # EVT ||| title ||| start ||| end ||| loc ||| calendar
            if len(parts) < 4:
                continue
            title = parts[1].strip()
            start = _parse_apple_date(parts[2].strip())
            end = _parse_apple_date(parts[3].strip()) if len(parts) > 3 else None
            loc = parts[4].strip() if len(parts) > 4 else ""
            cal_name = parts[5].strip() if len(parts) > 5 else ""
            if start:
                events.append({
                    "title": title, "start": start, "end": end,
                    "location": loc, "calendar": cal_name,
                })

    events.sort(key=lambda e: e["start"])

    if verbose or not events:
        print(f"[calendar] total calendars visible: {total_cals}")
        for s in cal_summary:
            print(f"[calendar]   · {s}")
        for e in errors:
            print(f"[calendar]   ERROR: {e}")
        print(f"[calendar] total events in next {_LOOKAHEAD_DAYS} days: {len(events)}")
        has_google = any("gmail" in s.lower() or "google" in s.lower() or "@" in s
                         for s in cal_summary)
        if not has_google:
            print("[calendar] ⚠️  no Google calendar detected in Calendar.app")
            print("[calendar]    fix: System Settings → Internet Accounts → Google → toggle Calendars ON")

    return events


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lstrip("0")


def _fmt_day(dt: datetime, now: datetime) -> str:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    target = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (target - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if 2 <= delta <= 6:
        return dt.strftime("%A")           # "Wednesday"
    return dt.strftime("%A, %b %-d")       # "Friday, Apr 24"


def _fmt_event(e: dict, now: datetime, include_day: bool = False) -> str:
    s = f"{e['title']} at {_fmt_time(e['start'])}"
    if include_day:
        s += f" {_fmt_day(e['start'], now)}"
    if e.get("location"):
        s += f" ({e['location']})"
    return s


# ----------------------- window resolution -----------------------

def _next_weekday(now: datetime, target_wd: int, force_next_week: bool = False) -> datetime:
    """Return the start-of-day datetime for the next occurrence of target_wd
    (Mon=0..Sun=6). If today matches and force_next_week is False, returns today."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days_ahead = (target_wd - today.weekday()) % 7
    if force_next_week or (days_ahead == 0 and now.hour >= 20):
        # "next monday" said on monday → a week away; also if it's already late
        # the same-day query probably means the coming week's day.
        if days_ahead == 0:
            days_ahead = 7
    return today + timedelta(days=days_ahead)


def _apply_time_of_day(day_start: datetime, day_end: datetime, q: str) -> tuple[datetime, datetime, str]:
    """Narrow a whole-day window to morning/afternoon/evening/night if requested."""
    if re.search(r"\bmorning\b", q):
        return day_start.replace(hour=6), day_start.replace(hour=12), "morning"
    if re.search(r"\bafternoon\b", q):
        return day_start.replace(hour=12), day_start.replace(hour=17), "afternoon"
    if re.search(r"\bevening\b|\btonight\b", q):
        return day_start.replace(hour=17), day_start.replace(hour=22), "evening"
    if re.search(r"\bnight\b", q) and "tonight" not in q:
        return day_start.replace(hour=20), day_end, "night"
    return day_start, day_end, ""


def _resolve_window(q: str, now: datetime) -> tuple[datetime, datetime, str]:
    """Parse the question and return (window_start, window_end, label).
    Falls back to 'next 24 hours from now' if nothing specific matches."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    q = q.lower()

    # Specific calendar date: "april 22", "apr 22", "on the 22nd"
    m = re.search(r"\b(" + "|".join(MONTHS.keys()) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", q)
    if m:
        month = MONTHS[m.group(1)]
        day = int(m.group(2))
        year = now.year + (1 if month < now.month else 0)
        try:
            day_start = datetime(year, month, day)
            day_end = day_start + timedelta(days=1)
            s, e, tod = _apply_time_of_day(day_start, day_end, q)
            return s, e, (_fmt_day(day_start, now) + (f" {tod}" if tod else ""))
        except ValueError:
            pass

    # "in N days" / "N days from now"
    m = re.search(r"\bin\s+(\d{1,2})\s+days?\b|\b(\d{1,2})\s+days?\s+from\s+now\b", q)
    if m:
        n = int(m.group(1) or m.group(2))
        day_start = today + timedelta(days=n)
        day_end = day_start + timedelta(days=1)
        s, e, tod = _apply_time_of_day(day_start, day_end, q)
        return s, e, (_fmt_day(day_start, now) + (f" {tod}" if tod else ""))

    # "this weekend" / "next weekend"
    if "weekend" in q:
        nxt = "next" in q
        sat = _next_weekday(now, 5, force_next_week=nxt)
        return sat, sat + timedelta(days=2), ("next weekend" if nxt else "this weekend")

    # "next week"
    if re.search(r"\bnext week\b", q):
        mon = _next_weekday(now, 0, force_next_week=True)
        return mon, mon + timedelta(days=7), "next week"

    # "this week" / "rest of the week"
    if re.search(r"\bthis week\b|\brest of (the|my) week\b", q):
        end = today + timedelta(days=(7 - today.weekday()))  # next Monday 00:00
        return today, end, "this week"

    # Weekday names — "wednesday", "next friday", "what about monday"
    for wd_name, wd_num in WEEKDAYS.items():
        if re.search(rf"\b{wd_name}\b", q):
            force = bool(re.search(rf"\bnext\s+{wd_name}\b", q))
            day_start = _next_weekday(now, wd_num, force_next_week=force)
            day_end = day_start + timedelta(days=1)
            s, e, tod = _apply_time_of_day(day_start, day_end, q)
            label = _fmt_day(day_start, now)
            if force:
                label = f"next {wd_name.capitalize()}"
            if tod:
                label += f" {tod}"
            return s, e, label

    # "tonight"
    if "tonight" in q:
        return (now.replace(hour=17, minute=0, second=0, microsecond=0),
                today + timedelta(days=1), "tonight")

    # "tomorrow"
    if "tomorrow" in q:
        day_start = today + timedelta(days=1)
        day_end = day_start + timedelta(days=1)
        s, e, tod = _apply_time_of_day(day_start, day_end, q)
        return s, e, ("tomorrow" + (f" {tod}" if tod else ""))

    # "today" / "rest of my day" / "now"
    if re.search(r"\btoday\b|\brest of (the|my) day\b|\bright now\b", q):
        s, e, tod = _apply_time_of_day(today, today + timedelta(days=1), q)
        return (max(s, now), e, ("today" + (f" {tod}" if tod else "")))

    # Default: upcoming window — today from now through tomorrow
    return now, today + timedelta(days=2), "coming up"


# ----------------------- main answer -----------------------

def answer(question: str) -> str | None:
    """Return a calendar-grounded answer for any day in the next ~2 weeks.
    Returns None only if Calendar is unreachable."""
    events = get_events()
    now = datetime.now()

    win_start, win_end, label = _resolve_window(question, now)
    q = question.lower()
    relevant = [e for e in events if win_start <= e["start"] < win_end]

    # Availability questions
    if re.search(r"\bfree\b|\bavailable\b|\bavailability\b|\bopen\b", q):
        if not relevant:
            return f"You're wide open {label} — nothing on the calendar."
        first = relevant[0]
        return (f"You're booked {label} starting {_fmt_time(first['start'])} "
                f"for {first['title']}.")

    # Schedule questions
    if not relevant:
        # If calendar truly is empty, signal that differently.
        if not events:
            return None
        # Nearest upcoming event AFTER the empty window — much more helpful.
        after = [e for e in events if e["start"] >= win_end]
        if after:
            nxt = after[0]
            return (f"Nothing {label} — your next thing is "
                    f"{_fmt_event(nxt, now, include_day=True)}.")
        return f"Nothing on your calendar {label}."

    # Pick a readable format depending on how many events.
    multi_day = len({e["start"].date() for e in relevant}) > 1
    fmt = lambda e: _fmt_event(e, now, include_day=multi_day)

    if len(relevant) == 1:
        return f"{label.capitalize()}: {fmt(relevant[0])}."
    if len(relevant) == 2:
        return f"{label.capitalize()}: {fmt(relevant[0])}, then {fmt(relevant[1])}."
    if len(relevant) == 3:
        return (f"{label.capitalize()}: {fmt(relevant[0])}, "
                f"{fmt(relevant[1])}, then {fmt(relevant[2])}.")
    return (f"{label.capitalize()}: {fmt(relevant[0])}, {fmt(relevant[1])}, "
            f"plus {len(relevant) - 2} more.")


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if a != "--debug"]
    q = " ".join(args) or "what are my plans tonight"
    print(f"Q: {q}")
    events = get_events(verbose=True)
    print(f"\nEvents pulled ({len(events)}):")
    for e in events[:20]:
        print(f"  · {e['start'].strftime('%a %b %-d %-I:%M%p')}  "
              f"{e['title']}  [{e.get('calendar', '?')}]")
    print(f"\nAnswer: {answer(q)}")
