"""Ara Copilot — macOS menu bar app.

Ties together:
  - call_detector: knows when a call is active
  - transcriber: streams mic audio -> text (Whisper tiny)
  - ara_connector: sends/receives messages to the Ara agent via iMessage
  - overlay: bottom-right floating HUD (separate tk subprocess)
  - global hotkey: Cmd+Shift+A to ask Ara manually
"""
import json
import os
import re
import subprocess
import sys
import threading
import time


_QUESTION_STARTERS = (
    "what", "when", "where", "who", "why", "how", "which",
    "is", "are", "am", "was", "were",
    "do", "does", "did", "can", "could", "would", "will",
    "have", "has", "should", "tell", "got",
)


def _last_sentence(text: str, fallback_words: int = 16) -> str:
    """Pick the most recent *question-shaped* sentence from a running
    transcript. Whisper often emits noisy chunks, so we prefer sentences
    that start with a question word, falling back to the last chunk."""
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r'[.?!]+', text) if p.strip()]
    if not parts:
        words = text.split()
        return " ".join(words[-fallback_words:]) if words else ""

    # Prefer the LATEST sentence that looks like a question.
    for p in reversed(parts):
        words = p.split()
        if len(words) < 2:
            continue
        if words[0].lower().strip(",") in _QUESTION_STARTERS:
            return p

    # No clearly question-shaped sentence — take the latest substantive chunk.
    for p in reversed(parts):
        if len(p.split()) >= 2:
            return p
    return parts[-1]

import rumps
from pynput import keyboard

if os.environ.get("CALENDAR_MODE"):
    from hybrid_connector import ask_ara
    print("[main] CALENDAR MODE — real Google Calendar via macOS Calendar.app")
elif os.environ.get("DEMO_MODE"):
    from demo_connector import ask_ara
    print("[main] DEMO MODE — using canned responses (no network)")
elif os.environ.get("ANTHROPIC_API_KEY"):
    from llm_connector import ask_ara
    print("[main] using Anthropic backend")
else:
    from ara_connector import ask_ara
    print("[main] using Ara (iMessage) backend")
from brain import hint_sentence, route
from call_detector import is_call_active
from transcriber import Transcriber


APP_DIR = os.path.dirname(os.path.abspath(__file__))
OVERLAY_SCRIPT = os.path.join(APP_DIR, "overlay.py")
OVERLAY_LOG = os.path.join(APP_DIR, "overlay.log")

ARA_SUGGESTION_EVERY = 10  # seconds — how often we ask Ara for a fresh answer
HEARTBEAT_SECONDS = 2      # overlay refresh cadence
ARA_CONTEXT_SECONDS = 15   # how much recent transcript we send to Ara


