"""Send/receive messages to the Ara agent via the Mac Messages app.

Ara phone number: +1 (415) 792-8699
Uses AppleScript to send via iMessage, and reads chat.db to poll for replies.
"""
import os
import sqlite3
import subprocess
import time

ARA_NUMBER = "+14157928699"
MESSAGES_DB = os.path.expanduser("~/Library/Messages/chat.db")

# Apple's epoch is 2001-01-01 UTC
APPLE_EPOCH_OFFSET = 978307200


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_message(text: str) -> bool:
    """Send a message to Ara via iMessage. Returns True on success."""
    safe = _escape_applescript(text)
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{ARA_NUMBER}" of targetService
        send "{safe}" to targetBuddy
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"[ara_connector] AppleScript send error: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"[ara_connector] send_message exception: {e}")
        return False


def _apple_to_unix(apple_date: int) -> float:
    """Convert Apple Cocoa date (nanoseconds since 2001-01-01) to unix seconds."""
    # Some older rows store seconds, newer rows store nanoseconds.
    if apple_date > 1e12:
        return (apple_date / 1e9) + APPLE_EPOCH_OFFSET
    return apple_date + APPLE_EPOCH_OFFSET


def get_latest_reply(since_timestamp: float = None):
    """Return {'text', 'timestamp'} of the latest incoming msg from Ara, or None."""
    if not os.path.exists(MESSAGES_DB):
        return None
    try:
        conn = sqlite3.connect(f"file:{MESSAGES_DB}?mode=ro", uri=True, timeout=2)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT message.text, message.attributedBody, message.date, message.is_from_me
            FROM message
            JOIN handle ON message.handle_id = handle.ROWID
            WHERE handle.id LIKE ?
              AND message.is_from_me = 0
            ORDER BY message.date DESC
            LIMIT 5
            """,
            ("%4157928699%",),
        )
        rows = cur.fetchall()
        conn.close()
        for text, attr_body, apple_date, _ in rows:
            body = text
            if not body and attr_body:
                # Fallback: pull readable text from the typedstream blob.
                try:
                    raw = bytes(attr_body)
                    idx = raw.find(b"NSString")
                    if idx != -1:
                        tail = raw[idx + 12 :]
                        # crude: take printable ASCII run
                        out = []
                        for b in tail:
                            if 32 <= b < 127 or b in (10, 13):
                                out.append(chr(b))
                            else:
                                if out:
                                    break
                        body = "".join(out).strip() or None
                except Exception:
                    body = None
            if not body:
                continue
            unix_ts = _apple_to_unix(apple_date)
            if since_timestamp is None or unix_ts > since_timestamp:
                return {"text": body, "timestamp": unix_ts}
        return None
    except sqlite3.OperationalError as e:
        print(f"[ara_connector] DB access error (grant Full Disk Access to Terminal): {e}")
        return None
    except Exception as e:
        print(f"[ara_connector] get_latest_reply error: {e}")
        return None


def ask_ara(question: str, timeout: int = 30) -> str | None:
    """Send a '?' prefixed question and poll for Ara's reply."""
    q = question.strip()
    if not q.startswith("?"):
        q = "? " + q

    before = get_latest_reply()
    before_ts = before["timestamp"] if before else (time.time() - 1)

    if not send_message(q):
        return None

    start = time.time()
    while time.time() - start < timeout:
        reply = get_latest_reply(since_timestamp=before_ts)
        if reply:
            return reply["text"]
        time.sleep(1.5)
    return None


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "? test from ara copilot"
    print(f"Asking Ara: {q}")
    reply = ask_ara(q, timeout=40)
    print(f"Reply: {reply}")
