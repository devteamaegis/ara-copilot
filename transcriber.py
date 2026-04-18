"""Live audio capture + Whisper transcription.

Captures mic at the device's native sample rate (to avoid PortAudio errors
like -9986 / Core Audio -50 when the device can't do 16 kHz), then resamples
each chunk to 16 kHz for Whisper.
"""
import queue
import threading
import time

import numpy as np
import sounddevice as sd

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except Exception as _e:
    WHISPER_AVAILABLE = False
    _WHISPER_ERR = _e

TARGET_SR = 16000       # Whisper wants 16 kHz
CHUNK_SECONDS = 5
RATES_TO_TRY = [16000, 48000, 44100, 22050, 32000]


def _resample(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return x.astype(np.float32)
    new_len = int(round(len(x) * (dst_sr / src_sr)))
    if new_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0.0, len(x) - 1, num=new_len, dtype=np.float64)
    return np.interp(src_idx, np.arange(len(x)), x).astype(np.float32)


class Transcriber:
    def __init__(self, on_transcript=None):
        self.on_transcript = on_transcript
        self.running = False
        self.audio_queue: queue.Queue = queue.Queue()
        self.model = None
        self.recent_transcripts: list[dict] = []
        self._capture_thread = None
        self._process_thread = None
        self._capture_sr = TARGET_SR

    def _load_model(self):
        if not WHISPER_AVAILABLE:
            print(f"[transcriber] faster-whisper unavailable: {_WHISPER_ERR}")
            return
        if self.model is None:
            print("[transcriber] loading Whisper tiny.en ...")
            self.model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            print("[transcriber] model loaded")

    def start(self):
        if self.running:
            return
        self.running = True
        self._load_model()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()

    def stop(self):
        self.running = False

    def _pick_device_and_rate(self) -> tuple[int | None, int]:
        """Pick the best input device, in this order:
          1. An aggregate device the user set up for call capture
             ("Ara Capture" by convention) — hears BOTH sides of the call.
          2. BlackHole on its own — hears only the other side, but that's
             still better than nothing for a call.
          3. Built-in Mac mic — hears only the user (old behaviour).
          4. Anything non-bluetooth.

        Returns (device_index, sample_rate).
        """
        # Highest priority: user-configured aggregate devices that mix mic +
        # system audio so we hear both sides of a FaceTime/Zoom call.
        aggregate_keywords = ["ara capture", "ara input", "call capture",
                              "aggregate"]
        loopback_keywords = ["blackhole", "loopback", "soundflower"]
        preferred_keywords = ["macbook", "built-in", "internal"]
        avoid_keywords = ["airpods", "bluetooth", "hands-free"]
        chosen_idx = None
        chosen_name = None
        try:
            devices = sd.query_devices()

            def _find(keywords):
                for i, dev in enumerate(devices):
                    if dev.get("max_input_channels", 0) <= 0:
                        continue
                    name = (dev.get("name") or "").lower()
                    if any(k in name for k in keywords):
                        return i, dev.get("name")
                return None, None

            # 1. Aggregate capture device (mic + system audio) — best case.
            chosen_idx, chosen_name = _find(aggregate_keywords)
            # 2. Raw loopback driver (captures call audio, misses user).
            if chosen_idx is None:
                chosen_idx, chosen_name = _find(loopback_keywords)
                if chosen_idx is not None:
                    print("[transcriber] WARNING: capturing loopback only — "
                          "you'll hear the other person but not yourself. "
                          "Create an Aggregate Device called 'Ara Capture' "
                          "combining your mic + BlackHole to hear both sides.")
            # 3. Built-in mic (only hears the user).
            if chosen_idx is None:
                chosen_idx, chosen_name = _find(preferred_keywords)
                if chosen_idx is not None:
                    print("[transcriber] NOTE: using built-in mic only — will "
                          "NOT hear the other side of a call. Install "
                          "BlackHole + create an 'Ara Capture' Aggregate "
                          "Device (see README) to capture both sides.")
            # 4. Anything non-bluetooth.
            if chosen_idx is None:
                for i, dev in enumerate(devices):
                    if dev.get("max_input_channels", 0) <= 0:
                        continue
                    name = (dev.get("name") or "").lower()
                    if not any(k in name for k in avoid_keywords):
                        chosen_idx = i
                        chosen_name = dev.get("name")
                        break
            # Fall back to system default.
            if chosen_idx is None:
                info = sd.query_devices(kind="input")
                chosen_name = info.get("name")
        except Exception as e:
            print(f"[transcriber] query_devices failed: {e}")
        print(f"[transcriber] using input device: {chosen_name!r} (idx={chosen_idx})")
        for sr in RATES_TO_TRY:
            try:
                sd.check_input_settings(device=chosen_idx, samplerate=sr,
                                        channels=1, dtype="float32")
                return chosen_idx, sr
            except Exception:
                continue
        return chosen_idx, 48000

    def _capture_loop(self):
        dev_idx, sr = self._pick_device_and_rate()
        self._capture_sr = sr
        chunk_samples = sr * CHUNK_SECONDS
        buf = np.zeros(0, dtype=np.float32)

        def callback(indata, frames, time_info, status):
            nonlocal buf
            if not self.running:
                return
            audio = indata[:, 0].astype(np.float32).copy()
            buf = np.concatenate([buf, audio])
            while len(buf) >= chunk_samples:
                self.audio_queue.put(buf[:chunk_samples].copy())
                buf = buf[chunk_samples:]

        try:
            print(f"[transcriber] opening mic stream @ {sr} Hz on device {dev_idx}")
            with sd.InputStream(
                device=dev_idx,
                samplerate=sr,
                channels=1,
                dtype="float32",
                callback=callback,
                blocksize=int(sr * 0.5),
            ):
                print("[transcriber] mic stream open — listening")
                while self.running:
                    time.sleep(0.1)
        except Exception as e:
            print(f"[transcriber] audio capture error: {e}")
            self.running = False

    def _process_loop(self):
        while self.running:
            try:
                chunk = self.audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not WHISPER_AVAILABLE or self.model is None:
                continue
            if float(np.abs(chunk).mean()) < 0.002:
                continue  # silent
            # Resample to 16 kHz for Whisper
            try:
                chunk_16k = _resample(chunk, self._capture_sr, TARGET_SR)
            except Exception as e:
                print(f"[transcriber] resample error: {e}")
                continue
            try:
                segments, _info = self.model.transcribe(
                    chunk_16k, language="en", beam_size=1, vad_filter=True,
                )
                text = " ".join(s.text for s in segments).strip()
                if text:
                    self.recent_transcripts.append({"text": text, "timestamp": time.time()})
                    cutoff = time.time() - 120
                    self.recent_transcripts = [
                        t for t in self.recent_transcripts if t["timestamp"] > cutoff
                    ]
                    if self.on_transcript:
                        try:
                            self.on_transcript(text)
                        except Exception as cb_e:
                            print(f"[transcriber] callback error: {cb_e}")
            except Exception as e:
                print(f"[transcriber] transcription error: {e}")

    def get_recent_text(self, seconds: int = 30) -> str:
        cutoff = time.time() - seconds
        return " ".join(t["text"] for t in self.recent_transcripts if t["timestamp"] > cutoff)


if __name__ == "__main__":
    def printer(t):
        print(">", t)
    tr = Transcriber(on_transcript=printer)
    tr.start()
    print("Recording 30s...")
    time.sleep(30)
    tr.stop()
    print("Final:", tr.get_recent_text(60))
