import unittest

from app.services.subtitle_generator import build_ass


class SubtitleGeneratorTests(unittest.TestCase):
    def test_build_ass_renders_one_word_at_a_time(self):
        content = build_ass(
            {
                "results": {
                    "utterances": [{
                        "start": 1.25,
                        "end": 2.5,
                        "transcript": "Привет мир",
                        "words": [
                            {"word": "Привет", "start": 1.25, "end": 1.8},
                            {"word": "мир", "start": 1.9, "end": 2.5},
                        ],
                    }]
                }
            },
            start_offset=3.0,
        )
        self.assertIsNotNone(content)
        self.assertIn("Dialogue: 0,0:00:04.25,0:00:04.80,Default,,0,0,0,,Привет", content)
        self.assertIn("Dialogue: 0,0:00:04.90,0:00:05.50,Default,,0,0,0,,мир", content)
        self.assertNotIn("Привет мир", content)
        self.assertIn("Style: Default,Montserrat,60,&H00FFFFFF,&H00000000,&H00000000,&H00000000", content)

    def test_build_ass_falls_back_to_word_slices_without_deepgram_words(self):
        content = build_ass(
            {"results": {"utterances": [{"start": 0.0, "end": 2.0, "transcript": "Привет мир"}]}},
        )
        self.assertIsNotNone(content)
        self.assertIn(",,Привет", content)
        self.assertIn(",,мир", content)

    def test_empty_transcript_returns_none(self):
        self.assertIsNone(build_ass({"results": {"utterances": []}}))


if __name__ == "__main__":
    unittest.main()
