import os
import logging
import random
import uuid
import math
import subprocess
import ffmpeg
from typing import List, Dict, Optional, Tuple

from .utils.plate_media import is_plate_video

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self):
        logger.info("VideoProcessor initialized (subtitles/transcription disabled).")

    @staticmethod
    def _truthy_env(name: str, default: str = "0") -> bool:
        return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _encode_kwargs(self, *, include_audio: bool = True) -> Dict[str, object]:
        kwargs: Dict[str, object] = {
            "vcodec": "libx264",
            "preset": os.getenv("FFMPEG_X264_PRESET", "veryfast"),
            "crf": os.getenv("FFMPEG_X264_CRF", "18"),
            "pix_fmt": "yuv420p",
            "movflags": "+faststart",
            "map_metadata": "-1",
        }
        if include_audio:
            kwargs.update(
                {
                    "acodec": "aac",
                    "b:a": os.getenv("FFMPEG_AUDIO_BITRATE", "256k"),
                }
            )
        return kwargs

    def _probe_media(self, media_path: str) -> Dict:
        return ffmpeg.probe(media_path)

    def _run_ffmpeg_output(
        self,
        stream,
        *,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        process = stream.overwrite_output().run_async(
            pipe_stdin=False,
            pipe_stdout=True,
            pipe_stderr=True,
        )
        try:
            out, err = process.communicate(timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            out, err = process.communicate()
            timeout_error = ffmpeg.Error("ffmpeg", out or b"", err or b"")
            timeout_error.timeout_seconds = timeout_seconds
            raise timeout_error from exc
        if process.returncode != 0:
            raise ffmpeg.Error("ffmpeg", out or b"", err or b"")

    def _get_first_stream(self, probe_data: Dict, codec_type: str) -> Optional[Dict]:
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == codec_type:
                return stream
        return None

    def _parse_frame_rate(self, value: str | None) -> Optional[float]:
        raw = (value or "").strip()
        if not raw or raw == "0/0":
            return None
        if "/" in raw:
            num, den = raw.split("/", 1)
            try:
                numerator = float(num)
                denominator = float(den)
                if denominator == 0:
                    return None
                return numerator / denominator
            except ValueError:
                return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _build_silent_audio(self, duration: float, sample_rate: int) -> ffmpeg.nodes.FilterableStream:
        safe_duration = max(duration, 0.1)
        return ffmpeg.input(
            f"anullsrc=r={sample_rate}:cl=stereo",
            f="lavfi",
            t=safe_duration,
        ).audio

    def _safe_duration(self, value: float, minimum: float = 0.2) -> float:
        return max(minimum, float(value))

    def _fit_with_padding(
        self,
        stream: ffmpeg.nodes.FilterableStream,
        *,
        target_width: int,
        target_height: int,
    ) -> ffmpeg.nodes.FilterableStream:
        fitted = stream.filter(
            "scale",
            target_width,
            target_height,
            force_original_aspect_ratio="decrease",
        )
        return fitted.filter(
            "pad",
            target_width,
            target_height,
            "(ow-iw)/2",
            "(oh-ih)/2",
            color="black",
        ).filter("setsar", "1")

    def apply_avatar_insert_clips(
        self,
        *,
        input_path: str,
        insert_paths: List[str],
        start_percent: int,
        end_percent: int,
        clips_count: int,
        output_path: str,
        seed: Optional[int] = None,
        max_insert_seconds: float = 7.0,
        min_insert_seconds: float = 0.2,
        target_total_insert_seconds: Optional[float] = None,
        preserve_source_audio: bool = False,
        timeout_seconds: Optional[int] = None,
    ) -> tuple[str | None, dict]:
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "requested_count": int(max(0, clips_count)),
            "applied_count": 0,
            "window_percent": [int(start_percent), int(end_percent)],
            "target_total_insert_seconds": target_total_insert_seconds,
            "preserve_source_audio": preserve_source_audio,
            "timeout_seconds": timeout_seconds,
            "insertions": [],
        }

        if clips_count <= 0:
            meta["reason"] = "clips_count_is_zero"
            return None, meta

        source_probe = self._probe_media(input_path)
        source_video = self._get_first_stream(source_probe, "video")
        source_audio = self._get_first_stream(source_probe, "audio")
        if not source_video:
            meta["reason"] = "source_video_stream_missing"
            return None, meta

        source_duration = float(source_probe.get("format", {}).get("duration") or 0.0)
        if source_duration <= 0.5:
            meta["reason"] = "source_duration_too_short"
            return None, meta

        target_width = int(source_video.get("width") or 720)
        target_height = int(source_video.get("height") or 1280)
        target_fps = self._parse_frame_rate(
            source_video.get("avg_frame_rate") or source_video.get("r_frame_rate")
        )
        target_sample_rate = int((source_audio or {}).get("sample_rate") or 44100)
        include_audio = bool(source_audio) and not preserve_source_audio

        normalized_start = max(0, min(99, int(start_percent)))
        normalized_end = max(1, min(100, int(end_percent)))
        if normalized_end <= normalized_start:
            normalized_end = min(100, normalized_start + 1)

        window_start = source_duration * (normalized_start / 100.0)
        window_end = source_duration * (normalized_end / 100.0)
        window_length = window_end - window_start
        if window_length <= 0.4:
            meta["reason"] = "insert_window_too_small"
            return None, meta

        max_insert_limit = float(max_insert_seconds)
        min_insert_limit = max(0.2, float(min_insert_seconds))
        valid_candidates: List[Tuple[str, float]] = []
        for path in insert_paths:
            if not path or not os.path.isfile(path):
                continue
            try:
                probe = self._probe_media(path)
            except ffmpeg.Error:
                continue
            duration = float(probe.get("format", {}).get("duration") or 0.0)
            if duration < min_insert_limit:
                continue
            if max_insert_limit > 0:
                bounded_duration = min(duration, self._safe_duration(max_insert_limit))
            else:
                bounded_duration = duration
            valid_candidates.append((path, bounded_duration))

        if not valid_candidates:
            meta["reason"] = "no_valid_insert_clips"
            return None, meta

        rnd = random.Random(seed if seed is not None else random.randint(1, 9999999))
        rnd.shuffle(valid_candidates)
        selected = valid_candidates[: min(clips_count, len(valid_candidates))]
        if not selected:
            meta["reason"] = "no_selected_clips"
            return None, meta

        if target_total_insert_seconds is not None:
            target_total = max(min_insert_limit, float(target_total_insert_seconds))
            target_total = min(target_total, window_length * 0.95)
            selected_count = len(selected)
            target_per_clip = target_total / max(1, selected_count)
            if target_per_clip > max_insert_limit and max_insert_limit > 0:
                selected_count = min(len(valid_candidates), max(1, int(math.ceil(target_total / max_insert_limit))))
                selected = valid_candidates[:selected_count]
                target_per_clip = target_total / max(1, len(selected))
            if target_per_clip < min_insert_limit and selected_count > 1:
                selected_count = max(1, int(math.floor(target_total / min_insert_limit)))
                selected = selected[:selected_count]
                target_per_clip = target_total / max(1, len(selected))

            adjusted: List[Tuple[str, float]] = []
            for path, available_duration in selected:
                duration = min(available_duration, target_per_clip)
                if max_insert_limit > 0:
                    duration = min(duration, max_insert_limit)
                duration = max(min_insert_limit, duration)
                adjusted.append((path, self._safe_duration(duration, minimum=min_insert_limit)))
            selected = adjusted

        max_total_insert_duration = window_length * 0.95
        min_segment_duration = min_insert_limit

        # Keep requested insert count whenever possible and compress segment durations to fit the window.
        if sum(item[1] for item in selected) > max_total_insert_duration:
            per_insert_cap = max_total_insert_duration / max(1, len(selected))
            compressed: List[Tuple[str, float]] = []
            for path, duration in selected:
                bounded = min(duration, per_insert_cap)
                compressed.append((path, self._safe_duration(bounded, minimum=min_segment_duration)))
            selected = compressed

            total_after_compress = sum(item[1] for item in selected)
            if total_after_compress > max_total_insert_duration:
                overflow = total_after_compress - max_total_insert_duration
                adjustable = [
                    idx
                    for idx, (_path, duration) in enumerate(selected)
                    if duration > min_segment_duration + 1e-6
                ]
                while overflow > 1e-6 and adjustable:
                    step = overflow / len(adjustable)
                    next_adjustable: List[int] = []
                    for idx in adjustable:
                        path, duration = selected[idx]
                        room = max(0.0, duration - min_segment_duration)
                        delta = min(room, step)
                        duration -= delta
                        selected[idx] = (path, duration)
                        overflow -= delta
                        if duration > min_segment_duration + 1e-6:
                            next_adjustable.append(idx)
                    adjustable = next_adjustable

            if sum(item[1] for item in selected) > max_total_insert_duration + 1e-6:
                max_feasible_count = int(math.floor(max_total_insert_duration / min_segment_duration))
                if max_feasible_count <= 0:
                    meta["reason"] = "insert_window_too_small_for_min_duration"
                    return None, meta
                selected = selected[:max_feasible_count]
                if not selected:
                    meta["reason"] = "selected_clips_too_long_for_window"
                    return None, meta

        total_insert_duration = sum(item[1] for item in selected)
        slack = max(0.0, window_length - total_insert_duration)

        schedule: List[Tuple[str, float, float]] = []
        if len(selected) == 1:
            # Single insert: keep it centered in the user-selected window.
            only_path, only_duration = selected[0]
            start_time = window_start + (slack / 2.0)
            schedule.append((only_path, start_time, only_duration))
        else:
            # Max-distance strategy: place first at window start and last near window end.
            # Remaining inserts are spaced uniformly between them.
            inter_gap = slack / (len(selected) - 1)
            cursor = window_start
            for path, duration in selected:
                start_time = cursor
                schedule.append((path, start_time, duration))
                cursor = start_time + duration + inter_gap

        segment_inputs: List[Tuple[str, float, float]] = []
        timeline_cursor = 0.0
        for _path, start_time, duration in schedule:
            if start_time > timeline_cursor + 0.05:
                segment_inputs.append(("main", timeline_cursor, start_time - timeline_cursor))
            segment_inputs.append(("insert", start_time, duration))
            timeline_cursor = start_time + duration
        if source_duration > timeline_cursor + 0.05:
            segment_inputs.append(("main", timeline_cursor, source_duration - timeline_cursor))

        if not segment_inputs:
            meta["reason"] = "empty_timeline_after_planning"
            return None, meta

        streams: List[ffmpeg.nodes.FilterableStream] = []
        for seg_type, start_value, duration_value in segment_inputs:
            safe_duration = self._safe_duration(duration_value)
            if seg_type == "main":
                main_input = ffmpeg.input(input_path, ss=max(0.0, start_value), t=safe_duration)
                main_v = self._fit_with_padding(
                    main_input.video,
                    target_width=target_width,
                    target_height=target_height,
                )
                if target_fps:
                    main_v = main_v.filter("fps", fps=target_fps)
                streams.append(main_v)
                if include_audio:
                    if source_audio:
                        main_a = main_input.audio.filter("aresample", target_sample_rate)
                    else:
                        main_a = self._build_silent_audio(safe_duration, target_sample_rate)
                    streams.append(main_a)
                continue

            insert_index = len(meta["insertions"])
            insert_path = schedule[insert_index][0]
            insert_input = ffmpeg.input(insert_path, ss=0, t=safe_duration)
            insert_v = self._fit_with_padding(
                insert_input.video,
                target_width=target_width,
                target_height=target_height,
            )
            if target_fps:
                insert_v = insert_v.filter("fps", fps=target_fps)
            streams.append(insert_v)
            if include_audio:
                try:
                    insert_probe = self._probe_media(insert_path)
                    insert_audio_stream = self._get_first_stream(insert_probe, "audio")
                except ffmpeg.Error:
                    insert_audio_stream = None
                if insert_audio_stream:
                    insert_a = insert_input.audio.filter("aresample", target_sample_rate)
                else:
                    insert_a = self._build_silent_audio(safe_duration, target_sample_rate)
                streams.append(insert_a)

            meta["insertions"].append(
                {
                    "source_path": insert_path,
                    "start_sec": round(schedule[insert_index][1], 3),
                    "duration_sec": round(safe_duration, 3),
                }
            )

        try:
            if preserve_source_audio and source_audio:
                joined = ffmpeg.concat(*streams, v=1, a=0).node
                out_v = joined[0]
                audio_input = ffmpeg.input(input_path)
                self._run_ffmpeg_output(
                    ffmpeg.output(
                        out_v,
                        audio_input.audio,
                        output_path,
                        **self._encode_kwargs(include_audio=True),
                    ),
                    timeout_seconds=timeout_seconds,
                )
            elif include_audio:
                joined = ffmpeg.concat(*streams, v=1, a=1).node
                out_v = joined[0]
                out_a = joined[1]
                self._run_ffmpeg_output(
                    ffmpeg.output(
                        out_v,
                        out_a,
                        output_path,
                        **self._encode_kwargs(include_audio=True),
                    ),
                    timeout_seconds=timeout_seconds,
                )
            else:
                joined = ffmpeg.concat(*streams, v=1, a=0).node
                out_v = joined[0]
                self._run_ffmpeg_output(
                    ffmpeg.output(
                        out_v,
                        output_path,
                        **self._encode_kwargs(include_audio=False),
                    ),
                    timeout_seconds=timeout_seconds,
                )
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if getattr(exc, "stderr", None) else ""
            logger.error("Avatar insert montage failed for %s: %s", output_path, stderr)
            meta["status"] = "failed"
            meta["reason"] = "ffmpeg_timeout" if getattr(exc, "timeout_seconds", None) else "ffmpeg_failed"
            return None, meta

        if not os.path.isfile(output_path):
            meta["status"] = "failed"
            meta["reason"] = "output_missing_after_concat"
            return None, meta

        meta["status"] = "applied"
        meta["applied_count"] = len(meta["insertions"])
        return output_path, meta

    def transcribe(self, video_path: str) -> List[Dict]:
        """
        Whisper transcription is disabled in this build.
        """
        logger.info("Transcription skipped for %s (disabled).", video_path)
        return []

    def generate_ass_subtitles(self, segments: List[Dict], font_name: str, font_size: int, font_color: str) -> str:
        """
        Subtitle generation is disabled and returns an empty string.
        """
        return ""

    def _format_timestamp(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    def _normalize_percent(self, value: Optional[int]) -> int:
        if value is None:
            return 0
        return max(0, min(100, int(value)))

    def mux_video_and_audio(self, video_path: str, audio_path: str, output_path: str) -> str:
        logger.info("Muxing media streams into %s", output_path)

        video_ext = os.path.splitext(video_path)[1].lower()
        audio_ext = os.path.splitext(audio_path)[1].lower()
        video_codec = "copy" if video_ext in {".mp4", ".m4v"} else "libx264"
        audio_codec = "copy" if audio_ext in {".m4a", ".aac", ".mp4"} else "aac"

        try:
            video_input = ffmpeg.input(video_path)
            audio_input = ffmpeg.input(audio_path)

            output_kwargs: Dict[str, object] = {
                "vcodec": video_codec,
                "acodec": audio_codec,
                "movflags": "+faststart",
                "map_metadata": "-1",
                "shortest": None,
            }
            if video_codec != "copy":
                output_kwargs["pix_fmt"] = "yuv420p"

            (
                ffmpeg
                .output(video_input.video, audio_input.audio, output_path, **output_kwargs)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return output_path
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8", errors="ignore") if getattr(e, "stderr", None) else ""
            if stderr:
                logger.error("FFmpeg mux failed for %s: %s", output_path, stderr)
            raise

    def prepend_image_intro(
        self,
        *,
        input_path: str,
        image_path: str,
        output_path: str,
        duration_seconds: float = 10.0,
    ) -> tuple[str | None, dict]:
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "image_path": image_path,
            "duration_seconds": float(duration_seconds),
        }
        if not image_path or not os.path.isfile(image_path):
            meta["reason"] = "image_missing"
            return None, meta
        if duration_seconds <= 0:
            meta["reason"] = "duration_not_positive"
            return None, meta

        source_probe = self._probe_media(input_path)
        source_video = self._get_first_stream(source_probe, "video")
        source_audio = self._get_first_stream(source_probe, "audio")
        if not source_video:
            meta["reason"] = "source_video_stream_missing"
            return None, meta

        target_width = int(source_video.get("width") or 720)
        target_height = int(source_video.get("height") or 1280)
        target_fps = self._parse_frame_rate(
            source_video.get("avg_frame_rate") or source_video.get("r_frame_rate")
        )
        target_sample_rate = int((source_audio or {}).get("sample_rate") or 44100)
        source_duration = float(source_probe.get("format", {}).get("duration") or 0.0)
        include_audio = bool(source_audio)

        intro_input = ffmpeg.input(image_path, loop=1, t=duration_seconds)
        intro_v = self._fit_with_padding(
            intro_input.video,
            target_width=target_width,
            target_height=target_height,
        ).filter("trim", duration=duration_seconds).filter("setpts", "PTS-STARTPTS")
        if target_fps:
            intro_v = intro_v.filter("fps", fps=target_fps)

        main_input = ffmpeg.input(input_path)
        main_v = self._fit_with_padding(
            main_input.video,
            target_width=target_width,
            target_height=target_height,
        ).filter("setpts", "PTS-STARTPTS")
        if target_fps:
            main_v = main_v.filter("fps", fps=target_fps)

        try:
            if include_audio:
                intro_a = self._build_silent_audio(duration_seconds, target_sample_rate)
                main_a = main_input.audio.filter("aresample", target_sample_rate)
                joined = ffmpeg.concat(intro_v, intro_a, main_v, main_a, v=1, a=1).node
                out_v = joined[0]
                out_a = joined[1]
                (
                    ffmpeg
                    .output(
                        out_v,
                        out_a,
                        output_path,
                        **self._encode_kwargs(include_audio=True),
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
            else:
                joined = ffmpeg.concat(intro_v, main_v, v=1, a=0).node
                (
                    ffmpeg
                    .output(
                        joined[0],
                        output_path,
                        **self._encode_kwargs(include_audio=False),
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if getattr(exc, "stderr", None) else ""
            logger.error("Vertical thumbnail intro failed for %s: %s", output_path, stderr)
            meta["status"] = "failed"
            meta["reason"] = "ffmpeg_failed"
            return None, meta

        if not os.path.isfile(output_path):
            meta["status"] = "failed"
            meta["reason"] = "output_missing_after_concat"
            return None, meta

        meta["status"] = "applied"
        meta["source_duration_seconds"] = source_duration
        return output_path, meta

    def process_video(self, 
                      input_path: str, 
                      output_path: str, 
                      plate_path: Optional[str] = None, 
                      plate_start_percent: int = 0,
                      ass_path: Optional[str] = None,
                      cta_path: Optional[str] = None,
                      subtitles_enabled: bool = False,
                      unique_seed: Optional[int] = None):
        """
        The final rendering pipeline using FFmpeg.
        1. Burn subtitles.
        2. Overlay plate (image).
        3. Simple concatenation with CTA (if provided).
        """
        logger.info(f"Rendering final video: {output_path}")

        main_probe = self._probe_media(input_path)
        main_video_stream = self._get_first_stream(main_probe, "video")
        main_audio_stream = self._get_first_stream(main_probe, "audio")
        if not main_video_stream:
            raise RuntimeError(f"Input video stream not found: {input_path}")

        target_width = int(main_video_stream.get("width") or 720)
        target_height = int(main_video_stream.get("height") or 1280)
        target_fps = self._parse_frame_rate(
            main_video_stream.get("avg_frame_rate") or main_video_stream.get("r_frame_rate")
        )
        target_sample_rate = int((main_audio_stream or {}).get("sample_rate") or 44100)
        main_duration = float(main_probe.get("format", {}).get("duration") or 0.0)

        stream = ffmpeg.input(input_path)
        video = stream.video
        audio = stream.audio if main_audio_stream else self._build_silent_audio(main_duration, target_sample_rate)

        if subtitles_enabled and ass_path:
            video = video.filter('subtitles', ass_path, force_style="Alignment=2")

        profile = self._build_unique_profile(unique_seed)
        if profile["unique_variations_enabled"]:
            video = video.filter(
                "eq",
                brightness=profile["brightness"],
                contrast=profile["contrast"],
                saturation=profile["saturation"],
                gamma=profile["gamma"],
            )
            video = video.filter("setpts", f"PTS/{profile['speed']}")
            audio = audio.filter("atempo", profile["speed"])

        if plate_path:
            plate_is_video = is_plate_video(plate_path)
            normalized_plate_start_percent = self._normalize_percent(plate_start_percent)
            processed_main_duration = main_duration / profile["speed"] if profile["speed"] else main_duration
            plate_start_seconds = processed_main_duration * normalized_plate_start_percent / 100.0
            remaining_duration = max(0.1, processed_main_duration - plate_start_seconds)
            if plate_is_video:
                plate_input = ffmpeg.input(
                    plate_path,
                    stream_loop=-1,
                    t=max(remaining_duration + plate_start_seconds, remaining_duration),
                )
                plate = plate_input.video
            else:
                plate = ffmpeg.input(plate_path)
            plate = (
                plate
                .filter("format", "rgba")
                .filter(
                    "scale",
                    target_width,
                    target_height,
                    force_original_aspect_ratio="decrease",
                )
                .filter("setsar", "1")
                .filter("format", "rgba")
            )
            if plate_is_video and target_fps:
                plate = plate.filter("fps", fps=target_fps)
            overlay_kwargs = {
                "x": "(main_w-overlay_w)/2",
                "y": "(main_h-overlay_h)/2",
                "format": "auto",
            }
            if plate_is_video:
                overlay_kwargs.update({"eof_action": "pass", "repeatlast": 0})
            if plate_start_seconds > 0:
                video = ffmpeg.overlay(
                    video,
                    plate,
                    enable=f"gte(t,{plate_start_seconds:.3f})",
                    **overlay_kwargs,
                )
            else:
                video = ffmpeg.overlay(video, plate, **overlay_kwargs)

        if cta_path:
            cta_probe = self._probe_media(cta_path)
            cta_video_stream = self._get_first_stream(cta_probe, "video")
            cta_audio_stream = self._get_first_stream(cta_probe, "audio")
            if not cta_video_stream:
                raise RuntimeError(f"CTA video stream not found: {cta_path}")

            cta_duration = float(cta_probe.get("format", {}).get("duration") or 0.0)
            cta_stream = ffmpeg.input(cta_path)
            cta_v = cta_stream.video.filter("scale", target_width, target_height).filter("setsar", "1")
            if target_fps:
                cta_v = cta_v.filter("fps", fps=target_fps)

            cta_a = (
                cta_stream.audio
                if cta_audio_stream
                else self._build_silent_audio(cta_duration, target_sample_rate)
            )
            cta_a = cta_a.filter("aresample", target_sample_rate)

            video = video.filter("setsar", "1")
            joined = ffmpeg.concat(video, audio, cta_v, cta_a, v=1, a=1).node
            video = joined[0]
            audio = joined[1]

        unique_tag = uuid.uuid4().hex
        try:
            (
                ffmpeg
                .output(
                video,
                audio,
                output_path,
                threads='auto',
                **self._encode_kwargs(include_audio=True),
            )
                .global_args(
                "-metadata", f"title=content-studio-{unique_tag}",
                "-metadata", f"comment=uniq-{unique_tag}",
                "-metadata", f"description=variant-{profile['variant_id']}",
            )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8", errors="ignore") if getattr(e, "stderr", None) else ""
            if stderr:
                logger.error("FFmpeg render failed for %s: %s", output_path, stderr)
            raise

    def render_unique_variants(
        self,
        input_path: str,
        output_base_path: str,
        variants_count: int = 2,
        plate_path: Optional[str] = None,
        plate_start_percent: int = 0,
        ass_path: Optional[str] = None,
        cta_path: Optional[str] = None,
        cta_paths: Optional[List[Optional[str]]] = None,
        subtitles_enabled: bool = False,
    ) -> List[str]:
        base, ext = os.path.splitext(output_base_path)
        ext = ext or ".mp4"
        outputs: List[str] = []

        for idx in range(1, max(1, variants_count) + 1):
            variant_output = f"{base}_u{idx}{ext}"
            variant_seed = random.randint(1, 10_000_000)
            variant_cta_path = (
                cta_paths[idx - 1]
                if cta_paths and len(cta_paths) >= idx
                else cta_path
            )
            self.process_video(
                input_path=input_path,
                output_path=variant_output,
                plate_path=plate_path,
                plate_start_percent=plate_start_percent,
                ass_path=ass_path,
                cta_path=variant_cta_path,
                subtitles_enabled=subtitles_enabled,
                unique_seed=variant_seed,
            )
            outputs.append(variant_output)
        return outputs

    def _build_unique_profile(self, unique_seed: Optional[int]) -> Dict[str, float | int]:
        if not self._truthy_env("VIDEO_UNIQUE_VARIATIONS_ENABLED", "0"):
            return {
                "variant_id": 0,
                "brightness": 0.0,
                "contrast": 1.0,
                "saturation": 1.0,
                "gamma": 1.0,
                "speed": 1.0,
                "unique_variations_enabled": 0,
            }
        rnd = random.Random(unique_seed if unique_seed is not None else random.randint(1, 10_000_000))
        return {
            "variant_id": int(rnd.random() * 1_000_000),
            "brightness": round(rnd.uniform(-0.03, 0.03), 3),
            "contrast": round(rnd.uniform(0.97, 1.06), 3),
            "saturation": round(rnd.uniform(0.95, 1.08), 3),
            "gamma": round(rnd.uniform(0.97, 1.04), 3),
            "speed": round(rnd.uniform(0.988, 1.012), 4),
            "unique_variations_enabled": 1,
        }
