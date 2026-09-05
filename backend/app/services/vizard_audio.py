"""Restore Vizard speech after visual rendering, preserving cover/CTA timing."""

import math
import os
import tempfile

import ffmpeg


def _video_duration(probe: dict) -> float:
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    duration = float(video.get("duration") or probe["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid video duration for Vizard audio restoration")
    return duration


def restore_vizard_audio(
    *, output_path: str, source_path: str, prepared_path: str, cta_path: str | None,
) -> None:
    source = ffmpeg.probe(source_path)
    if not any(s["codec_type"] == "audio" for s in source["streams"]):
        raise ValueError("Original Vizard clip has no audio stream")
    source_duration = _video_duration(source)
    prepared_duration = _video_duration(ffmpeg.probe(prepared_path))
    offset = prepared_duration - source_duration
    if offset < -0.1:
        raise ValueError("Prepared Vizard video is shorter than its original speech")
    offset = max(0.0, offset)
    video = ffmpeg.input(output_path).video
    options = {"vcodec": "copy", "movflags": "+faststart"}

    if not cta_path:
        # Timestamp offset adds the cover gap without touching compressed speech.
        audio = ffmpeg.input(source_path, itsoffset=offset).audio
        options["acodec"] = "copy"
    else:
        # Different CTA codecs/layouts require one encode, always from the originals.
        def segment(path: str | None, duration: float):
            stream = (
                ffmpeg.input(path).audio if path else
                ffmpeg.input("anullsrc=r=48000:cl=stereo", f="lavfi", t=duration).audio
            )
            return (stream.filter("aresample", 48000)
                    .filter("aformat", channel_layouts="stereo")
                    .filter("apad").filter("atrim", duration=duration)
                    .filter("asetpts", "PTS-STARTPTS"))

        parts = [segment(None, offset)] if offset > 0 else []
        parts.append(segment(source_path, source_duration))
        cta = ffmpeg.probe(cta_path)
        cta_has_audio = any(s["codec_type"] == "audio" for s in cta["streams"])
        parts.append(segment(cta_path if cta_has_audio else None, _video_duration(cta)))
        audio = ffmpeg.concat(*parts, v=0, a=1)
        options.update(acodec="aac", **{"b:a": os.getenv("FFMPEG_AUDIO_BITRATE", "256k")})

    fd, temporary = tempfile.mkstemp(suffix=".mp4", dir=os.path.dirname(output_path) or ".")
    os.close(fd)
    try:
        ffmpeg.output(video, audio, temporary, **options).overwrite_output().run(
            capture_stdout=True, capture_stderr=True,
        )
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
