import tkinter as tk
import threading
import queue
import wave
import tempfile
import os
import collections
import struct
import pyaudio
import httpx
from concurrent.futures import ThreadPoolExecutor

# ── Audio ─────────────────────────────────────────────────────────────────────
CHUNK = 512
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.0
MAX_UTTERANCE_SEC = 12
PREROLL_SEC = 0.35

# ── Latency ───────────────────────────────────────────────────────────────────
STREAM_INTERVAL = 1.2  # ↑ from 0.8 — fewer mid-speech refreshes
MAX_PARALLEL = 4

# ── Sarvam AI ─────────────────────────────────────────────────────────────────
SARVAM_API_KEY = "sk_os7rfor3_g5QqBvTGKCEbu8kjm9YjkLCX"
SARVAM_ENDPOINT = "https://api.sarvam.ai/speech-to-text"
SARVAM_MODEL = "saaras:v3"
SARVAM_MODE = "translit"  # Hindi/Hinglish → Roman script (oye sun, bhai, kya kar rha)
SARVAM_LANGUAGE = "hi-IN"

# ── Anti-flicker diff threshold ───────────────────────────────────────────────
MIN_NEW_WORDS_TO_UPDATE = 2

# ── Glasses-style subtitle UI ─────────────────────────────────────────────────
BAR_WIDTH = 700
BAR_HEIGHT = 100
BAR_PADDING_X = 28
BAR_PADDING_Y = 14
CORNER_RADIUS = 18

START_X = None  # None = auto-centre horizontally
START_Y = None  # None = auto bottom-ish

BG_COLOR = "#0f0f0f"
BG_ALPHA = 0.82
LINE1_COLOR = "#6b7280"  # muted grey — previous line
LINE2_COLOR = "#ffffff"  # white bold — current line
LIVE_COLOR = "#a5b4fc"  # indigo — while transcribing
CURSOR_CHAR = "▌"

FONT_FAMILY = "Segoe UI"  # macOS: "SF Pro Display" · Linux: "Ubuntu"
FONT_SIZE_LINE1 = 13
FONT_SIZE_LINE2 = 16
FONT_WEIGHT = "bold"

FADE_DELAY_MS = 3200  # ms before the greyed line clears
MIN_AUDIO_SEC = 0.35
WORD_REVEAL_MS = 0  # ms between word reveals (0 = instant)

_TRANSPARENT = "#010101"  # chroma key for window transparency

# ── Helpers ───────────────────────────────────────────────────────────────────

def rms(data: bytes) -> float:
    count = len(data) // 2
    if not count:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return (sum(s * s for s in shorts) / count) ** 0.5

def frames_to_wav(frames: list) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    return tmp.name

def transcribe(frames: list) -> str:
    if not SARVAM_API_KEY:
        return "[set SARVAM_API_KEY env var]"
    if len(frames) * CHUNK / RATE < MIN_AUDIO_SEC:
        return ""
    path = frames_to_wav(frames)
    try:
        with open(path, "rb") as f:
            resp = httpx.post(
                SARVAM_ENDPOINT,
                headers={"api-subscription-key": SARVAM_API_KEY},
                data={
                    "model": SARVAM_MODEL,
                    "mode": SARVAM_MODE,
                    "language_code": SARVAM_LANGUAGE
                },
                files={"file": ("audio.wav", f, "audio/wav")},
                timeout=15,
            )
        resp.raise_for_status()
        return resp.json().get("transcript", "").strip()
    except Exception:
        return ""
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass

def word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0

def is_meaningful_update(current: str, incoming: str) -> bool:
    """
    Return True only if incoming text is worth displaying.
    Suppresses micro-updates that barely differ from what's shown,
    which is the main cause of flickering / broken flow.
    """
    cur_words = word_count(current)
    new_words = word_count(incoming)

    # Always accept if current is empty
    if cur_words == 0:
        return True

    # Accept only if we gained enough new words
    if new_words - cur_words >= MIN_NEW_WORDS_TO_UPDATE:
        return True

    # Also accept if it's a completely different phrase (speaker changed mid-stream)
    cur_set = set(current.lower().split())
    new_set = set(incoming.lower().split())
    overlap = len(cur_set & new_set) / max(len(cur_set), 1)
    if overlap < 0.3 and new_words >= 2:
        return True

    return False

# ── Recorder ────────────────────────────────────────────────────────────────────

