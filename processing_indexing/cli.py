import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path


def parser():
    p = argparse.ArgumentParser(
        description="Accuracy-first video processing and Qdrant indexing"
    )
    p.add_argument("path", type=Path)
    p.add_argument("--collection", default="video_windows")
    p.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--window-size", type=float, default=10)
    p.add_argument("--stride", type=float, default=5)
    p.add_argument(
        "--reprocess", action="store_true", help="Upsert deterministic point IDs again"
    )
    p.add_argument("--json-report", action="store_true")
    return p


def main():
    args = parser().parse_args()
    try:
        from qdrant_client import QdrantClient
        from .config import Settings
        from .transcription import FasterWhisperTranscriber
        from .visual_encoder import XClipVisualEncoder
        from .audio_encoder import ClapAudioEncoder
        from .text_encoder import BgeM3TextEncoder
        from .vlm import LocalQwenProvider
        from .qdrant_store import QdrantStore
        from .pipeline import ProcessingPipeline

        settings = replace(
            Settings.from_env(),
            window_seconds=args.window_size,
            stride_seconds=args.stride,
            collection_name=args.collection,
            device=args.device,
            batch_size=args.batch_size,
        )
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        pipeline = ProcessingPipeline(
            FasterWhisperTranscriber(device=args.device),
            XClipVisualEncoder(device=args.device),
            ClapAudioEncoder(device=args.device),
            BgeM3TextEncoder(device=args.device),
            LocalQwenProvider(device=args.device),
            QdrantStore(client, args.collection, args.batch_size),
            settings,
        )
        paths = (
            [args.path]
            if args.path.is_file()
            else sorted(
                p
                for p in args.path.iterdir()
                if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"}
            )
        )
        reports = []
        for path in paths:
            if not args.json_report:
                print(f"Processing {path}", file=sys.stderr)
            reports.append(pipeline.process_video(path).model_dump(mode="json"))
        print(json.dumps(reports if len(reports) != 1 else reports[0], indent=2))
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)})
            if args.json_report
            else f"error: {exc}",
            file=sys.stdout if args.json_report else sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
