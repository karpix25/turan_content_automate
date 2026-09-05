import array
import math
import os
import shutil
import subprocess
import tempfile
import unittest

import ffmpeg

from app.processor import VideoProcessor
from app.services.vizard_audio import restore_vizard_audio


def make_video(path, frequency, duration=2):
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=blue:size=160x120:rate=25", "-f", "lavfi", "-i",
        f"sine=frequency={frequency}:sample_rate=48000", "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path,
    ], check=True, capture_output=True)


def audio_packets(path):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0",
        "-c:a", "copy", "-f", "adts", "-",
    ])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VizardAudioTests(unittest.TestCase):
    def test_final_render_restores_original_packets_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            source, prepared, output = [os.path.join(directory, n + ".mp4") for n in ("source", "prepared", "output")]
            make_video(source, 440)
            make_video(prepared, 1200, 2.2)  # Damaged intermediate plus a cover gap.
            VideoProcessor().process_video(
                input_path=prepared, output_path=output, original_audio_path=source,
                uniqueization_mode="aggressive", unique_seed=42,
            )
            self.assertEqual(audio_packets(source), audio_packets(output))
            probe = ffmpeg.probe(output)
            video = next(s for s in probe["streams"] if s["codec_type"] == "video")
            audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
            self.assertAlmostEqual(float(video["duration"]), 2.2, delta=0.05)
            self.assertAlmostEqual(float(audio["start_time"]), 0.2, delta=0.03)

    def test_cta_preserves_original_speech_cover_and_ending(self):
        with tempfile.TemporaryDirectory() as directory:
            source, prepared, cta, output = [os.path.join(directory, n + ".mp4") for n in ("source", "prepared", "cta", "output")]
            make_video(source, 440)
            make_video(prepared, 1200, 2.2)
            make_video(cta, 880, 1)
            VideoProcessor().process_video(
                input_path=prepared, output_path=output, original_audio_path=source,
                cta_path=cta, uniqueization_mode="standard", unique_seed=42,
            )
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-i", output, "-vn", "-ac", "1",
                "-ar", "48000", "-f", "f32le", "-",
            ])
            samples = array.array("f", raw)
            def power(start, frequency):
                window = samples[int(start * 48000):int((start + 0.1) * 48000)]
                return abs(sum(v * complex(math.cos(2 * math.pi * frequency * i / 48000),
                                           math.sin(2 * math.pi * frequency * i / 48000))
                               for i, v in enumerate(window)))
            self.assertLess(max(abs(x) for x in samples[1000:4000]), 0.001)
            self.assertGreater(power(0.5, 440), 20 * power(0.5, 1200))
            self.assertGreater(power(2.5, 880), 20 * power(2.5, 440))
            self.assertAlmostEqual(float(ffmpeg.probe(output)["format"]["duration"]), 3.2, delta=0.08)

    def test_restore_failure_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "final.mp4")
            make_video(output, 440)
            original = audio_packets(output)
            with self.assertRaises(ffmpeg.Error):
                restore_vizard_audio(output_path=output, source_path="missing.mp4", prepared_path=output, cta_path=None)
            self.assertEqual(original, audio_packets(output))


if __name__ == "__main__":
    unittest.main()
