"""Detect whether a call app is currently running on the Mac."""
import subprocess

import psutil

# Process-name substring -> friendly app name
PROCESS_HINTS = [
    ("FaceTime", "FaceTime"),
    ("zoom.us", "Zoom"),
    ("ZoomClips", "Zoom"),
    ("CptHost", "Zoom"),
    ("Microsoft Teams", "Teams"),
    ("Webex", "Webex"),
    ("Meet", "Meet"),
    ("Discord", "Discord"),
    ("Slack", "Slack"),
]


def _chrome_meet_active() -> bool:
    """Return True if Chrome has a Google Meet tab as active tab."""
    script = (
        'tell application "System Events" to (name of processes) contains "Google Chrome"'
    )
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
        if "true" not in r.stdout.lower():
            return False
    except Exception:
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "Google Chrome" to get URL of active tab of front window'],
            capture_output=True, text=True, timeout=2,
        )
        return "meet.google.com" in (r.stdout or "")
    except Exception:
        return False


def is_call_active() -> tuple[bool, str | None]:
    """Return (active, app_name)."""
    try:
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name") or ""
            for hint, friendly in PROCESS_HINTS:
                if hint.lower() in name.lower():
                    return True, friendly
    except Exception:
        pass
    if _chrome_meet_active():
        return True, "Google Meet"
    return False, None


if __name__ == "__main__":
    print(is_call_active())