class AudioRecorder(threading.Thread):
    def __init__(self, q: queue.Queue):
        super().__init__(daemon=True)
        self.q = q
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        pa = pyaudio.PyAudio()
        stream = pa.open(format=FORMAT, channels=CHANNELS,
                         rate=RATE, input=True,
                         frames_per_buffer=CHUNK)
        preroll = collections.deque(maxlen=int(RATE / CHUNK * PREROLL_SEC))
        sil_needed = int(RATE / CHUNK * SILENCE_DURATION)
        max_chunks = int(RATE / CHUNK * MAX_UTTERANCE_SEC)
        stream_every = int(RATE / CHUNK * STREAM_INTERVAL)
        utterance = []
        silent_cnt = 0
        speaking = False
        since_stream = 0

        while self.running:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                continue
            level = rms(data)
            if level > SILENCE_THRESHOLD:
                if not speaking:
                    utterance = list(preroll) + [data]
                    speaking = True
                else:
                    utterance.append(data)
                    silent_cnt = 0
                    since_stream += 1
                if since_stream >= stream_every:
                    self.q.put((list(utterance), False))
                    since_stream = 0
                if len(utterance) >= max_chunks:
                    self.q.put((list(utterance), True))
                    utterance = []
                    speaking = False
                    since_stream = 0
            elif speaking:
                utterance.append(data)
                silent_cnt += 1
                if silent_cnt >= sil_needed:
                    self.q.put((list(utterance), True))
                    utterance = []
                    speaking = False
                    silent_cnt = 0
                else:
                    preroll.append(data)
            else:
                preroll.append(data)

        stream.stop_stream()
        stream.close()
        pa.terminate()

# ── Transcription worker ────────────────────────────────────────────────

class TranscriptionWorker(threading.Thread):
    def __init__(self, audio_q: queue.Queue, text_q: queue.Queue):
        super().__init__(daemon=True)
        self.audio_q = audio_q
        self.text_q = text_q
        self.running = True
        self._seq = 0
        self._lock = threading.Lock()

    def stop(self):
        self.running = False

    def _handle(self, frames, is_final, seq):
        text = transcribe(frames)
        if text:
            self.text_q.put(("final" if is_final else "live", seq, text))

    def run(self):
        pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL)
        while self.running:
            try:
                frames, is_final = self.audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                self._seq += 1
                seq = self._seq
            pool.submit(self._handle, frames, is_final, seq)
        pool.shutdown(wait=False)

