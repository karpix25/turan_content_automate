import os
import shutil
import subprocess
import tempfile
import unittest

from app.services.broll_planner import BrollCandidate, build_broll_plan
from app.services.broll_renderer import BrollRenderer
from app.services.subtitle_generator import build_ass, write_ass_file
from app.processor import VideoProcessor


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class BrollRendererTests(unittest.TestCase):
    def test_render_preserves_duration_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            main_path = os.path.join(directory, "main.mp4")
            broll_path = os.path.join(directory, "broll.mp4")
            output_path = os.path.join(directory, "output.mp4")
            self.make_video(main_path, "testsrc=size=320x180:rate=24", 12, with_audio=True)
            self.make_video(broll_path, "color=c=red:size=320x180:rate=24", 5, with_audio=False)

            renderer = BrollRenderer()
            plan = build_broll_plan(
                main_duration=12,
                candidates=[BrollCandidate(1, broll_path, 5)],
                seed=1,
            )
            renderer.render(input_path=main_path, output_path=output_path, plan=plan, timeout_seconds=60)
            probe = renderer.probe(output_path)
            duration = float(probe["format"]["duration"])
            stream_types = {stream.get("codec_type") for stream in probe.get("streams", [])}
            self.assertAlmostEqual(duration, 12.0, delta=0.35)
            self.assertIn("video", stream_types)
            self.assertIn("audio", stream_types)

    def test_subtitles_burn_after_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            main_path = os.path.join(directory, "main.mp4")
            output_path = os.path.join(directory, "output.mp4")
            final_path = os.path.join(directory, "final.mp4")
            self.make_video(main_path, "testsrc=size=320x180:rate=24", 4, with_audio=True)
            ass_path = write_ass_file(
                build_ass({"results": {"utterances": [{"start": 0.5, "end": 1.5, "transcript": "test"}]}}) or "",
                directory=directory,
                prefix="captions",
            )
            renderer = BrollRenderer()
            plan = build_broll_plan(main_duration=4, candidates=[], seed=1)
            renderer.render(input_path=main_path, output_path=output_path, plan=plan, timeout_seconds=60)
            VideoProcessor().process_video(
                input_path=output_path,
                output_path=final_path,
                ass_path=ass_path,
                subtitles_enabled=True,
            )
            self.assertTrue(os.path.isfile(final_path))

    @staticmethod
    def make_video(path: str, video_filter: str, duration: int, *, with_audio: bool) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            video_filter,
        ]
        if with_audio:
            command.extend(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"])
        command.extend(["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"])
        if with_audio:
            command.extend(["-c:a", "aac", "-shortest"])
        command.append(path)
        subprocess.run(command, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
