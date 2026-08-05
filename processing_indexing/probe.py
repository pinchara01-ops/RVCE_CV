import hashlib
import json
import subprocess
from pathlib import Path
from .models import VideoMetadata


class VideoProbeError(RuntimeError):
    pass


def stable_video_id(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path, ffprobe="ffprobe") -> VideoMetadata:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise VideoProbeError(f"Video is not a readable file: {path}")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoProbeError(f"Could not run FFprobe: {exc}") from exc
    if result.returncode:
        raise VideoProbeError(
            f"FFprobe rejected video: {result.stderr.strip() or 'corrupt/unsupported file'}"
        )
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video is None:
            raise VideoProbeError("Video has no video stream")
        n, d = (video.get("avg_frame_rate") or video["r_frame_rate"]).split("/")
        return VideoMetadata(
            duration=float(data["format"].get("duration") or video["duration"]),
            has_video=True,
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
            fps=float(n) / float(d),
            width=int(video["width"]),
            height=int(video["height"]),
            codec=video["codec_name"],
            container=data["format"]["format_name"],
        )
    except VideoProbeError:
        raise
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise VideoProbeError(f"Invalid/corrupt FFprobe metadata: {exc}") from exc
