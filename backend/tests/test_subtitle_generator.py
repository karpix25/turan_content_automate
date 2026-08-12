import unittest

from app.services.subtitle_generator import build_ass


class SubtitleGeneratorTests(unittest.TestCase):
    def test_build_ass_uses_utterance_timing_and_offset(self):
        content = build_ass(
            {"results": {"utterances": [{"start": 1.25, "end": 2.5, "transcript": "Привет {мир}"}]}},
            start_offset=3.0,
        )
        self.assertIsNotNone(content)
        self.assertIn("Dialogue: 0,0:00:04.25,0:00:05.50", content)
        self.assertIn("Привет \\{мир\\}", content)

    def test_empty_transcript_returns_none(self):
        self.assertIsNone(build_ass({"results": {"utterances": []}}))


if __name__ == "__main__":
    unittest.main()
