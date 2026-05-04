"""Horizon Orchestra — Media Pipeline.

Comprehensive media processing toolkit that wraps ffmpeg, yt-dlp,
image generation (DALL-E 3 / FLUX / Stable Diffusion), video generation
(Veo / Sora / Runway), text-to-speech (OpenAI TTS / ElevenLabs),
speech-to-text (Whisper), and image processing (Pillow / ImageMagick).

Quick start::

    from orchestra.media import FFmpegRunner, YTDLPDownloader, ImageGenerator
    from orchestra.media import VideoGenerator, TTSEngine, STTEngine, ImageProcessor

    runner = FFmpegRunner()
    info = await runner.get_media_info("video.mp4")

    gen = ImageGenerator()
    result = await gen.generate("a sunset over mountains", model="dall-e-3")
"""

from __future__ import annotations

from .ffmpeg import FFmpegRunner, MediaInfo
from .ytdlp import YTDLPDownloader, VideoInfo, DownloadResult, FormatInfo
from .image_gen import ImageGenerator, ImageResult
from .video_gen import VideoGenerator, VideoResult
from .tts import TTSEngine, AudioResult
from .stt import STTEngine, TranscriptResult
from .image_processing import ImageProcessor

__all__ = [
    # ffmpeg
    "FFmpegRunner",
    "MediaInfo",
    # yt-dlp
    "YTDLPDownloader",
    "VideoInfo",
    "DownloadResult",
    "FormatInfo",
    # Image generation
    "ImageGenerator",
    "ImageResult",
    # Video generation
    "VideoGenerator",
    "VideoResult",
    # Text-to-speech
    "TTSEngine",
    "AudioResult",
    # Speech-to-text
    "STTEngine",
    "TranscriptResult",
    # Image processing
    "ImageProcessor",
]
