"""Transparent floating overlay — PyObjC NSWindow with EB Garamond
typography and fade-in transitions on every update.

Reads JSON lines from stdin:
    {"transcript": "..."}  -> live caption line
    {"ara": "..."}         -> Ara answer (rendered bigger)
    {"show": true}         -> show overlay
    {"hide": true}         -> hide overlay
    {"quit": true}         -> exit
"""
import json
import sys
import threading

import objc
from Foundation import NSObject, NSMakeRect, NSTimer, NSAttributedString
from AppKit import (
    NSApplication, NSColor, NSFont, NSTextField, NSView, NSScreen,
    NSWindow, NSBackingStoreBuffered, NSShadow, NSAnimationContext,
    NSWindowStyleMaskBorderless,
    NSForegroundColorAttributeName, NSFontAttributeName,
    NSShadowAttributeName, NSKernAttributeName,
)
from PyObjCTools import AppHelper


# Window levels. ScreenSaver = 1000, above fullscreen FaceTime.
NS_SCREENSAVER_WINDOW_LEVEL = 1000
# canJoinAllSpaces(1) | stationary(16) | fullScreenAuxiliary(256)
NS_COLLECT_BEHAVIOR = 1 | 16 | 256

# Layout
WIN_WIDTH = 720
WIN_HEIGHT = 440
WIN_MARGIN_RIGHT = 36
WIN_MARGIN_BOTTOM = 110

# Typography sizes
HEADER_SIZE = 13
TRANSCRIPT_SIZE = 20
ARA_SIZE = 30

# Fade durations (seconds)
FADE_DURATION = 0.35

# Preferred fonts in order. First one that exists on the system wins.
SERIF_CANDIDATES = [
    "EBGaramond-Regular", "EB Garamond", "EBGaramond",
    "Garamond", "Hoefler Text", "Baskerville", "Palatino",
]
SERIF_BOLD_CANDIDATES = [
    "EBGaramond-Bold", "EB Garamond Bold", "EBGaramond-Medium",
    "Garamond Bold", "Hoefler Text Black", "Baskerville Bold",
    "Palatino Bold",
]


def _pick_font(candidates: list[str], size: float, bold: bool = False) -> NSFont:
    for name in candidates:
        f = NSFont.fontWithName_size_(name, size)
        if f is not None:
            return f
    return NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)


def _shadow(blur: float = 4.0, alpha: float = 0.92) -> NSShadow:
    s = NSShadow.alloc().init()
    s.setShadowColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, alpha))
    s.setShadowBlurRadius_(blur)
    s.setShadowOffset_((0, -1))
    return s


def _attr(text: str, font: NSFont, color: NSColor, shadow_blur: float = 4.0,
          kern: float = 0.3) -> NSAttributedString:
    attrs = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font,
        NSShadowAttributeName: _shadow(blur=shadow_blur),
        NSKernAttributeName: kern,
    }
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


