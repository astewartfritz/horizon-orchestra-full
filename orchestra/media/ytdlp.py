"""Horizon Orchestra — yt-dlp Wrapper.

Async interface around the ``yt-dlp`` CLI for downloading videos, audio,
subtitles, and extracting metadata from YouTube and thousands of other
sites.  All subprocess calls use ``asyncio.create_subprocess_exec``.

Usage::

    from orchestra.media.ytdlp import YTDLPDownloader

    dl = YTDLPDownloader()
    info = await dl.extract_info("https://youtube.com/watch?v=...")
    result = await dl.download("https://youtube.com/watch?v=...")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = [
    "YTDLPDownloader",
    "VideoInfo",
    "DownloadResult",
    "FormatInfo",
    "YTDLPNotFoundError",
]

log = logging.getLogger("orchestra.media.ytdlp")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class YTDLPNotFoundError(RuntimeError):
    """Raised when yt-dlp is not on $PATH."""


class YTDLPError(RuntimeError):
    """Raised when yt-dlp returns a non-zero exit code."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FormatInfo:
    """Metadata for a single available format."""

    format_id: str = ""
    extension: str = ""
    resolution: str = ""
    filesize: int = 0
    vcodec: str = ""
    acodec: str = ""
    fps: float = 0.0
    tbr: float = 0.0  # total bitrate in kbps
    note: str = ""

    @property
    def is_video(self) -> bool:
        return self.vcodec not in ("none", "")

    @property
    def is_audio(self) -> bool:
        return self.acodec not in ("none", "")

    def __str__(self) -> str:
        parts = [self.format_id, self.extension, self.resolution]
        if self.vcodec and self.vcodec != "none":
            parts.append(f"v:{self.vcodec}")
        if self.acodec and self.acodec != "none":
            parts.append(f"a:{self.acodec}")
        if self.tbr:
            parts.append(f"{self.tbr:.0f}k")
        return " | ".join(p for p in parts if p)


@dataclass
class ThumbnailInfo:
    """A thumbnail associated with a video."""

    url: str = ""
    width: int = 0
    height: int = 0
    preference: int = 0


