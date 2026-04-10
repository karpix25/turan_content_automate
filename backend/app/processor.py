import os
import logging
import random
import uuid
import ffmpeg
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self):
        logger.info("VideoProcessor initialized (subtitles/transcription disabled).")

    def _probe_media(self, media_path: str) -> Dict:
        return ffmpeg.probe(media_path)

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

    def process_video(self, 
                      input_path: str, 
                      output_path: str, 
                      plate_path: Optional[str] = None, 
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
            plate = ffmpeg.input(plate_path)
            video = ffmpeg.overlay(video, plate)

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
                vcodec='libx264',
                acodec='aac',
                threads='auto',
                pix_fmt='yuv420p',
                movflags='+faststart',
                map_metadata='-1',
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
                ass_path=ass_path,
                cta_path=variant_cta_path,
                subtitles_enabled=subtitles_enabled,
                unique_seed=variant_seed,
            )
            outputs.append(variant_output)
        return outputs

    def _build_unique_profile(self, unique_seed: Optional[int]) -> Dict[str, float | int]:
        rnd = random.Random(unique_seed if unique_seed is not None else random.randint(1, 10_000_000))
        return {
            "variant_id": int(rnd.random() * 1_000_000),
            "brightness": round(rnd.uniform(-0.03, 0.03), 3),
            "contrast": round(rnd.uniform(0.97, 1.06), 3),
            "saturation": round(rnd.uniform(0.95, 1.08), 3),
            "gamma": round(rnd.uniform(0.97, 1.04), 3),
            "speed": round(rnd.uniform(0.988, 1.012), 4),
        }
