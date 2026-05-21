from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class VoiceBackend(Enum):
    SYSTEM = "system"
    OPENAI = "openai"
    PYTTSX3 = "pyttsx3"
    WHISPER = "whisper"


@dataclass
class VoiceResult:
    text: str = ""
    audio_path: str = ""
    duration: float = 0.0
    error: str = ""


class VoiceEngine:
    def __init__(self, tts_backend: VoiceBackend = VoiceBackend.SYSTEM, stt_backend: VoiceBackend = VoiceBackend.WHISPER):
        self.tts_backend = tts_backend
        self.stt_backend = stt_backend
        self._openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")

    def speak(self, text: str, output_path: Optional[str] = None) -> VoiceResult:
        if self.tts_backend == VoiceBackend.OPENAI and self._openai_api_key:
            return self._openai_tts(text, output_path)
        elif self.tts_backend == VoiceBackend.PYTTSX3:
            return self._pyttsx3_tts(text)
        else:
            return self._system_tts(text, output_path)

    def listen(self, audio_input: Optional[str] = None, duration: int = 5) -> VoiceResult:
        if self.stt_backend == VoiceBackend.WHISPER:
            return self._whisper_stt(audio_input)
        elif self.stt_backend == VoiceBackend.OPENAI and self._openai_api_key:
            return self._openai_stt(audio_input)
        else:
            return VoiceResult(text="[Voice input not available. Install whisper or set OPENAI_API_KEY]", error="No STT backend available")

    def _system_tts(self, text: str, output_path: Optional[str] = None) -> VoiceResult:
        try:
            temp = output_path or str(Path(tempfile.mkdtemp()) / "speech.wav")

            if os.name == "nt":
                import clr  # type: ignore
                clr.AddReference("System.Speech")
                from System.Speech.Synthesis import SpeechSynthesizer  # type: ignore
                synth = SpeechSynthesizer()
                synth.SetOutputToWaveFile(temp)
                synth.Speak(text)
                synth.Dispose()
            else:
                if not output_path:
                    subprocess.run(["say", text], check=False, timeout=30)
                    return VoiceResult(text=text, audio_path="", duration=0.0)

            return VoiceResult(text=text, audio_path=temp, duration=len(text) * 0.06)
        except Exception as e:
            return VoiceResult(text=text, error=str(e))

    def _openai_tts(self, text: str, output_path: Optional[str] = None) -> VoiceResult:
        try:
            import httpx
            out = output_path or str(Path(tempfile.mkdtemp()) / "speech.mp3")
            response = httpx.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self._openai_api_key}"},
                json={"model": "tts-1", "input": text, "voice": "alloy"},
                timeout=30,
            )
            if response.status_code == 200:
                Path(out).write_bytes(response.content)
                return VoiceResult(text=text, audio_path=out, duration=len(text) * 0.06)
            return VoiceResult(text=text, error=f"OpenAI TTS error: {response.status_code}")
        except Exception as e:
            return VoiceResult(text=text, error=str(e))

    def _pyttsx3_tts(self, text: str) -> VoiceResult:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return VoiceResult(text=text, duration=len(text) * 0.06)
        except Exception as e:
            return VoiceResult(text=text, error=str(e))

    def _whisper_stt(self, audio_input: Optional[str] = None) -> VoiceResult:
        try:
            import whisper
            model = whisper.load_model("base")
            if audio_input:
                result = model.transcribe(audio_input)
            else:
                import sounddevice as sd
                import numpy as np
                fs = 16000
                recording = sd.rec(int(5 * fs), samplerate=fs, channels=1)
                sd.wait()
                result = model.transcribe(np.squeeze(recording))
            return VoiceResult(text=result["text"].strip(), duration=result.get("duration", 0.0))
        except ImportError:
            return VoiceResult(text="", error="whisper not installed. pip install openai-whisper")
        except Exception as e:
            return VoiceResult(text="", error=str(e))

    def _openai_stt(self, audio_input: Optional[str] = None) -> VoiceResult:
        try:
            import httpx
            if not audio_input:
                return VoiceResult(text="", error="Audio file required for OpenAI STT")

            with open(audio_input, "rb") as f:
                response = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._openai_api_key}"},
                    files={"file": (Path(audio_input).name, f, "audio/wav")},
                    data={"model": "whisper-1"},
                    timeout=30,
                )
            if response.status_code == 200:
                text = response.json().get("text", "")
                return VoiceResult(text=text)
            return VoiceResult(text="", error=f"OpenAI STT error: {response.status_code}")
        except Exception as e:
            return VoiceResult(text="", error=str(e))

    def is_available(self) -> bool:
        engines = []
        if self._openai_api_key:
            engines.append("openai")
        try:
            import pyttsx3  # noqa: F401
            engines.append("pyttsx3")
        except ImportError:
            pass
        try:
            import whisper  # noqa: F401
            engines.append("whisper")
        except ImportError:
            pass
        return len(engines) > 0
