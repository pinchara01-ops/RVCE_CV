from pathlib import Path
import time
from .config import Settings
from .models import ProcessingReport, RunStatus, WindowPayload, WindowVectors
from .probe import probe_video, stable_video_id
from .windowing import generate_windows, transcript_for_window


class ProcessingPipeline:
    def __init__(
        self,
        transcriber,
        visual_encoder,
        audio_encoder,
        text_encoder,
        vlm,
        store,
        settings: Settings | None = None,
    ):
        self.transcriber, self.visual, self.audio, self.text, self.vlm, self.store = (
            transcriber,
            visual_encoder,
            audio_encoder,
            text_encoder,
            vlm,
            store,
        )
        self.settings = settings or Settings()

    def process_video(self, video_path: Path) -> ProcessingReport:
        started = time.monotonic()
        path = Path(video_path).expanduser().resolve()
        video_id = stable_video_id(path)
        metadata = probe_video(path)
        windows = generate_windows(
            video_id,
            metadata.duration,
            self.settings.window_seconds,
            self.settings.stride_seconds,
        )
        segments = self.transcriber.transcribe(path, metadata.has_audio)
        self.store.ensure_collection()
        successful = []
        errors = {}
        vlm_successes = vlm_failures = 0
        for window in windows:
            try:
                transcript = transcript_for_window(segments, window.start, window.end)
                visual = self.visual.encode(path, window)
                audio = self.audio.encode(path, window, metadata.has_audio)
                try:
                    description = self.vlm.describe(path, window)
                    caption = description.caption()
                    processed = True
                    vlm_successes += 1
                except Exception as exc:
                    vlm_failures += 1
                    raise RuntimeError(f"VLM failed: {exc}") from exc
                speech_vector = self.text.encode([transcript])[0]
                caption_vector = self.text.encode([caption])[0]
                payload = WindowPayload(
                    video_id=video_id,
                    window_id=window.window_id,
                    start=window.start,
                    end=window.end,
                    transcript=transcript,
                    caption=caption,
                    has_audio=metadata.has_audio,
                    vlm_processed=processed,
                    source_path=str(path),
                )
                vectors = WindowVectors(
                    visual=visual,
                    audio=audio,
                    speech=speech_vector,
                    caption=caption_vector,
                )
                successful.append((payload, vectors))
            except Exception as exc:
                errors[window.window_id] = str(exc)
        indexed = 0
        for offset in range(0, len(successful), self.settings.batch_size):
            batch = successful[offset : offset + self.settings.batch_size]
            try:
                self.store.upsert(batch)
                indexed += len(batch)
            except Exception as exc:
                for payload, _ in batch:
                    errors[payload.window_id] = f"Qdrant upsert failed: {exc}"
        failed = len(windows) - indexed
        status = (
            RunStatus.complete
            if failed == 0
            else (RunStatus.partial if indexed else RunStatus.failed)
        )
        return ProcessingReport(
            video_id=video_id,
            duration=metadata.duration,
            total_windows=len(windows),
            successfully_indexed_windows=indexed,
            failed_windows=failed,
            vlm_successes=vlm_successes,
            vlm_failures=vlm_failures,
            elapsed_seconds=time.monotonic() - started,
            errors=errors,
            status=status,
        )
