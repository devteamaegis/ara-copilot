# Ara Copilot

AI earpiece for live calls on macOS. A menu-bar app that listens during FaceTime / Zoom / Meet / Teams calls, transcribes locally with Whisper, and answers the other person's questions in real time — grounded in your actual Google Calendar, Gmail, and Drive — inside a transparent overlay that floats over the call window.

Built at a hackathon, April 2026.

## What it does

- **Auto-detects calls.** psutil + AppleScript watches for FaceTime, Zoom, Meet, Teams, Webex. Menu bar icon flips from `⚪ Ara` to `🟢 Ara` the moment a call starts.
- **Transcribes your mic locally.** `faster-whisper` with the `tiny.en` model runs on-device — audio never leaves the Mac. Prefers the built-in mic so AirPods being grabbed by FaceTime doesn't break capture.
- **Routes questions through a "brain".** `brain.py` is a keyword router that classifies each utterance into connector categories (Calendar, Gmail, Drive, Notion, Linear, etc.) and injects a hint into the prompt.
- **Answers live with real data.**
  - **Calendar questions** go to a direct macOS Calendar.app reader (`calendar_lookup.py`) that pulls your synced Google Calendar via AppleScript. Handles weekdays ("Wednesday"), relative dates ("in 3 days"), time buckets ("Friday afternoon"), and specific dates ("April 22").
  - **General questions** can route to an Ara agent over iMessage, to Anthropic's API, or to a canned demo backend — switched via env var.
- **Renders in a transparent overlay.** PyObjC `NSWindow` at screensaver window level so it floats above full-screen FaceTime. EB Garamond typography with fade-in transitions on every update. Click-through (`setIgnoresMouseEvents_`).
- **Manual hotkey.** `Cmd+Shift+A` anywhere on the system opens a quick Ask dialog.

## Architecture

```
┌─────────────┐   mic   ┌──────────────┐   text    ┌────────┐
│ Call app    │────────▶│ transcriber  │──────────▶│ main   │
│ FaceTime    │         │ Whisper tiny │           │ (rumps)│
└─────────────┘         └──────────────┘           └────┬───┘
                                                        │
                               ┌────────────────────────┼───────────────────┐
                               ▼                        ▼                   ▼
                        ┌─────────────┐          ┌───────────┐       ┌───────────┐
                        │ brain       │          │ connector │       │ overlay   │
                        │ (routing)   │          │ (ask_ara) │       │ (PyObjC)  │
                        └─────────────┘          └─────┬─────┘       └───────────┘
                                                       │                   ▲
                                          ┌────────────┼─────────────┐     │
                                          ▼            ▼             ▼     │
                                  ┌─────────────┐ ┌─────────┐ ┌──────────┐ │
                                  │ Mac         │ │ Ara     │ │ Claude / │ │
                                  │ Calendar.app│ │ iMessage│ │ demo     │─┘
                                  └─────────────┘ └─────────┘ └──────────┘
```

## Backends

Pick one by setting an env var before launching:

| Env var | Module | What it does |
|---|---|---|
| `CALENDAR_MODE=1` | `hybrid_connector.py` | Calendar via local Mac Calendar.app; honest fallback for everything else. **Fastest, most deterministic — demo default.** |
| `ANTHROPIC_API_KEY=…` | `llm_connector.py` | Claude 3.5 Haiku via REST. |
| `DEMO_MODE=1` | `demo_connector.py` | Canned plausible answers per connector category. Offline. |
| *(none)* | `ara_connector.py` | Sends `? <question>` to the Ara agent via iMessage, polls `chat.db` for the reply. |

## Setup

