import os
import subprocess
from typing import Any

import ffmpeg

from .broll_planner import TimelineSegment


class BrollRenderer:
    def probe(self, path: str) -> dict[str, Any]:
        return ffmpeg.probe(path)

    @staticmethod
    def _stream(probe: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
        return next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == codec_type),
            None,
        )

    @staticmethod
    def _fps(value: str | None) -> float | None:
        raw = (value or "").strip()
        if not raw or raw == "0/0":
            return None
        try:
            if "/" in raw:
                numerator, denominator = raw.split("/", 1)
                return float(numerator) / float(denominator)
            return float(raw)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _fit_video(stream, width: int, height: int, fps: float | None):
        fitted = (
            stream.filter("scale", width, height, force_original_aspect_ratio="decrease")
            .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .filter("setsar", 1)
            .filter("setpts", "PTS-STARTPTS")
        )
        return fitted.filter("fps", fps=fps) if fps else fitted

    @staticmethod
    def _run(stream, timeout_seconds: int | None) -> None:
        process = stream.overwrite_output().run_async(
            pipe_stdin=False,
            pipe_stdout=True,
            pipe_stderr=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds or None)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            error = ffmpeg.Error("ffmpeg", stdout or b"", stderr or b"")
            error.timeout_seconds = timeout_seconds
            raise error from exc
        if process.returncode:
            raise ffmpeg.Error("ffmpeg", stdout or b"", stderr or b"")

    def render(
        self,
        *,
        input_path: str,
        output_path: str,
        plan: list[TimelineSegment],
        timeout_seconds: int | None = None,
    ) -> dict:
        if not plan:
            raise ValueError("B-roll plan is empty")
        source_probe = self.probe(input_path)
        source_video = self._stream(source_probe, "video")
        if not source_video:
            raise ValueError("Source video stream is missing")
        width = int(source_video.get("width") or 720)
        height = int(source_video.get("height") or 1280)
        fps = self._fps(source_video.get("avg_frame_rate") or source_video.get("r_frame_rate"))
        source_has_audio = self._stream(source_probe, "audio") is not None

        streams = []
        for segment in plan:
            path = input_path if segment.kind == "main" else segment.path
            if not path:
                raise ValueError("B-roll segment has no source path")
            clip = ffmpeg.input(path, ss=max(0.0, segment.source_start if segment.kind == "broll" else segment.start), t=segment.duration)
            streams.append(self._fit_video(clip.video, width, height, fps))

        joined = ffmpeg.concat(*streams, v=1, a=0).node[0]
        output_args = {
            "vcodec": "libx264",
            "preset": os.getenv("FFMPEG_X264_PRESET", "veryfast"),
            "crf": os.getenv("FFMPEG_X264_CRF", "18"),
            "pix_fmt": "yuv420p",
            "movflags": "+faststart",
            "map_metadata": "-1",
        }
        if source_has_audio:
            source_audio = ffmpeg.input(input_path).audio
            output_args.update({"acodec": "copy", "shortest": None})
            output = ffmpeg.output(joined, source_audio, output_path, **output_args)
        else:
            output = ffmpeg.output(joined, output_path, **output_args)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        self._run(output, timeout_seconds)
        if not os.path.isfile(output_path):
            raise RuntimeError("FFmpeg finished without creating B-roll output")
        return {
            "status": "applied",
            "segments": [segment.as_dict() for segment in plan],
            "output_path": output_path,
        }