# ── Glasses overlay ───────────────────────────────────────────────────────
class GlassesOverlay:
    """
    Subtitle pill — Hearview-style.
    """
    def __init__(self, root: tk.Tk, text_q: queue.Queue):
        self.root = root
        self.text_q = text_q

        self._line2_text = ""  # what's currently confirmed on line 2
        self._line2_live = False
        self._fade_job = None

        # word-reveal state
        self._reveal_words = []
        self._reveal_idx = 0
        self._reveal_job = None
        self._reveal_live = False

        # last displayed live text (for diff check)
        self._last_live_text = ""

        self._build_ui()
        self._poll()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        sx = START_X if START_X is not None else (sw - BAR_WIDTH) // 2
        sy = START_Y if START_Y is not None else sh - BAR_HEIGHT - 80

        r.overrideredirect(True)
        r.geometry(f"{BAR_WIDTH}x{BAR_HEIGHT}+{sx}+{sy}")
        r.attributes("-topmost", True)
        r.attributes("-alpha", BG_ALPHA)
        r.configure(bg=_TRANSPARENT)
        try:
            r.attributes("-transparentcolor", _TRANSPARENT)
        except Exception:
            pass
        try:
            r.attributes("-transparent", True)
        except Exception:
            pass

        self.canvas = tk.Canvas(r, width=BAR_WIDTH, height=BAR_HEIGHT,
                                bg=_TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._draw_pill()

        self.lbl1 = tk.Label(r, text="", bg=BG_COLOR, fg=LINE1_COLOR,
                             font=(FONT_FAMILY, FONT_SIZE_LINE1),
                             anchor="w", justify="left",
                             wraplength=BAR_WIDTH - BAR_PADDING_X * 2)
        self.canvas.create_window(BAR_PADDING_X, BAR_PADDING_Y,
                                  window=self.lbl1, anchor="nw")

        self.lbl2 = tk.Label(r, text="", bg=BG_COLOR, fg=LINE2_COLOR,
                             font=(FONT_FAMILY, FONT_SIZE_LINE2, FONT_WEIGHT),
                             anchor="w", justify="left",
                             wraplength=BAR_WIDTH - BAR_PADDING_X * 2)
        self.canvas.create_window(BAR_PADDING_X, BAR_PADDING_Y + FONT_SIZE_LINE1 + 10,
                                  window=self.lbl2, anchor="nw")

        # close button
        self._close = tk.Label(r, text="×", bg=BG_COLOR, fg="#333",
                               font=(FONT_FAMILY, 11), cursor="hand2")
        self.canvas.create_window(BAR_WIDTH - 16, 8, anchor="ne", window=self._close)
        self._close.bind("<Button-1>", lambda _: r.destroy())
        self._close.bind("<Enter>", lambda _: self._close.config(fg="#888"))
        self._close.bind("<Leave>", lambda _: self._close.config(fg="#333"))

        for w in (self.canvas, self.lbl1, self.lbl2):
            w.bind("<ButtonPress-1>", self._start_move)
            w.bind("<B1-Motion>", self._do_move)
            w.bind("<Double-Button-1>", self._snap_position)

        r.bind("<Escape>", lambda _: r.destroy())

    # ── Draw pill ─────────────────────────────────────────────────────────────
    def _draw_pill(self):
        x1, y1, x2, y2, rr = 0, 0, BAR_WIDTH, BAR_HEIGHT, CORNER_RADIUS
        c = self.canvas
        c.create_arc(x1, y1, x1 + 2 * rr, y1 + 2 * rr, start=90, extent=90,
                     fill=BG_COLOR, outline=BG_COLOR)
        c.create_arc(x2 - 2 * rr, y1, x2, y1 + 2 * rr, start=0, extent=90,
                     fill=BG_COLOR, outline=BG_COLOR)
        c.create_arc(x1, y2 - 2 * rr, x1 + 2 * rr, y2, start=180, extent=90,
                     fill=BG_COLOR, outline=BG_COLOR)
        c.create_arc(x2 - 2 * rr, y2 - 2 * rr, x2, y2, start=270, extent=90,
                     fill=BG_COLOR, outline=BG_COLOR)
        c.create_rectangle(x1 + rr, y1, x2 - rr, y2, fill=BG_COLOR, outline=BG_COLOR)
        c.create_rectangle(x1, y1 + rr, x2, y2 - rr, fill=BG_COLOR, outline=BG_COLOR)

    # ── Drag & snap ───────────────────────────────────────────────────────────
    def _start_move(self, e):
        self._ox = self.root.winfo_x()
        self._oy = self.root.winfo_y()
        self._dx = e.x_root
        self._dy = e.y_root

    def _do_move(self, e):
        self.root.geometry(
            f"+{self._ox + e.x_root - self._dx}+{self._oy + e.y_root - self._dy}"
        )

    def _snap_position(self, e):
        sw = self.root.winfo_screenwidth()
        cur = self.root.winfo_x()
        positions = [40, (sw - BAR_WIDTH) // 2, sw - BAR_WIDTH - 40]
        closest = min(positions, key=lambda p: abs(p - cur))
        nxt = positions[(positions.index(closest) + 1) % len(positions)]
        self.root.geometry(f"+{nxt}+{self.root.winfo_y()}")

    # ── Word reveal ───────────────────────────────────────────────────────────
    def _cancel_reveal(self):
        if self._reveal_job:
            self.root.after_cancel(self._reveal_job)
            self._reveal_job = None

    def _reveal_next_word(self):
        if self._reveal_idx >= len(self._reveal_words):
            self._reveal_job = None
            return
        shown = " ".join(self._reveal_words[:self._reveal_idx + 1])
        cursor = (" " + CURSOR_CHAR) if self._reveal_live else ""
        color = LIVE_COLOR if self._reveal_live else LINE2_COLOR
        self.lbl2.config(text=shown + cursor, fg=color)
        self._reveal_idx += 1
        if self._reveal_idx < len(self._reveal_words):
            self._reveal_job = self.root.after(WORD_REVEAL_MS, self._reveal_next_word)
        else:
            self._reveal_job = None

    # ── Set line2 ─────────────────────────────────────────────────────────────
    def _set_line2(self, text: str, live: bool, force: bool = False):
        """
        Update line 2 immediately when live=True.
        If live=True, always show the text without anti-flicker checks.
        """
        self._last_live_text = text  # Track for diff checks
        color = LIVE_COLOR if live else LINE2_COLOR
        cursor = (" " + CURSOR_CHAR) if live else ""
        self.lbl2.config(text=text + cursor, fg=color)

    # ── Caption logic ─────────────────────────────────────────────────────────
    def _push_line1(self, text: str):
        if self._fade_job:
            self.root.after_cancel(self._fade_job)
        self.lbl1.config(text=text)
        self._fade_job = self.root.after(FADE_DELAY_MS,
                                         lambda: self.lbl1.config(text=""))

    def _on_live(self, text: str):
        self._set_line2(text, live=True)
        self._line2_live = True

    def _on_final(self, text: str):
        # Push whatever was on line 2 to the grey line above
        if self._line2_text:
            self._push_line1(self._line2_text)
        # Show final text immediately (force=True bypasses diff check)
        self._set_line2(text, live=False, force=True)
        self._line2_text = text
        self._line2_live = False
        self._last_live_text = ""  # reset diff baseline for next utterance

    # ── Poll ──────────────────────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                kind, seq, text = self.text_q.get_nowait()
                if kind == "live":
                    self._on_live(text)
                elif kind == "final":
                    self._on_final(text)
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    if not SARVAM_API_KEY:
        print("⚠ SARVAM_API_KEY not set.")
        print(" Get your key → https://dashboard.sarvam.ai/")
        print(" macOS/Linux : export SARVAM_API_KEY=your-key")
        print(" Windows PS  : $env:SARVAM_API_KEY='your-key'")
        print(" Then re-run : python main.py\n")

    audio_q: queue.Queue = queue.Queue()
    text_q: queue.Queue = queue.Queue()

    recorder = AudioRecorder(audio_q)
    worker = TranscriptionWorker(audio_q, text_q)
    recorder.start()
    worker.start()

    root = tk.Tk()
    GlassesOverlay(root, text_q)

    def on_close():
        recorder.stop()
        worker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    print("HeadphoneMode v5 — Glasses Mode [translit · anti-flicker]")
    print("Drag to move · Double-click to snap L / C / R · Esc to quit\n")
    root.mainloop()


if __name__ == "__main__":
    main()