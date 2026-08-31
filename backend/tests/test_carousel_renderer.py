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
        )
        self.assertEqual((template["width"], template["height"]), (1080, 1350))
        self.assertEqual(data, {})
        self.assertFalse(any(element["type"] == "image" for element in template["elements"]))
        self.assertIn("• Сириус:", next(element["content"] for element in template["elements"] if element["id"] == "heading"))
        self.assertEqual(next(element["content"] for element in template["elements"] if element["id"] == "cta"), "Подпишись")


if __name__ == "__main__":
    unittest.main()
