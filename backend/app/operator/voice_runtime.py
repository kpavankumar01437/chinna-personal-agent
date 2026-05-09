from __future__ import annotations

import asyncio
import queue
import re
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .schemas import OperatorMode


CommandCallback = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass
class VoiceRuntimeStatus:
    enabled: bool
    listening: bool
    speaking: bool
    last_transcript: str
    last_reply: str
    last_error: str
    processed_chunks: int
    wake_phrase: str
    mode: str


class LocalSpeaker:
    def __init__(self):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._speaking = False
        self._last_error = ""

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def last_error(self) -> str:
        return self._last_error

    def speak(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        if not self._thread or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        self._queue.put(clean)

    def stop(self) -> None:
        self._queue.put(None)

    def _run(self) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 172)
            while True:
                text = self._queue.get()
                if text is None:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    break
                try:
                    self._speaking = True
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    self._last_error = f"Local TTS failed safely: {exc}"
                finally:
                    self._speaking = False
        except Exception as exc:
            self._last_error = f"Local TTS unavailable: {exc}"
            self._speaking = False


class VoiceRuntime:
    def __init__(
        self,
        operator: Any,
        command_callback: CommandCallback,
        speaker: LocalSpeaker,
        sample_rate: int = 16000,
        chunk_seconds: int = 2,
    ):
        self.operator = operator
        self.command_callback = command_callback
        self.speaker = speaker
        self.sample_rate = sample_rate
        self.chunk_seconds = chunk_seconds
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_transcript = ""
        self._last_reply = ""
        self._last_error = ""
        self._processed_chunks = 0
        self._awake_until = 0.0
        self._warm_thread: threading.Thread | None = None

    def start(self) -> VoiceRuntimeStatus:
        with self._lock:
            self.operator.sleep()
            self._awake_until = 0.0
            self._enabled = True
            self._warm_transcriber()
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
        return self.status()

    def _warm_transcriber(self) -> None:
        if self._warm_thread and self._warm_thread.is_alive():
            return

        def warm() -> None:
            try:
                from .service import _get_whisper_model

                _get_whisper_model()
            except Exception as exc:
                self._last_error = f"STT warm-up failed safely: {exc}"

        self._warm_thread = threading.Thread(target=warm, daemon=True)
        self._warm_thread.start()

    def stop(self) -> VoiceRuntimeStatus:
        with self._lock:
            self._enabled = False
        return self.status()

    def status(self) -> VoiceRuntimeStatus:
        session = self.operator.current_session()
        return VoiceRuntimeStatus(
            enabled=self._enabled,
            listening=bool(self._thread and self._thread.is_alive() and self._enabled),
            speaking=self.speaker.speaking,
            last_transcript=self._last_transcript,
            last_reply=self._last_reply,
            last_error=self._last_error or self.speaker.last_error,
            processed_chunks=self._processed_chunks,
            wake_phrase="Hey Chinna WakeUp",
            mode=session["mode"],
        )

    def _loop(self) -> None:
        while self._enabled:
            try:
                if self.speaker.speaking:
                    time.sleep(0.2)
                    continue
                transcript = self._record_and_transcribe()
                if not transcript:
                    continue
                self._last_transcript = transcript
                should_process = self._should_process(transcript)
                if not should_process:
                    continue
                result = asyncio.run(self.command_callback(transcript))
                reply = result.get("reply") or result.get("message") or ""
                self._last_reply = reply
                if reply:
                    self.speaker.speak(reply)
                    time.sleep(0.6)
            except Exception as exc:
                self._last_error = f"Voice listener failed safely: {exc}"

    def _should_process(self, transcript: str) -> bool:
        lowered = transcript.lower().strip()
        if _has_wake_phrase(lowered):
            self._awake_until = time.monotonic() + 45
            return True
        if _is_sleep_phrase(lowered):
            self._awake_until = 0.0
            return True
        session_mode = self.operator.current_session()["mode"]
        if session_mode in {OperatorMode.LISTENING.value, OperatorMode.WAITING_FOR_APPROVAL.value}:
            self._awake_until = time.monotonic() + 30
            return True
        if time.monotonic() <= self._awake_until:
            self._awake_until = time.monotonic() + 30
            return True
        return False

    def _record_and_transcribe(self) -> str:
        import numpy as np
        import sounddevice as sd

        frames = int(self.sample_rate * self.chunk_seconds)
        recording = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
        sd.wait()
        self._processed_chunks += 1
        if float(np.max(np.abs(recording))) < 0.012:
            return ""
        wav_path = self._write_temp_wav(recording)
        try:
            from .service import _get_whisper_model

            model = _get_whisper_model()
            segments, _info = model.transcribe(
                str(wav_path),
                vad_filter=True,
                beam_size=1,
                best_of=1,
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass

    def _write_temp_wav(self, recording: Any) -> Path:
        import numpy as np

        self.operator.vault.ensure()
        temp_dir = self.operator.vault.root / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        path = temp_dir / f"wake-listener-{_stamp()}.wav"
        clipped = np.clip(recording.reshape(-1), -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm.tobytes())
        return path


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _normalize(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    normalized = normalized.replace("wake up", "wakeup")
    normalized = normalized.replace("china", "chinna")
    normalized = normalized.replace("tina", "chinna")
    normalized = normalized.replace("chena", "chinna")
    return re.sub(r"\s+", " ", normalized).strip()


def _has_wake_phrase(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        phrase in normalized
        for phrase in [
            "hey chinna wakeup",
            "ok chinna wakeup",
            "okay chinna wakeup",
            "chinna wakeup",
        ]
    )


def _is_sleep_phrase(text: str) -> bool:
    normalized = _normalize(text)
    return normalized in {"sleep", "go to sleep", "go sleep"}