class OverlayController(NSObject):
    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None

        self._queue: list[dict] = []
        self._lock = threading.Lock()

        # Resolve fonts once
        self.serif_regular = _pick_font(SERIF_CANDIDATES, TRANSCRIPT_SIZE, bold=False)
        self.serif_bold = _pick_font(SERIF_BOLD_CANDIDATES, ARA_SIZE, bold=True)
        self.header_font = _pick_font(SERIF_BOLD_CANDIDATES, HEADER_SIZE, bold=True)
        print(f"[overlay] fonts: regular={self.serif_regular.fontName()}, "
              f"bold={self.serif_bold.fontName()}", flush=True)

        # Window
        screen = NSScreen.mainScreen().frame()
        x = screen.size.width - WIN_WIDTH - WIN_MARGIN_RIGHT
        y = WIN_MARGIN_BOTTOM
        rect = NSMakeRect(x, y, WIN_WIDTH, WIN_HEIGHT)

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False,
        )
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setOpaque_(False)
        self.window.setHasShadow_(False)
        self.window.setLevel_(NS_SCREENSAVER_WINDOW_LEVEL)
        self.window.setIgnoresMouseEvents_(True)
        self.window.setCollectionBehavior_(NS_COLLECT_BEHAVIOR)

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIN_WIDTH, WIN_HEIGHT))
        content.setWantsLayer_(True)
        self.window.setContentView_(content)

        # Header
        self.header = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, WIN_HEIGHT - 36, WIN_WIDTH - 40, 22),
        )
        self._config_label(self.header)
        self.header.setAttributedStringValue_(
            _attr("●  LIVE  ·  ARA",
                  font=self.header_font,
                  color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.64, 0.78, 1.0, 0.95),
                  shadow_blur=3.0, kern=2.0),
        )
        content.addSubview_(self.header)

        # Transcript area
        transcript_h = 140
        self.transcript_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, WIN_HEIGHT - 48 - transcript_h, WIN_WIDTH - 40, transcript_h),
        )
        self._config_label(self.transcript_label, wraps=True)
        self.transcript_label.setWantsLayer_(True)
        self._set_text_internal(self.transcript_label, "Listening…",
                                font=self.serif_regular,
                                color=NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.80))
        content.addSubview_(self.transcript_label)

        # Ara answer area
        ara_h = WIN_HEIGHT - 48 - transcript_h - 40
        self.ara_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, 20, WIN_WIDTH - 40, ara_h),
        )
        self._config_label(self.ara_label, wraps=True)
        self.ara_label.setWantsLayer_(True)
        self._set_text_internal(self.ara_label, "",
                                font=self.serif_bold,
                                color=NSColor.whiteColor())
        content.addSubview_(self.ara_label)

        self.window.orderFrontRegardless()
        print("[overlay] shown", flush=True)

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1, self, "tick:", None, True,
        )

        threading.Thread(target=self._read_stdin, daemon=True).start()
        return self

    # ---- helpers ----
    @objc.python_method
    def _config_label(self, tf: NSTextField, wraps: bool = False):
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        if wraps:
            cell = tf.cell()
            cell.setWraps_(True)
            cell.setScrollable_(False)
            cell.setLineBreakMode_(0)  # word-wrap

    @objc.python_method
    def _set_text_internal(self, tf: NSTextField, text: str, font: NSFont,
                           color: NSColor, shadow_blur: float = 4.0):
        tf.setAttributedStringValue_(
            _attr(text, font=font, color=color, shadow_blur=shadow_blur),
        )

    @objc.python_method
    def _fade_to(self, tf: NSTextField, text: str, font: NSFont,
                 color: NSColor, shadow_blur: float = 4.0):
        """Fade the label to 0, swap text, fade back to 1."""
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(FADE_DURATION / 2.0)
        tf.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()

        def swap_and_in():
            self._set_text_internal(tf, text, font=font, color=color, shadow_blur=shadow_blur)
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(FADE_DURATION / 2.0)
            tf.animator().setAlphaValue_(1.0)
            NSAnimationContext.endGrouping()

        # Delay the swap until the fade-out finishes.
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            FADE_DURATION / 2.0, False, lambda _t: swap_and_in(),
        )

    # ---- stdin feeder ----
    @objc.python_method
    def _read_stdin(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                with self._lock:
                    self._queue.append(msg)
        except Exception:
            pass
        with self._lock:
            self._queue.append({"quit": True})

    # ---- main-thread tick ----
    def tick_(self, _timer):
        with self._lock:
            msgs = self._queue
            self._queue = []
        for msg in msgs:
            try:
                self._apply(msg)
            except Exception as e:
                print(f"[overlay] apply error: {e}", file=sys.stderr)

    @objc.python_method
    def _apply(self, msg: dict):
        if "transcript" in msg:
            txt = (msg["transcript"] or "").strip() or "Listening…"
            if len(txt) > 220:
                txt = "…" + txt[-220:]
            self._fade_to(
                self.transcript_label, txt,
                font=self.serif_regular,
                color=NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.82),
                shadow_blur=4.0,
            )
        if "ara" in msg:
            ara = (msg["ara"] or "").strip()
            if len(ara) > 360:
                ara = ara[:360] + "…"
            self._fade_to(
                self.ara_label, ara,
                font=self.serif_bold,
                color=NSColor.whiteColor(),
                shadow_blur=5.0,
            )
        if "show" in msg:
            self.window.orderFrontRegardless()
        if "hide" in msg:
            self.window.orderOut_(None)
        if "quit" in msg:
            NSApplication.sharedApplication().terminate_(None)


def main():
    NSApplication.sharedApplication()
    OverlayController.alloc().init()
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
