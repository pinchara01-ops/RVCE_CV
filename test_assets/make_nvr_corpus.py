"""Generate an NVR-style corpus from the licensed assets.

The asset library has no capture times, so the camera and time filters have
nothing to demonstrate against. This derives short clips named the way a network
video recorder names them, which is where the metadata parser reads camera and
timestamp from.

Media is gitignored, so this script is the tracked artefact: anyone can
regenerate the corpus from the committed originals.

    python test_assets/make_nvr_corpus.py

The scenario is deliberately built so each filter is provable:
  - CAM01 and CAM02 share a timestamp, so a camera filter must narrow.
  - CAM01 appears in both afternoon and night, so time-of-day must narrow.
  - CAM03 is on a different date, so a date filter must exclude it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "asset_library" / "media"
OUT = ROOT / "nvr"

ATM = ROOT / "public_domain" / "vidssave.com Surveillance_ Thieves rip open ATM in Shelbyville 1080P.mp4"
DASHCAM = ROOT / "public_domain" / "ga_paulding_vehicle_burglary_dashcam_20m.webm"
LOW_LIGHT = ROOT / "derived" / "atm_low_light.mp4"
SILENT = ROOT / "derived" / "atm_silent.mp4"

# (source, start, seconds, output name)
# 2026-08-04 is a Tuesday, so "tuesday afternoon" resolves onto CAM01/CAM02.
CLIPS: list[tuple[Path, float, float, str]] = [
    (ATM, 0, 40, "CAM01_20260804_143000.mp4"),
    (DASHCAM, 300, 40, "CAM02_20260804_143000.mp4"),
    (LOW_LIGHT, 30, 30, "CAM01_20260804_221500.mp4"),
    (SILENT, 0, 30, "CAM03_20260805_091500.mp4"),
]


def cut(source: Path, start: float, seconds: float, target: Path) -> bool:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.2f}", "-i", str(source), "-t", f"{seconds:.2f}",
        "-vf", "scale=854:-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        print(f"  FAILED {target.name}: {result.stderr.decode('utf-8', 'replace')[:160]}")
        return False
    return True


def main() -> int:
    missing = [path for path, *_ in CLIPS if not path.is_file()]
    if missing:
        print("Missing source assets. Fetch the asset library first:")
        for path in dict.fromkeys(missing):
            print(f"  {path}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    made = 0
    for source, start, seconds, name in CLIPS:
        target = OUT / name
        print(f"  {name} <- {source.name}")
        if cut(source, start, seconds, target):
            made += 1

    print(f"\n{made}/{len(CLIPS)} clips written to {OUT}")
    return 0 if made == len(CLIPS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
