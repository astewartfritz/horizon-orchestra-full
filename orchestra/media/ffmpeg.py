"""Horizon Orchestra — FFmpeg Wrapper.

Async interface around the ``ffmpeg`` CLI for video/audio conversion,
trimming, merging, thumbnail extraction, concatenation, and subtitle
embedding.  Every call goes through ``asyncio.create_subprocess_exec``
so the event loop is never blocked.

Usage::

    from orchestra.media.ffmpeg import FFmpegRunner

    runner = FFmpegRunner()
    info = await runner.get_media_info("input.mp4")
    await runner.convert("input.mp4", "output.webm", fmt="webm")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = [
    "FFmpegRunner",
    "MediaInfo",
    "FFmpegNotFoundError",
]

log = logging.getLogger("orchestra.media.ffmpeg")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg / ffprobe is not on $PATH."""


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg command exits non-zero."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StreamInfo:
    """Metadata about a single stream inside a media container."""

    index: int = 0
    codec_name: str = ""
    codec_type: str = ""  # "video" | "audio" | "subtitle"
    width: int = 0
    height: int = 0
    duration: float = 0.0
    bit_rate: int = 0
    sample_rate: int = 0
    channels: int = 0
    frame_rate: float = 0.0


@dataclass
class MediaInfo:
    """Aggregate metadata for a media file."""

    path: str = ""
    duration: float = 0.0
    codec: str = ""
    resolution: str = ""
    bitrate: int = 0
    format_name: str = ""
    size_bytes: int = 0
    streams: list[StreamInfo] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        for s in self.streams:
            if s.codec_type == "video":
                return s.width
        return 0

    @property
    def height(self) -> int:
        for s in self.streams:
            if s.codec_type == "video":
                return s.height
        return 0

    @property
    def has_audio(self) -> bool:
        return any(s.codec_type == "audio" for s in self.streams)

    @property
    def has_video(self) -> bool:
        return any(s.codec_type == "video" for s in self.streams)


# ---------------------------------------------------------------------------
# FFmpegRunner
# ---------------------------------------------------------------------------

