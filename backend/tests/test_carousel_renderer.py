import tempfile
import unittest
from pathlib import Path

from app.services.karpix_carousel import build_render_data, load_template_set, render_account_carousel


def _template(name, variables, width=1080, height=1350):
    return {"id": name, "name": name, "width": width, "height": height, "variables": variables}


class KarpixCarouselTests(unittest.TestCase):
    def setUp(self):
        self.templates = [
            _template("ОБЛОЖКА", {
                "headlineAccent": {"required": True},
                "headlineMain": {"required": True},
                "аватар": {"required": True},
                "author": {"required": True},
            }),
            _template("Основное", {
                "Заголовок": {"required": True},
                "подзаголовок": {"required": True},
                "аватара": {"required": True},
                "автор": {"required": True},
            }),
            _template("СТА", {
                "CTA": {"required": True},
                "аватар": {"required": True},
                "author": {"required": True},
            }),
        ]

    def test_loads_saved_templates_by_name(self):
        loaded = load_template_set(type("Renderer", (), {"list_templates": lambda _: self.templates})())
        self.assertEqual(loaded["cover"]["id"], "ОБЛОЖКА")
        self.assertEqual(loaded["content"]["id"], "Основное")
        self.assertEqual(loaded["cta"]["id"], "СТА")

    def test_loads_saved_story_templates_by_existing_names(self):
        templates = [
            _template("Stories — Обложка", {
                "хук заголовок": {"required": True},
                "описание": {"required": True},
            }, height=1920),
            _template("Сторис основной ", {}, height=1920),
            _template("СТОРИС CTA", {}, height=1920),
        ]
        loaded = load_template_set(type("Renderer", (), {"list_templates": lambda _: templates})(), "story")
        self.assertEqual([loaded[key]["id"] for key in ("cover", "content", "cta")], [
            "Stories — Обложка", "Сторис основной ", "СТОРИС CTA",
        ])
        self.assertEqual(build_render_data(loaded["cover"], {
            "хук заголовок": "Сириус:",
            "описание": "бесплатная смена в Сочи.",
        }), {
            "хук заголовок": "Сириус:",
            "описание": "бесплатная смена в Сочи.",
        })

    def test_builds_all_required_fields_from_saved_template(self):
        data = build_render_data(
            self.templates[1],
            {
                "Заголовок": "Сириус:",
                "подзаголовок": "бесплатная смена в Сочи.",
                "аватара": "",
                "автор": "",
            },
            author="@turan",
            avatar_url="https://cdn.test/avatar.jpg",
        )
        self.assertEqual(data, {
            "Заголовок": "Сириус:",
            "подзаголовок": "бесплатная смена в Сочи.",
            "аватара": "https://cdn.test/avatar.jpg",
            "автор": "@turan",
        })

    def test_uses_json_fields_without_renaming_them(self):
        data = build_render_data(self.templates[0], {
            "headlineAccent": "Где бесплатно",
            "headlineMain": "готовиться к олимпиадам?",
            "аватар": "",
            "author": "",
        })
        self.assertEqual(data["headlineAccent"], "Где бесплатно")
        self.assertEqual(data["headlineMain"], "готовиться к олимпиадам?")

    def test_renders_saved_templates_in_cover_content_cta_order(self):
        class Renderer:
            def __init__(self):
                self.calls = []

            def render_saved_template(self, template_id, data, output_path):
                self.calls.append((template_id, data))
                Path(output_path).touch()

        renderer = Renderer()
        package = {
            "slide_count": 4,
            "cover": {
                "headlineAccent": "Главный хук",
                "headlineMain": "Одна связная тема",
                "аватар": "",
                "author": "",
            },
            "main": [
                {
                    "Заголовок": "Первый тезис",
                    "подзаголовок": "Короткое объяснение",
                    "аватара": "",
                    "автор": "",
                },
                {
                    "Заголовок": "Второй тезис",
                    "подзаголовок": "Ещё одно объяснение",
                    "аватара": "",
                    "автор": "",
                },
            ],
            "cta": {"CTA": "Подпишись", "аватар": "", "author": ""},
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = render_account_carousel(
                renderer,
                {"cover": self.templates[0], "content": self.templates[1], "cta": self.templates[2]},
                package,
                "Подпишись",
                "@turan",
                "https://cdn.test/avatar.jpg",
                Path(directory),
                "carousel",
                "vk",
                12,
            )
        self.assertEqual([call[0] for call in renderer.calls], ["ОБЛОЖКА", "Основное", "Основное", "СТА"])
        self.assertEqual(renderer.calls[-1][1]["CTA"], "Подпишись")
        self.assertEqual(len(paths), 4)

    def test_missing_saved_template_fails_instead_of_using_fallback(self):
        with self.assertRaisesRegex(ValueError, "сохранённый шаблон"):
            load_template_set(type("Renderer", (), {"list_templates": lambda _: self.templates[:2]})())


if __name__ == "__main__":
    unittest.main()
