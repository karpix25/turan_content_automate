import unittest

from app.services.carousel_template import build_carousel_render_request


class CarouselRendererTemplateTests(unittest.TestCase):
    def test_template_renders_exact_size_and_text_without_image_generator(self):
        contract = (
            '{"palette":{"background":"#111111","text":"#ffffff","muted":"#dddddd",'
            '"accent":"#ffcc00"},"heading":{"top":"10%","left":"8%","width":"84%"},'
            '"body":{"top":"35%","left":"8%","width":"84%"},'
            '"text_slots":{"heading_lines":2,"description_lines":3,"bullet_heading_lines":1,"bullet_body_lines":3}}'
        )
        template, data = build_carousel_render_request(
            "• Сириус: Бесплатная смена в Сочи и отбор.",
            contract,
            "carousel",
            "Подпишись",
            "@turantender",
        )
        self.assertEqual((template["width"], template["height"]), (1080, 1350))
        self.assertEqual(data, {})
        self.assertFalse(any(element["type"] == "image" for element in template["elements"]))
        self.assertIn("• Сириус:", next(element["content"] for element in template["elements"] if element["id"] == "heading"))
        self.assertEqual(next(element["content"] for element in template["elements"] if element["id"] == "cta"), "Подпишись")
        self.assertEqual(next(element["content"] for element in template["elements"] if element["id"] == "author"), "@turantender")

    def test_template_passes_social_avatar_to_dynamic_image_field(self):
        template, data = build_carousel_render_request(
            "Одна мысль.",
            '{"avatar":{"left":"8%","top":"92%","width":64,"height":64}}',
            "carousel",
            author="@turantender",
            avatar_url="https://cdn.test/turan.jpg",
        )
        avatar = next(element for element in template["elements"] if element["id"] == "avatar")
        self.assertEqual(data, {"аватар": "https://cdn.test/turan.jpg"})
        self.assertEqual(avatar["variableName"], "аватар")
        self.assertEqual(avatar["content"], "{{аватар}}")
        self.assertEqual((avatar["x"], avatar["y"], avatar["width"], avatar["height"]), (86, 1242, 64, 64))
        self.assertEqual(avatar["borderRadius"], 32)


if __name__ == "__main__":
    unittest.main()