@dataclass
class VideoInfo:
    """Structured metadata extracted from a URL."""

    title: str = ""
    description: str = ""
    duration: float = 0.0
    uploader: str = ""
    upload_date: str = ""
    view_count: int = 0
    like_count: int = 0
    url: str = ""
    webpage_url: str = ""
    thumbnail: str = ""
    thumbnails: list[ThumbnailInfo] = field(default_factory=list)
    formats: list[FormatInfo] = field(default_factory=list)
    subtitles: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    chapters: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_str(self) -> str:
        """Duration as ``HH:MM:SS``."""
        if not self.duration:
            return "00:00"
        h = int(self.duration // 3600)
        m = int((self.duration % 3600) // 60)
        s = int(self.duration % 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


@dataclass
class DownloadResult:
    """Result of a download operation."""

    path: Path
    title: str = ""
    duration: float = 0.0
    format_id: str = ""
    extension: str = ""
    filesize: int = 0

    @property
    def filename(self) -> str:
        return self.path.name


# ---------------------------------------------------------------------------
# YTDLPDownloader
# ---------------------------------------------------------------------------

class YTDLPDownloader:
    """Async wrapper around the ``yt-dlp`` CLI.

    Parameters
    ----------
    workspace:
        Directory where downloaded files are saved.
    ytdlp_path:
        Override path to the ``yt-dlp`` binary.
    cookies_file:
        Optional path to a Netscape-format cookies file.
    proxy:
        Optional proxy URL.
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        ytdlp_path: str | None = None,
        cookies_file: str | Path | None = None,
        proxy: str | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "ytdlp"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._ytdlp = ytdlp_path or shutil.which("yt-dlp") or "yt-dlp"
        self._cookies = str(cookies_file) if cookies_file else None
        self._proxy = proxy

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    async def _check_installed(self) -> None:
        """Verify that yt-dlp is available on the system."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ytdlp, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                raise YTDLPNotFoundError(
                    "yt-dlp is installed but returned a non-zero exit code."
                )
            log.debug("yt-dlp version: %s", stdout.decode().strip())
        except FileNotFoundError:
            raise YTDLPNotFoundError(
                "yt-dlp is not installed or not found on $PATH.  "
                "Install it with: pip install yt-dlp"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_args(self) -> list[str]:
        """Common yt-dlp arguments."""
        args: list[str] = ["--no-warnings"]
        if self._cookies:
            args.extend(["--cookies", self._cookies])
        if self._proxy:
            args.extend(["--proxy", self._proxy])
        return args

    async def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> tuple[bytes, bytes]:
        """Execute a yt-dlp command asynchronously."""
        await self._check_installed()
        full_args = [self._ytdlp] + self._base_args() + list(args)
        log.debug("Running: %s", " ".join(full_args))
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if check and proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:2000]
            raise YTDLPError(f"yt-dlp exited with code {proc.returncode}: {err_msg}")
        return stdout, stderr

    def _parse_format(self, f: dict[str, Any]) -> FormatInfo:
        """Parse a single format dict from yt-dlp JSON."""
        return FormatInfo(
            format_id=str(f.get("format_id", "")),
            extension=f.get("ext", ""),
            resolution=f.get("resolution", f.get("format_note", "")),
            filesize=int(f.get("filesize", 0) or f.get("filesize_approx", 0) or 0),
            vcodec=f.get("vcodec", "none"),
            acodec=f.get("acodec", "none"),
            fps=float(f.get("fps", 0) or 0),
            tbr=float(f.get("tbr", 0) or 0),
            note=f.get("format_note", ""),
        )

    def _parse_info(self, data: dict[str, Any]) -> VideoInfo:
        """Parse yt-dlp JSON output into VideoInfo."""
        formats = [self._parse_format(f) for f in data.get("formats", [])]
        thumbnails = [
            ThumbnailInfo(
                url=t.get("url", ""),
                width=int(t.get("width", 0) or 0),
                height=int(t.get("height", 0) or 0),
                preference=int(t.get("preference", 0) or 0),
            )
            for t in data.get("thumbnails", [])
        ]
        return VideoInfo(
            title=data.get("title", ""),
            description=data.get("description", ""),
            duration=float(data.get("duration", 0) or 0),
            uploader=data.get("uploader", ""),
            upload_date=data.get("upload_date", ""),
            view_count=int(data.get("view_count", 0) or 0),
            like_count=int(data.get("like_count", 0) or 0),
            url=data.get("url", ""),
            webpage_url=data.get("webpage_url", ""),
            thumbnail=data.get("thumbnail", ""),
            thumbnails=thumbnails,
            formats=formats,
            subtitles=data.get("subtitles", {}),
            chapters=data.get("chapters", []),
            tags=data.get("tags", []),
            categories=data.get("categories", []),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_info(self, url: str) -> VideoInfo:
        """Extract metadata without downloading.

        Parameters
        ----------
        url:
            URL of the video page.

        Returns
        -------
        VideoInfo
            Structured metadata.
        """
        stdout, _ = await self._run(
            "--dump-json",
            "--no-download",
            url,
        )
        data = json.loads(stdout.decode())
        return self._parse_info(data)

    async def download(
        self,
        url: str,
        *,
        format_spec: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        output_dir: str | Path | None = None,
        filename_template: str = "%(title)s.%(ext)s",
        extra_args: Sequence[str] = (),
    ) -> DownloadResult:
        """Download a video.

        Parameters
        ----------
        url:
            URL to download from.
        format_spec:
            yt-dlp format selector string.
        output_dir:
            Target directory.
        filename_template:
            Output filename template using yt-dlp syntax.
        extra_args:
            Additional arguments passed to yt-dlp.

        Returns
        -------
        DownloadResult
            Information about the downloaded file.
        """
        out_dir = Path(output_dir) if output_dir else self.workspace
        out_dir.mkdir(parents=True, exist_ok=True)

        out_template = str(out_dir / filename_template)

        args = [
            "-f", format_spec,
            "-o", out_template,
            "--print-json",
            "--merge-output-format", "mp4",
        ]
        args.extend(extra_args)
        args.append(url)

        stdout, _ = await self._run(*args)
        data = json.loads(stdout.decode().strip().split("\n")[-1])

        filepath = data.get("_filename", data.get("filename", ""))
        if not filepath:
            # Fallback: find the most recent file in output dir
            files = sorted(out_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            filepath = str(files[0]) if files else ""

        result = DownloadResult(
            path=Path(filepath),
            title=data.get("title", ""),
            duration=float(data.get("duration", 0) or 0),
            format_id=data.get("format_id", ""),
            extension=data.get("ext", ""),
            filesize=int(data.get("filesize", 0) or 0),
        )
        log.info("Downloaded: %s → %s", url, result.path)
        return result

    async def download_audio_only(
        self,
        url: str,
        *,
        audio_format: str = "mp3",
        quality: str = "192",
        output_dir: str | Path | None = None,
    ) -> Path:
        """Download only the audio track from a video.

        Parameters
        ----------
        url:
            Video URL.
        audio_format:
            Target audio format (``mp3``, ``wav``, ``aac``, ``opus``).
        quality:
            Audio quality in kbps.
        output_dir:
            Destination directory.

        Returns
        -------
        Path
            Path to the downloaded audio file.
        """
        out_dir = Path(output_dir) if output_dir else self.workspace
        out_dir.mkdir(parents=True, exist_ok=True)

        out_template = str(out_dir / "%(title)s.%(ext)s")
        args = [
            "-x",
            "--audio-format", audio_format,
            "--audio-quality", quality,
            "-o", out_template,
            "--print-json",
            url,
        ]
        stdout, _ = await self._run(*args)
        data = json.loads(stdout.decode().strip().split("\n")[-1])
        filepath = data.get("_filename", data.get("filename", ""))

        # yt-dlp may keep the original ext in _filename; find the converted file
        p = Path(filepath)
        converted = p.with_suffix(f".{audio_format}")
        if converted.exists():
            p = converted
        elif not p.exists():
            files = sorted(out_dir.glob(f"*.{audio_format}"), key=lambda f: f.stat().st_mtime, reverse=True)
            p = files[0] if files else p

        log.info("Downloaded audio: %s → %s", url, p)
        return p

    async def download_best_quality(
        self,
        url: str,
        *,
        output_dir: str | Path | None = None,
    ) -> Path:
        """Download the highest quality video+audio.

        Parameters
        ----------
        url:
            Video URL.
        output_dir:
            Destination directory.

        Returns
        -------
        Path
            Path to the downloaded file.
        """
        result = await self.download(
            url,
            format_spec="bestvideo+bestaudio/best",
            output_dir=output_dir,
        )
        return result.path

    async def download_subtitles(
        self,
        url: str,
        *,
        language: str = "en",
        fmt: str = "srt",
        output_dir: str | Path | None = None,
    ) -> Path:
        """Download subtitles for a video.

        Parameters
        ----------
        url:
            Video URL.
        language:
            Subtitle language code (``en``, ``es``, ``fr``, …).
        fmt:
            Subtitle format (``srt``, ``vtt``, ``ass``).
        output_dir:
            Destination directory.

        Returns
        -------
        Path
            Path to the subtitle file.
        """
        out_dir = Path(output_dir) if output_dir else self.workspace
        out_dir.mkdir(parents=True, exist_ok=True)

        out_template = str(out_dir / "%(title)s.%(ext)s")
        args = [
            "--write-sub",
            "--write-auto-sub",
            "--sub-lang", language,
            "--sub-format", fmt,
            "--skip-download",
            "-o", out_template,
            url,
        ]
        await self._run(*args)

        # Find the subtitle file
        srt_files = sorted(
            out_dir.glob(f"*.{language}.{fmt}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not srt_files:
            srt_files = sorted(
                out_dir.glob(f"*.{fmt}"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        if not srt_files:
            raise YTDLPError(f"No subtitle file found for language '{language}'")

        log.info("Downloaded subtitles: %s → %s", url, srt_files[0])
        return srt_files[0]

    async def list_formats(self, url: str) -> list[FormatInfo]:
        """List all available formats for a URL.

        Parameters
        ----------
        url:
            Video URL.

        Returns
        -------
        list[FormatInfo]
            Available download formats.
        """
        info = await self.extract_info(url)
        return info.formats
