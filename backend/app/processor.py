import os
import logging
from faster_whisper import WhisperModel
import ffmpeg
from typing import List, Dict, Optional
import json

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, model_size: str = "large-v3", device: str = "cpu", compute_type: str = "int8"):
        # Initialize Whisper
        logger.info(f"Loading Whisper model {model_size} on {device} with {compute_type}...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, video_path: str) -> List[Dict]:
        """
        Transcribes the video and returns a list of segments with timestamps.
        """
        logger.info(f"Transcribing {video_path}...")
        segments, info = self.model.transcribe(video_path, beam_size=5, word_timestamps=True)
        
        result = []
        for segment in segments:
            for word in segment.words:
                result.append({
                    "start": word.start,
                    "end": word.end,
                    "text": word.word.strip()
                })
        return result

    def generate_ass_subtitles(self, segments: List[Dict], font_name: str, font_size: int, font_color: str) -> str:
        """
        Creates an .ass subtitle file content from segments.
        This allows for the rich styling requested (fonts from Google Fonts, etc).
        """
        # Basic ASS header with styles
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00{font_color},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,2,2,10,10,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []
        for s in segments:
            # Format time: H:MM:SS.cs
            start_t = self._format_timestamp(s["start"])
            end_t = self._format_timestamp(s["end"])
            text = s["text"]
            events.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{text}")
        
        return header + "\n".join(events)

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
                      cta_path: Optional[str] = None):
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
        if ass_path:
            video = video.filter('subtitles', ass_path, force_style="Alignment=2")

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
        (
            ffmpeg
            .output(video, audio, output_path, vcodec='libx264', acodec='aac', threads='auto')
            .overwrite_output()
            .run()
        )