class AraCopilot(rumps.App):
    def __init__(self):
        super().__init__("Ara Copilot", title="⚪ Ara", quit_button="Quit")
        self.menu = [
            "Start listening",
            "Stop",
            None,
            "Show overlay",
            "Hide overlay",
            "Clear",
            None,
            "Ask Ara…",
        ]

        self.listening = False
        self.call_active = False
        self._manual_mode = False      # True = user-controlled, ignore auto-detect
        self.overlay_proc: subprocess.Popen | None = None
        self.transcriber = Transcriber(on_transcript=self._on_transcript)
        self.last_ara_suggestion = 0.0
        self._hotkey_listener: keyboard.Listener | None = None
        self._ask_in_progress = False
        self._last_ara_text = ""

        self._start_overlay()
        self._start_hotkey()

        rumps.Timer(self._check_call, 5).start()
        rumps.Timer(self._maybe_ask_ara, 8).start()
        rumps.Timer(self._heartbeat, HEARTBEAT_SECONDS).start()

    # ---------- overlay IPC ----------
    def _start_overlay(self):
        try:
            log_fh = open(OVERLAY_LOG, "a", buffering=1)
            log_fh.write("\n--- overlay launched ---\n")
            self.overlay_proc = subprocess.Popen(
                [sys.executable, OVERLAY_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=log_fh,
                stderr=log_fh,
            )
            print(f"[main] overlay started (pid {self.overlay_proc.pid}) — log: {OVERLAY_LOG}")
        except Exception as e:
            print(f"[main] failed to start overlay: {e}")

    def _send_overlay(self, payload: dict):
        if not self.overlay_proc or self.overlay_proc.poll() is not None:
            self._start_overlay()
        try:
            line = (json.dumps(payload) + "\n").encode("utf-8")
            self.overlay_proc.stdin.write(line)
            self.overlay_proc.stdin.flush()
        except Exception as e:
            print(f"[main] overlay write error: {e}")

    # ---------- transcription ----------
    def _on_transcript(self, _text: str):
        live = self.transcriber.get_recent_text(seconds=15)
        self._send_overlay({"transcript": live})

    def _start_listening(self):
        if self.listening:
            return
        # Clear stale transcripts so we start fresh
        self.transcriber.recent_transcripts = []
        self._last_ara_text = ""
        self.last_ara_suggestion = 0.0
        self.listening = True
        self.transcriber.start()
        self.title = "🟢 Ara"
        self._send_overlay({"show": True, "transcript": "Listening…", "ara": ""})

    def _stop_listening(self):
        self.listening = False
        self.transcriber.stop()
        self.title = "⚪ Ara"

    # ---------- heartbeat ----------
    def _heartbeat(self, _):
        """Push current state to overlay every few seconds so it never looks frozen."""
        if not self.listening:
            return
        live = self.transcriber.get_recent_text(seconds=25)
        if not live:
            live = "(listening — say something…)"
        self._send_overlay({"transcript": live})

    # ---------- call detection ----------
    def _check_call(self, _):
        if self._manual_mode:
            return  # user is driving; don't fight them
        active, app = is_call_active()
        if active and not self.call_active:
            print(f"[main] call detected: {app}")
            self.call_active = True
            self._start_listening()
        elif not active and self.call_active:
            print("[main] call ended")
            self.call_active = False
            self._stop_listening()
            self._send_overlay({"hide": True})

    # ---------- Ara suggestions ----------
    def _maybe_ask_ara(self, _):
        if not self.listening or self._ask_in_progress:
            return
        if time.time() - self.last_ara_suggestion < ARA_SUGGESTION_EVERY:
            return
        transcript = self.transcriber.get_recent_text(seconds=ARA_CONTEXT_SECONDS)
        if not transcript or len(transcript.split()) < 4:
            return
        # Use ONLY the most recent sentence so old questions don't linger in
        # the sliding window and cause the overlay to re-answer stale content.
        question = _last_sentence(transcript)
        if not question or len(question.split()) < 3:
            return
        # Skip if we just answered this exact utterance.
        if question == getattr(self, "_last_question", None):
            return
        self._last_question = question
        self.last_ara_suggestion = time.time()
        hint = hint_sentence(question)
        connectors = route(question)
        if connectors:
            print(f"[brain] routed to: {connectors}")
        prompt = (
            "? Live-call copilot mode. Use my connected data (Drive, Docs, "
            "Gmail, Calendar, Notion, Linear, etc.) to answer what was just "
            "said on my call. If it's a question, answer it directly and "
            "concretely with real data from my tools. If it's a claim, add "
            "one sharp fact. Reply in ONE sentence, under 25 words, no "
            "preamble. "
            + (hint + " " if hint else "")
            + "Just said: \"" + question + "\""
        )
        self._ask_ara_async(prompt, label="answer")

    def _ask_ara_async(self, question: str, label: str = "ask"):
        def _run():
            self._ask_in_progress = True
            try:
                self._send_overlay({"ara": "thinking…"})
                reply = ask_ara(question, timeout=25)
                if reply:
                    self._last_ara_text = reply
                    self._send_overlay({"ara": reply})
                else:
                    self._send_overlay({"ara": self._last_ara_text or "(no reply yet)"})
            finally:
                self._ask_in_progress = False
        threading.Thread(target=_run, daemon=True).start()

    # ---------- hotkey + manual ask ----------
    def _start_hotkey(self):
        def on_activate():
            threading.Thread(target=self._prompt_and_ask, daemon=True).start()

        hotkey = keyboard.HotKey(keyboard.HotKey.parse("<cmd>+<shift>+a"), on_activate)

        def on_press(k):
            try:
                hotkey.press(self._hotkey_listener.canonical(k))
            except Exception:
                pass

        def on_release(k):
            try:
                hotkey.release(self._hotkey_listener.canonical(k))
            except Exception:
                pass

        self._hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._hotkey_listener.start()

    def _prompt_and_ask(self):
        script = (
            'tell application "System Events" to activate\n'
            'set answer to text returned of (display dialog "Ask Ara:" '
            'default answer "" with title "Ara Copilot" buttons {"Cancel","Ask"} '
            'default button "Ask")\n'
            "return answer"
        )
        try:
            r = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=120
            )
            q = (r.stdout or "").strip()
        except Exception as e:
            print(f"[main] prompt error: {e}")
            return
        if not q:
            return
        raw = q.lstrip("?").strip()
        hint = hint_sentence(raw)
        if route(raw):
            print(f"[brain] manual ask routed to: {route(raw)}")
        q = "? " + (hint + " " if hint else "") + raw
        self._send_overlay({"show": True, "ara": "Asking Ara…"})
        self._ask_ara_async(q, label="manual")

    # ---------- menu actions ----------
    @rumps.clicked("Start listening")
    def menu_start(self, _):
        self._manual_mode = True
        self._start_listening()

    @rumps.clicked("Stop")
    def menu_stop(self, _):
        self._manual_mode = False
        self._stop_listening()
        self._send_overlay({"hide": True})

    @rumps.clicked("Show overlay")
    def menu_show(self, _):
        self._send_overlay({"show": True})

    @rumps.clicked("Hide overlay")
    def menu_hide(self, _):
        self._send_overlay({"hide": True})

    @rumps.clicked("Clear")
    def menu_clear(self, _):
        self.transcriber.recent_transcripts = []
        self._last_ara_text = ""
        self.last_ara_suggestion = 0.0
        self._send_overlay({"transcript": "(cleared — listening…)", "ara": ""})

    @rumps.clicked("Ask Ara…")
    def menu_ask(self, _):
        threading.Thread(target=self._prompt_and_ask, daemon=True).start()


if __name__ == "__main__":
    AraCopilot().run()
