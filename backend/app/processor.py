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
        
        # 1. Start with the input stream
        stream = ffmpeg.input(input_path)
        video = stream.video
        audio = stream.audio

        # 2. Add Subtitles
        if subtitles_enabled and ass_path:
            video = video.filter('subtitles', ass_path, force_style="Alignment=2")

        # 2.1 Lightweight visual/audio uniqueness profile.
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

        # 3. Add Plate (Overlay)
        if plate_path:
            plate = ffmpeg.input(plate_path)
            # Center the plate or place it at the top/bottom as needed
            # For now, let's assume it's a fixed size transparent overlay
            video = ffmpeg.overlay(video, plate)

        # 4. Final render (intermediate or final)
        # Note: Concatenation with CTA is easier done as a separate step or a complex filter.
        # Given it's CPU, we'll try to do it in one pass if possible.
        
        if cta_path:
            # Concatenation logic in FFmpeg is tricky for disparate files.
            # Using the concat filter.
            cta_stream = ffmpeg.input(cta_path)
            cta_v = cta_stream.video
            cta_a = cta_stream.audio
            
            # Ensure same resolution/frame rate for concat
            video = ffmpeg.concat(video, cta_v, v=1, a=0)
            audio = ffmpeg.concat(audio, cta_a, v=0, a=1)

        # Final output
        unique_tag = uuid.uuid4().hex
        (
            ffmpeg
            .output(
                video,
                audio,
                output_path,
                vcodec='libx264',
                acodec='aac',
                threads='auto',
                movflags='+faststart',
                map_metadata='-1',
            )
            .global_args(
                "-metadata", f"title=content-studio-{unique_tag}",
                "-metadata", f"comment=uniq-{unique_tag}",
                "-metadata", f"description=variant-{profile['variant_id']}",
            )
            .overwrite_output()
            .run()
        )

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