```bash
cd ara-copilot-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Install EB Garamond** (optional — falls back to Hoefler Text / Baskerville / Palatino otherwise): download from [fonts.google.com/specimen/EB+Garamond](https://fonts.google.com/specimen/EB+Garamond), unzip, drag the `.ttf` files into Font Book.

## Capture both sides of the call (BlackHole setup)

**Without this step the app only hears YOU, not the other person on FaceTime/Zoom.** The mic can't pick up what's playing through your speakers or AirPods. Fix: install a virtual audio loopback and combine it with your mic into a single "Aggregate Device" the app can capture from.

**1. Install BlackHole 2ch** (free, open-source virtual audio driver)

```bash
# easiest: via Homebrew
brew install blackhole-2ch
# or download the installer from https://existential.audio/blackhole/
```

After install, **reboot your Mac** (required for macOS to load the driver).

**2. Create an Aggregate Device called "Ara Capture"** (app captures from this)

Open **Audio MIDI Setup** (Spotlight → "Audio MIDI") → click `+` bottom-left → **Create Aggregate Device**. In the right pane, check:

- ☑ MacBook Pro Microphone (or your preferred mic)
- ☑ BlackHole 2ch

Double-click the new device in the list, rename it to **Ara Capture**.

**3. Create a Multi-Output Device called "Ara Output"** (so you can still hear the call)

Same window → `+` → **Create Multi-Output Device**. Check:

- ☑ MacBook Pro Speakers (or AirPods)
- ☑ BlackHole 2ch

Rename it to **Ara Output**.

**4. Route FaceTime audio through it**

System Settings → Sound → Output → select **Ara Output**. FaceTime's audio now goes to both your ears and BlackHole at the same time. The app auto-picks any device whose name contains "Ara Capture", "aggregate", or "BlackHole" — no code change needed.

Verify: start the app, look for `[transcriber] using input device: 'Ara Capture'` in the log.

## Required macOS permissions

Open **System Settings → Privacy & Security** and grant Terminal (or your Python runner) access to:

1. **Microphone** — for Whisper.
2. **Accessibility** — for the global `Cmd+Shift+A` hotkey.
3. **Full Disk Access** — for `ara_connector.py` to read `~/Library/Messages/chat.db` (only needed in Ara-iMessage mode).
4. **Automation → Calendar** — for `calendar_lookup.py` to read events (prompted on first run).
5. **Automation → Messages** — for AppleScript to send via iMessage (prompted on first send).

For calendar mode, also sync Google Calendar into Mac Calendar.app: **System Settings → Internet Accounts → Google → toggle Calendars ON**.

## Run

```bash
source venv/bin/activate
export CALENDAR_MODE=1      # recommended for demo
python main.py
```

`⚪ Ara` appears top-right of the menu bar. Start a FaceTime → it flips to `🟢 Ara` and the transparent HUD fades in bottom-right.

## Demo flow

1. Launch with `CALENDAR_MODE=1`.
2. Start FaceTime — icon turns green, overlay appears.
3. The other person asks "what are your plans tonight?"
4. Transcript fades in live; a few seconds later Ara's answer fades in below it: *"You have Ty Dolla Sign Concert at 6 PM, then DKE Party at 10 PM."* (real events from your Google Calendar).
5. Press `Cmd+Shift+A` to ask anything manually mid-call.

## Files

| File | Purpose |
|------|---------|
| `main.py` | rumps menu-bar app; timers, hotkey, IPC to overlay |
| `overlay.py` | PyObjC transparent `NSWindow`; EB Garamond; fade-in transitions |
| `transcriber.py` | `sounddevice` capture + `faster-whisper` tiny.en |
| `call_detector.py` | `psutil` + AppleScript call detection |
| `brain.py` | Keyword router → connector categories + prompt hints |
| `calendar_lookup.py` | Direct Mac Calendar.app reader via AppleScript |
| `hybrid_connector.py` | Calendar via local, honest fallback otherwise |
| `ara_connector.py` | iMessage send + `chat.db` polling for Ara replies |
| `llm_connector.py` | Anthropic Claude via REST |
| `demo_connector.py` | Canned offline responses per connector |

## Troubleshooting

- **"Operation not permitted" reading `chat.db`** → grant Full Disk Access to Terminal; restart Terminal.
- **Hotkey does nothing** → grant Accessibility to Terminal.
- **No transcription** → grant Microphone; check `faster-whisper` installed (tiny model ~75MB, downloads on first run).
- **Calendar says "Nothing on your calendar"** → run `python calendar_lookup.py "monday"` to see which calendars are visible. If no Google calendar listed, sync via System Settings → Internet Accounts.
- **Double overlay after restart** → old subprocess didn't die. Run `pkill -f overlay.py; pkill -f "python main.py"` before relaunching.
- **AppleScript fails to send to Messages** → open Messages, confirm iMessage is signed in, send one manual message to the Ara number first so the conversation exists.

## License

MIT.
