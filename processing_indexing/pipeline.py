from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import time

from .config import Settings
from .models import (
    ProcessingReport,
    RunStatus,
    VLMDescription,
    WindowPayload,
    WindowVectors,
)
from .probe import probe_video, stable_video_id
from .selection import (
    SelectionInput,
    is_strong_boundary,
    select_vlm_windows,
)
from .windowing import generate_windows, transcript_for_window

CAPTION_UNAVAILABLE_TEXT = "[CAPTION UNAVAILABLE]"
INHERITED_PREFIX = "Inherited nearby scene context"
STAGES = (
    "ffprobe_validation",
    "media_decoding_window_creation",
    "whisper",
    "xclip",
    "clap",
    "bge_m3_speech",
    "selector",
    "openai_vlm",
    "bge_m3_caption",
    "qdrant",
    "export_generation",
)


@dataclass
class PreparedWindow:
    window: object
    transcript: str
    visual: list[float]
    audio: list[float]
    speech: list[float]
    has_meaningful_audio: bool


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
        clock=time.monotonic,
        progress_callback=None,
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
        self.clock = clock
        self.progress_callback = progress_callback
        self.stage_durations = {name: 0.0 for name in STAGES}

    def _progress(self, stage, fraction, current_window=0, total_windows=0):
        if self.progress_callback is not None:
            self.progress_callback(stage, fraction, current_window, total_windows)

    def _timed(self, stage, operation):
        started = self.clock()
        try:
            return operation()
        finally:
            self.stage_durations[stage] += self.clock() - started

    def _prepare(self, path, windows, segments, has_audio):
        prepared = []
        errors = {}
        total = len(windows)
        for index, window in enumerate(windows):
            self._progress("embedding_windows", 0.20 + 0.35 * index / max(total, 1), index, total)
            try:
                transcript = transcript_for_window(segments, window.start, window.end)
                visual = self._timed("xclip", lambda: self.visual.encode(path, window))
                audio = self._timed(
                    "clap", lambda: self.audio.encode(path, window, has_audio)
                )
                speech = self._timed(
                    "bge_m3_speech", lambda: self.text.encode([transcript])[0]
                )
                meaningful_audio = has_audio and any(
                    abs(value) > 1e-8 for value in audio
                )
                prepared.append(
                    PreparedWindow(
                        window, transcript, visual, audio, speech, meaningful_audio
                    )
                )
            except Exception as exc:
                errors[window.window_id] = str(exc)
        return prepared, errors

    def _select(self, prepared):
        inputs = [
            SelectionInput(
                item.visual,
                item.audio,
                item.speech,
                item.has_meaningful_audio,
                bool(item.transcript.strip()),
            )
            for item in prepared
        ]
        return select_vlm_windows(inputs, self.settings)

    def _run_vlm(self, path, prepared, decisions):
        direct: dict[int, VLMDescription] = {}
        failures: dict[int, str] = {}
        selected = {decision.index for decision in decisions if decision.selected}
        index = 0
        while index < len(prepared):
            if index in selected:
                try:
                    result = self.vlm.describe(path, prepared[index].window)
                    direct[index] = result
                    if (
                        result.confidence < self.settings.vlm_min_direct_confidence
                        and index + 1 < len(prepared)
                    ):
                        selected.add(index + 1)
                        if (
                            "previous_low_confidence"
                            not in decisions[index + 1].reasons
                        ):
                            decisions[index + 1].reasons.append(
                                "previous_low_confidence"
                            )
                        decisions[index + 1].selected = True
                except Exception as exc:
                    failures[index] = str(exc)
                    if index + 1 < len(prepared):
                        selected.add(index + 1)
                        if "previous_vlm_failure" not in decisions[index + 1].reasons:
                            decisions[index + 1].reasons.append("previous_vlm_failure")
                        decisions[index + 1].selected = True
            index += 1
        return direct, failures, selected

    def _inheritance_source(self, target, direct, decisions):
        candidates = sorted(direct, key=lambda source: (abs(source - target), source))
        for source in candidates:
            if direct[source].confidence < self.settings.vlm_min_direct_confidence:
                continue
            distance = abs(source - target)
            if distance == 0 or distance > self.settings.vlm_context_neighbours:
                continue
            crossed = range(min(source, target) + 1, max(source, target) + 1)
            if any(
                is_strong_boundary(decisions[index], self.settings) for index in crossed
            ):
                continue
            context = direct[source].context_caption()
            if context:
                return source, distance, context
        return None

    def process_video(self, video_path: Path) -> ProcessingReport:
        self.stage_durations = {name: 0.0 for name in STAGES}
        started = self.clock()
        path = Path(video_path).expanduser().resolve()
        self._progress("ffprobe_validation", 0.02)
        video_id, metadata = self._timed(
            "ffprobe_validation", lambda: (stable_video_id(path), probe_video(path))
        )
        windows = self._timed(
            "media_decoding_window_creation",
            lambda: generate_windows(
                video_id,
                metadata.duration,
                self.settings.window_seconds,
                self.settings.stride_seconds,
            ),
        )
        if self.settings.max_windows is not None:
            windows = windows[: self.settings.max_windows]
        self._progress("transcription", 0.10, 0, len(windows))
        segments = self._timed(
            "whisper", lambda: self.transcriber.transcribe(path, metadata.has_audio)
        )
        self._progress("qdrant_schema", 0.18, 0, len(windows))
        self._timed("qdrant", self.store.ensure_collection)
        prepared, errors = self._prepare(path, windows, segments, metadata.has_audio)
        if not prepared:
            return ProcessingReport(
                video_id=video_id,
                duration=metadata.duration,
                total_windows=len(windows),
                successfully_indexed_windows=0,
                failed_windows=len(windows),
                vlm_successes=0,
                vlm_failures=0,
                elapsed_seconds=self.clock() - started,
                errors=errors,
                status=RunStatus.failed,
                stage_durations=self.stage_durations,
            )
        self._progress("selecting_windows", 0.56, len(prepared), len(windows))
        decisions = self._timed("selector", lambda: self._select(prepared))
        self._progress("captioning_windows", 0.62, 0, len(prepared))
        if getattr(self.vlm, "disabled", False):
            # Selection-only indexing still calculates selection evidence, but
            # deliberately performs no VLM calls and must not label empty
            # captions as direct VLM output.
            direct, vlm_failures, selected = {}, {}, set()
        else:
            direct, vlm_failures, selected = self._timed(
                "openai_vlm", lambda: self._run_vlm(path, prepared, decisions)
            )
        errors.update(
            {
                prepared[index].window.window_id: f"VLM failed: {message}"
                for index, message in vlm_failures.items()
            }
        )
        records = []
        inherited_count = unavailable_count = 0
        for index, item in enumerate(prepared):
            self._progress("building_payloads", 0.74 + 0.12 * index / max(len(prepared), 1), index, len(prepared))
            decision = decisions[index]
            if index in direct:
                description = direct[index]
                caption = description.caption()
                provenance = dict(
                    vlm_processed=True,
                    caption_direct=True,
                    caption_inherited=False,
                    caption_available=bool(caption),
                    caption_source_window_id=None,
                    caption_source_distance=0,
                    caption_confidence=description.confidence,
                )
                caption_text = caption if caption else CAPTION_UNAVAILABLE_TEXT
                if not caption:
                    unavailable_count += 1
            else:
                inherited = self._inheritance_source(index, direct, decisions)
                if inherited:
                    source, distance, context = inherited
                    caption = f"{INHERITED_PREFIX} from {prepared[source].window.window_id}: {context}"
                    caption_text = caption
                    inherited_count += 1
                    provenance = dict(
                        vlm_processed=False,
                        caption_direct=False,
                        caption_inherited=True,
                        caption_available=True,
                        caption_source_window_id=prepared[source].window.window_id,
                        caption_source_distance=distance,
                        caption_confidence=0.0,
                    )
                else:
                    caption = ""
                    caption_text = CAPTION_UNAVAILABLE_TEXT
                    unavailable_count += 1
                    provenance = dict(
                        vlm_processed=False,
                        caption_direct=False,
                        caption_inherited=False,
                        caption_available=False,
                        caption_source_window_id=None,
                        caption_source_distance=0,
                        caption_confidence=0.0,
                    )
            caption_vector = self._timed(
                "bge_m3_caption", lambda: self.text.encode([caption_text])[0]
            )
            payload = WindowPayload(
                video_id=video_id,
                window_id=item.window.window_id,
                start=item.window.start,
                end=item.window.end,
                transcript=item.transcript,
                caption=caption,
                has_audio=metadata.has_audio,
                source_path=str(path),
                selection_reasons=decision.reasons,
                change_scores=decision.change_scores,
                change_from_previous=decision.change_from_previous,
                change_from_last_vlm=decision.change_from_last_vlm,
                vlm_call_state=(
                    "failed"
                    if index in vlm_failures
                    else "succeeded"
                    if index in direct
                    else "inherited"
                    if provenance["caption_inherited"]
                    else "unavailable"
                ),
                **provenance,
            )
            vectors = WindowVectors(
                visual=item.visual,
                audio=item.audio,
                speech=item.speech,
                caption=caption_vector,
            )
            records.append((payload, vectors))
        indexed = 0
        for offset in range(0, len(records), self.settings.batch_size):
            batch = records[offset : offset + self.settings.batch_size]
            self._progress("writing_qdrant", 0.87 + 0.12 * offset / max(len(records), 1), offset, len(records))
            try:
                self._timed("qdrant", lambda: self.store.upsert(batch))
                indexed += len(batch)
            except Exception as exc:
                for payload, _ in batch:
                    errors[payload.window_id] = f"Qdrant upsert failed: {exc}"
        failed = len(windows) - indexed
        status = (
            RunStatus.failed
            if not indexed
            else RunStatus.partial
            if failed
            else RunStatus.completed_with_errors
            if vlm_failures
            else RunStatus.complete
        )
        reason_counts = Counter(
            reason for decision in decisions for reason in decision.reasons
        )
        averages = {
            name: sum(d.change_scores.get(name, 0.0) for d in decisions)
            / len(decisions)
            for name in ("visual", "audio", "speech", "combined")
        }
        selected_count = len(selected)
        self._progress("complete", 1.0, len(records), len(records))
        return ProcessingReport(
            video_id=video_id,
            duration=metadata.duration,
            total_windows=len(windows),
            successfully_indexed_windows=indexed,
            failed_windows=failed,
            vlm_successes=len(direct),
            vlm_failures=len(vlm_failures),
            elapsed_seconds=self.clock() - started,
            errors=errors,
            status=status,
            selected_vlm_windows=selected_count,
            successful_vlm_windows=len(direct),
            failed_vlm_windows=len(vlm_failures),
            skipped_vlm_windows=len(windows) - selected_count,
            direct_caption_windows=sum(
                bool(value.caption()) for value in direct.values()
            ),
            inherited_caption_windows=inherited_count,
            unavailable_caption_windows=unavailable_count,
            selected_ratio=selected_count / len(windows),
            estimated_calls_saved=len(windows) - selected_count,
            selection_count_by_reason=dict(reason_counts),
            average_change=averages,
            selection_config={
                "enabled": self.settings.vlm_selection_enabled,
                "visual_threshold": self.settings.vlm_visual_change_threshold,
                "audio_threshold": self.settings.vlm_audio_change_threshold,
                "speech_threshold": self.settings.vlm_speech_change_threshold,
                "combined_threshold": self.settings.vlm_combined_change_threshold,
                "visual_weight": self.settings.vlm_change_weight_visual,
                "audio_weight": self.settings.vlm_change_weight_audio,
                "speech_weight": self.settings.vlm_change_weight_speech,
                "max_gap_windows": self.settings.vlm_max_gap_windows,
                "max_selected_ratio": self.settings.vlm_max_selected_ratio,
            },
            stage_durations=self.stage_durations,
        )