class FFmpegRunner:
    """Async wrapper around the ``ffmpeg`` / ``ffprobe`` CLI tools.

    Parameters
    ----------
    workspace:
        Directory where intermediate and output files are written.
        Defaults to ``$ORCHESTRA_WORKSPACE/ffmpeg`` or ``/tmp/orchestra_media/ffmpeg``.
    ffmpeg_path:
        Override path to the ``ffmpeg`` binary.
    ffprobe_path:
        Override path to the ``ffprobe`` binary.
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "ffmpeg"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self._ffprobe = ffprobe_path or shutil.which("ffprobe") or "ffprobe"

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    async def _check_installed(self) -> None:
        """Verify that ffmpeg is available on the system."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ffmpeg, "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise FFmpegNotFoundError(
                    "ffmpeg is installed but returned a non-zero exit code.  "
                    "Check your ffmpeg installation."
                )
        except FileNotFoundError:
            raise FFmpegNotFoundError(
                "ffmpeg is not installed or not found on $PATH.  "
                "Install it with: apt-get install ffmpeg  (Linux) / "
                "brew install ffmpeg  (macOS)"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _output_path(self, suffix: str, name: str | None = None) -> Path:
        """Generate a unique output path inside the workspace."""
        fname = name or f"{uuid.uuid4().hex[:12]}{suffix}"
        return self.workspace / fname

    async def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> tuple[bytes, bytes]:
        """Execute an ffmpeg/ffprobe command asynchronously."""
        log.debug("Running: %s", " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if check and proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:2000]
            raise FFmpegError(
                f"ffmpeg exited with code {proc.returncode}: {err_msg}"
            )
        return stdout, stderr

    async def _run_ffmpeg(self, *args: str, check: bool = True) -> tuple[bytes, bytes]:
        """Run ffmpeg with the given arguments."""
        await self._check_installed()
        return await self._run(self._ffmpeg, *args, check=check)

    async def _run_ffprobe(self, *args: str, check: bool = True) -> tuple[bytes, bytes]:
        """Run ffprobe with the given arguments."""
        await self._check_installed()
        return await self._run(self._ffprobe, *args, check=check)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_media_info(self, path: str | Path) -> MediaInfo:
        """Probe a media file and return structured metadata.

        Parameters
        ----------
        path:
            Path to the input media file.

        Returns
        -------
        MediaInfo
            Parsed metadata including duration, codec, resolution, bitrate.
        """
        path = str(path)
        stdout, _ = await self._run_ffprobe(
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            path,
        )
        data = json.loads(stdout.decode())
        fmt = data.get("format", {})
        streams_raw = data.get("streams", [])

        streams: list[StreamInfo] = []
        video_codec = ""
        resolution = ""
        for s in streams_raw:
            si = StreamInfo(
                index=s.get("index", 0),
                codec_name=s.get("codec_name", ""),
                codec_type=s.get("codec_type", ""),
                width=int(s.get("width", 0)),
                height=int(s.get("height", 0)),
                duration=float(s.get("duration", 0)),
                bit_rate=int(s.get("bit_rate", 0)),
                sample_rate=int(s.get("sample_rate", 0)),
                channels=int(s.get("channels", 0)),
            )
            # Parse frame rate
            r_frame = s.get("r_frame_rate", "0/1")
            if "/" in r_frame:
                num, den = r_frame.split("/")
                si.frame_rate = float(num) / float(den) if float(den) else 0.0
            else:
                si.frame_rate = float(r_frame)
            streams.append(si)

            if s.get("codec_type") == "video" and not video_codec:
                video_codec = s.get("codec_name", "")
                w, h = s.get("width", 0), s.get("height", 0)
                if w and h:
                    resolution = f"{w}x{h}"

        return MediaInfo(
            path=path,
            duration=float(fmt.get("duration", 0)),
            codec=video_codec or fmt.get("format_name", ""),
            resolution=resolution,
            bitrate=int(fmt.get("bit_rate", 0)),
            format_name=fmt.get("format_name", ""),
            size_bytes=int(fmt.get("size", 0)),
            streams=streams,
            raw=data,
        )

    async def convert(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        fmt: str = "mp4",
        codec: str | None = None,
        bitrate: str | None = None,
        audio_codec: str | None = None,
        extra_args: Sequence[str] = (),
    ) -> Path:
        """Convert a media file to a different format/codec.

        Parameters
        ----------
        input_path:
            Source file.
        output_path:
            Destination file.  Auto-generated if *None*.
        fmt:
            Output container format (``mp4``, ``webm``, ``mkv``, ``mp3``, …).
        codec:
            Video codec (``libx264``, ``libvpx-vp9``, ``copy``, …).
        bitrate:
            Target bitrate string (``"2M"``, ``"128k"``).
        audio_codec:
            Audio codec override (``aac``, ``libopus``, ``copy``).
        extra_args:
            Additional arguments passed verbatim to ffmpeg.

        Returns
        -------
        Path
            The output file path.
        """
        out = Path(output_path) if output_path else self._output_path(f".{fmt}")
        cmd: list[str] = ["-y", "-i", str(input_path)]

        if codec:
            cmd.extend(["-c:v", codec])
        if audio_codec:
            cmd.extend(["-c:a", audio_codec])
        if bitrate:
            cmd.extend(["-b:v", bitrate])
        cmd.extend(extra_args)
        cmd.append(str(out))

        await self._run_ffmpeg(*cmd)
        log.info("Converted %s → %s", input_path, out)
        return out

    async def extract_audio(
        self,
        video_path: str | Path,
        output_path: str | Path | None = None,
        *,
        audio_format: str = "mp3",
        bitrate: str = "192k",
    ) -> Path:
        """Extract the audio track from a video file.

        Parameters
        ----------
        video_path:
            Source video.
        output_path:
            Destination audio file.
        audio_format:
            Output audio format (``mp3``, ``wav``, ``aac``, ``opus``).
        bitrate:
            Audio bitrate.

        Returns
        -------
        Path
            Path to the extracted audio file.
        """
        out = Path(output_path) if output_path else self._output_path(f".{audio_format}")
        await self._run_ffmpeg(
            "-y", "-i", str(video_path),
            "-vn",
            "-acodec", {"mp3": "libmp3lame", "aac": "aac", "opus": "libopus", "wav": "pcm_s16le"}.get(audio_format, audio_format),
            "-b:a", bitrate,
            str(out),
        )
        log.info("Extracted audio → %s", out)
        return out

    async def merge_audio_video(
        self,
        audio_path: str | Path,
        video_path: str | Path,
        output_path: str | Path | None = None,
        *,
        shortest: bool = True,
    ) -> Path:
        """Merge separate audio and video tracks into a single file.

        Parameters
        ----------
        audio_path:
            Path to the audio file.
        video_path:
            Path to the video file.
        output_path:
            Destination.  Auto-generated if *None*.
        shortest:
            End the output when the shorter stream ends.

        Returns
        -------
        Path
            Merged output path.
        """
        out = Path(output_path) if output_path else self._output_path(".mp4")
        cmd = [
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
        ]
        if shortest:
            cmd.append("-shortest")
        cmd.append(str(out))
        await self._run_ffmpeg(*cmd)
        log.info("Merged audio+video → %s", out)
        return out

    async def trim(
        self,
        input_path: str | Path,
        start: float | str,
        end: float | str,
        output_path: str | Path | None = None,
    ) -> Path:
        """Trim a media file to a time range.

        Parameters
        ----------
        input_path:
            Source file.
        start:
            Start time in seconds or ``"HH:MM:SS"`` / ``"MM:SS"`` format.
        end:
            End time in seconds or ``"HH:MM:SS"`` / ``"MM:SS"`` format.
        output_path:
            Destination file.

        Returns
        -------
        Path
            Trimmed output path.
        """
        suffix = Path(str(input_path)).suffix or ".mp4"
        out = Path(output_path) if output_path else self._output_path(suffix)
        await self._run_ffmpeg(
            "-y",
            "-i", str(input_path),
            "-ss", str(start),
            "-to", str(end),
            "-c", "copy",
            str(out),
        )
        log.info("Trimmed %s [%s–%s] → %s", input_path, start, end, out)
        return out

    async def create_thumbnail(
        self,
        video_path: str | Path,
        timestamp: float | str = 1.0,
        output_path: str | Path | None = None,
        *,
        width: int = 640,
    ) -> Path:
        """Extract a single frame from a video as an image.

        Parameters
        ----------
        video_path:
            Source video.
        timestamp:
            Time position for the frame (seconds or ``"HH:MM:SS"``).
        output_path:
            Destination image.
        width:
            Scale the thumbnail to this width (height auto-calculated).

        Returns
        -------
        Path
            Path to the generated thumbnail.
        """
        out = Path(output_path) if output_path else self._output_path(".jpg")
        await self._run_ffmpeg(
            "-y",
            "-i", str(video_path),
            "-ss", str(timestamp),
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            str(out),
        )
        log.info("Thumbnail at %s → %s", timestamp, out)
        return out

    async def concat(
        self,
        files: Sequence[str | Path],
        output_path: str | Path | None = None,
        *,
        fmt: str = "mp4",
    ) -> Path:
        """Concatenate multiple media files into one.

        Uses the ffmpeg concat demuxer for stream-copy when possible.

        Parameters
        ----------
        files:
            Ordered list of input files.
        output_path:
            Destination file.
        fmt:
            Output format.

        Returns
        -------
        Path
            Concatenated output path.
        """
        if not files:
            raise ValueError("No files provided for concatenation.")
        out = Path(output_path) if output_path else self._output_path(f".{fmt}")

        # Write concat list to a temp file
        list_file = self._output_path(".txt", f"concat_{uuid.uuid4().hex[:8]}.txt")
        lines = [f"file '{Path(f).resolve()}'" for f in files]
        list_file.write_text("\n".join(lines), encoding="utf-8")

        try:
            await self._run_ffmpeg(
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(out),
            )
        finally:
            list_file.unlink(missing_ok=True)

        log.info("Concatenated %d files → %s", len(files), out)
        return out

    async def add_subtitles(
        self,
        video_path: str | Path,
        srt_file: str | Path,
        output_path: str | Path | None = None,
        *,
        burn_in: bool = True,
        style: str = "",
    ) -> Path:
        """Add subtitles to a video.

        Parameters
        ----------
        video_path:
            Source video.
        srt_file:
            Path to the ``.srt`` or ``.vtt`` subtitle file.
        output_path:
            Destination file.
        burn_in:
            If *True*, burn subtitles into the video (hard-sub).
            Otherwise embed as a subtitle stream (soft-sub).
        style:
            ASS/SSA override style string for hard subs
            (e.g. ``"FontSize=24,PrimaryColour=&H00FFFFFF"``).

        Returns
        -------
        Path
            Output path with subtitles.
        """
        out = Path(output_path) if output_path else self._output_path(".mp4")

        if burn_in:
            # Burn subtitles into the video with the subtitles filter
            escaped_srt = str(Path(srt_file).resolve()).replace("'", r"\'").replace(":", r"\:")
            vf = f"subtitles='{escaped_srt}'"
            if style:
                vf += f":force_style='{style}'"
            await self._run_ffmpeg(
                "-y",
                "-i", str(video_path),
                "-vf", vf,
                "-c:a", "copy",
                str(out),
            )
        else:
            # Embed as a subtitle stream
            await self._run_ffmpeg(
                "-y",
                "-i", str(video_path),
                "-i", str(srt_file),
                "-c", "copy",
                "-c:s", "mov_text",
                str(out),
            )

        log.info("Added subtitles → %s", out)
        return out

    async def resize(
        self,
        input_path: str | Path,
        width: int,
        height: int = -1,
        output_path: str | Path | None = None,
    ) -> Path:
        """Resize a video to a specific resolution.

        Parameters
        ----------
        input_path:
            Source video.
        width:
            Target width in pixels.
        height:
            Target height (``-1`` to auto-calculate from aspect ratio).
        output_path:
            Destination file.

        Returns
        -------
        Path
            Resized output.
        """
        suffix = Path(str(input_path)).suffix or ".mp4"
        out = Path(output_path) if output_path else self._output_path(suffix)
        await self._run_ffmpeg(
            "-y",
            "-i", str(input_path),
            "-vf", f"scale={width}:{height}",
            "-c:a", "copy",
            str(out),
        )
        log.info("Resized → %dx%d → %s", width, height, out)
        return out

    async def change_speed(
        self,
        input_path: str | Path,
        speed: float = 2.0,
        output_path: str | Path | None = None,
    ) -> Path:
        """Change playback speed of a video.

        Parameters
        ----------
        input_path:
            Source video.
        speed:
            Speed multiplier (2.0 = double speed, 0.5 = half speed).
        output_path:
            Destination file.

        Returns
        -------
        Path
            Speed-adjusted output.
        """
        suffix = Path(str(input_path)).suffix or ".mp4"
        out = Path(output_path) if output_path else self._output_path(suffix)
        video_tempo = 1.0 / speed
        audio_tempo = speed

        # Audio tempo filter has a range of [0.5, 100]; chain if needed
        atempo_filters: list[str] = []
        remaining = audio_tempo
        while remaining > 2.0:
            atempo_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_filters.append("atempo=0.5")
            remaining /= 0.5
        atempo_filters.append(f"atempo={remaining:.4f}")

        await self._run_ffmpeg(
            "-y",
            "-i", str(input_path),
            "-filter:v", f"setpts={video_tempo:.4f}*PTS",
            "-filter:a", ",".join(atempo_filters),
            str(out),
        )
        log.info("Changed speed ×%.2f → %s", speed, out)
        return out

    async def extract_frames(
        self,
        video_path: str | Path,
        fps: float = 1.0,
        output_dir: str | Path | None = None,
        *,
        fmt: str = "jpg",
    ) -> list[Path]:
        """Extract frames from a video at a specified frame rate.

        Parameters
        ----------
        video_path:
            Source video.
        fps:
            Frames per second to extract.
        output_dir:
            Directory for output frames.
        fmt:
            Image format for extracted frames.

        Returns
        -------
        list[Path]
            Paths to the extracted frame images.
        """
        out_dir = Path(output_dir) if output_dir else self.workspace / f"frames_{uuid.uuid4().hex[:8]}"
        out_dir.mkdir(parents=True, exist_ok=True)

        pattern = str(out_dir / f"frame_%06d.{fmt}")
        await self._run_ffmpeg(
            "-y",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            pattern,
        )

        frames = sorted(out_dir.glob(f"frame_*.{fmt}"))
        log.info("Extracted %d frames → %s", len(frames), out_dir)
        return frames
