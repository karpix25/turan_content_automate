import datetime
import unittest

from app.integrations.postmypost_carousel import build_carousel_payload
from app.services.carousel_pipeline import build_package_prompts, build_slide_prompts, normalize_master_text, split_master_text, suggest_package_slide_count
from app.services.carousel_layout import build_layout_instruction, build_slide_text_spec, parse_text_slots, split_slide_content
from app.services.carousel_copy import build_reference_rewrite_prompt, is_russian_text, strip_source_cta
from app.services.design_composition import analyze_design_composition, build_design_composition_analysis_prompt
from app.services.project_cta_settings import normalize_ctas
from app.services.reference_sources import extract_reference_post, resolve_project_platform_accounts
from app.utils.platform_utils import _normalize_platform_code
from app import models


class CarouselPipelineTests(unittest.TestCase):
    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def all(self):
            return list(self.rows)

    class _Db:
        def __init__(self, rows):
            self.rows = rows

        def query(self, _model):
            return CarouselPipelineTests._Query(self.rows)

    class _Pmp:
        def get_accounts(self, project_id):
            self.project_id = project_id
            return [
                {"id": 11, "chanel_id": 1},
                {"id": 12, "chanel_id": 1},
                {"id": 13, "chanel_id": 2},
            ]

        def get_channels(self):
            return [{"id": 1, "code": "instagram"}, {"id": 2, "code": "telegram"}]

    def test_project_accounts_include_only_enabled_accounts_and_telegram(self):
        rows = [models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=11, enabled=True),
                models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=12, enabled=False),
                models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=13, enabled=True)]
        self.assertEqual(
            resolve_project_platform_accounts(7, self._Pmp(), self._Db(rows), 1),
            {"instagram": [11], "telegram": [13]},
        )

    def test_one_master_text_becomes_platform_specific_final_cta(self):
        text = "Первый тезис. Второй тезис. Третий тезис."
        prompts = build_slide_prompts(text, 3, "instagram", "Подпишись")
        self.assertEqual(len(prompts), 3)
        self.assertIn("СПЕЦИФИКАЦИЯ ТЕКСТА СЛАЙДА", prompts[0])
        self.assertIn("ЗАГОЛОВОК", prompts[0])
        self.assertIn("Первый\nтезис", prompts[0])
        self.assertNotIn("Второй тезис", prompts[0])
        self.assertNotIn("Подпишись", prompts[0])
        self.assertIn("Подпишись", prompts[-1])
        self.assertIn("отрисуй CTA дословно", prompts[-1])

    def test_split_text_respects_safe_slide_limit(self):
        slides = split_master_text("Один. Два. Три. Четыре.", 20)
        self.assertLessEqual(len(slides), 10)
        self.assertTrue(all(slides))

    def test_split_text_keeps_sentence_boundaries_and_removes_numbering(self):
        slides = split_master_text("1. Первая мысль.\n\n2. Вторая мысль.\n\n3. Третья мысль.", 3)
        self.assertEqual(slides, ["Первая мысль.", "• Вторая мысль.", "• Третья мысль."])
        self.assertNotIn("1.", normalize_master_text("1. Текст"))
        self.assertEqual(normalize_master_text("1-ое Сириус. 2-ое — Физтехшкола."), "• Сириус. • Физтехшкола.")

    def test_inline_numbering_becomes_separate_thoughts(self):
        self.assertEqual(
            split_master_text("1. Первый тезис. 2. Второй тезис. 3. Третий тезис.", 1),
            ["Первый тезис.", "• Второй тезис.", "• Третий тезис."],
        )

    def test_nested_variants_become_separate_thoughts(self):
        self.assertEqual(
            split_master_text("Где готовиться? Первый вариант — Сириус: смена в Сочи. Второй — Физтех: дистанционно.", 1),
            ["Где готовиться?", "• Сириус: смена в Сочи.", "• Физтех: дистанционно."],
        )

    def test_split_text_does_not_merge_independent_thoughts(self):
        self.assertEqual(
            split_master_text("Первый тезис. Второй тезис. Третий тезис.", 1),
            ["Первый тезис.", "Второй тезис.", "Третий тезис."],
        )

    def test_split_text_keeps_bullet_description_together(self):
        text = "Варианты подготовки. 1-ое Сириус. Бесплатная смена в Сочи. 2-ое Физтехшкола. Дистанционные занятия."
        slides = split_master_text(text, 3, 20)
        self.assertEqual(slides, [
            "Варианты подготовки.",
            "• Сириус. Бесплатная смена в Сочи.",
            "• Физтехшкола. Дистанционные занятия.",
        ])

    def test_split_text_does_not_break_one_bullet_into_two_slides(self):
        text = "Варианты подготовки. 1-ое Сириус. Бесплатная смена в Сочи. 2-ое Физтехшкола. Дистанционные занятия."
        slides = split_master_text(text, 5, 20)
        self.assertEqual(slides, [
            "Варианты подготовки.",
            "• Сириус. Бесплатная смена в Сочи.",
            "• Физтехшкола. Дистанционные занятия.",
        ])

    def test_long_bullet_is_split_into_short_thought_blocks(self):
        text = "• Метапознание важно. Оно помогает принимать решения. Навык можно тренировать. Делайте это каждый день."
        self.assertEqual(split_master_text(text, 1), [
            "• Метапознание важно. Оно помогает принимать решения.",
            "• Навык можно тренировать. Делайте это каждый день.",
        ])

    def test_story_prompt_has_story_format_and_word_limit(self):
        prompts = build_slide_prompts("раз два три четыре пять шесть семь восемь девять десять", 2, "instagram", "Смотри подробнее", "story")
        self.assertIn("1080x1920", prompts[0])
        self.assertIn("весь текст отрисуй непосредственно внутри него", prompts[0])
        self.assertIn("не разрывай слова", prompts[0])
        self.assertIn("Не используй нумерованные списки", prompts[0])
        self.assertIn("весь текст слайда целиком", prompts[0])
        self.assertIn("Жёсткий невидимый каркас", prompts[0])
        self.assertNotIn("около 23% кадра", prompts[0])
        self.assertIn("Исходный CTA и любой текст с дизайн-референса считать чужими", prompts[0])
        self.assertNotIn("будет наложен программно", prompts[0])

    def test_carousel_prompt_uses_reference_derived_grid(self):
        prompt = build_slide_prompts("Заголовок. Основной текст.", 2, "vk", "Подпишись")[0]
        self.assertIn("Жёсткий невидимый каркас", prompt)
        self.assertIn("ровно 3 строки", prompt)
        self.assertNotIn("около 8% кадра", prompt)

    def test_layout_contract_uses_reference_line_counts_without_raw_json(self):
        contract = '{"text_slots":{"heading_lines":2,"description_lines":5,"bullet_heading_lines":1,"bullet_body_lines":3}}'
        self.assertEqual(parse_text_slots(contract, "carousel"), {
            "heading_lines": 2,
            "description_lines": 5,
            "bullet_heading_lines": 1,
            "bullet_body_lines": 3,
        })
        instruction = build_layout_instruction(contract, "carousel")
        self.assertIn("ровно 2 строки", instruction)
        self.assertIn("описание буллета — ровно 3 строки", instruction)
        self.assertNotIn("text_slots", instruction)

    def test_layout_instruction_passes_reference_positions_without_raw_contract(self):
        contract = '{"heading":{"top":"12%","left":"8%","align":"left"},"body":{"top":"38%","width":"84%"},"cta":{"bottom":"8%"}}'
        instruction = build_layout_instruction(contract, "carousel")
        self.assertIn("Зона заголовка: top=12%, left=8%, align=left.", instruction)
        self.assertIn("Зона описания: top=38%, width=84%.", instruction)
        self.assertIn("Зона CTA: bottom=8%.", instruction)
        self.assertNotIn('"heading"', instruction)

    def test_slide_content_has_one_thought_and_explicit_heading_body(self):
        content = split_slide_content("• Сириус. Бесплатная смена в Сочи и отбор.")
        self.assertEqual(content, {
            "heading": "Сириус.",
            "body": "Бесплатная смена в Сочи и отбор.",
            "is_bullet": True,
        })
        self.assertEqual(split_slide_content("• Сириус: смена в Сочи."), {
            "heading": "Сириус:",
            "body": "смена в Сочи.",
            "is_bullet": True,
        })
        spec = build_slide_text_spec("• Сириус. Бесплатная смена в Сочи и отбор.", None, "carousel")
        self.assertIn("РОВНО ОДНА МЫСЛЬ НА СЛАЙД", spec)
        self.assertIn("ЗАГОЛОВОК (1 строку): • Сириус.", spec)
        self.assertIn("ОПИСАНИЕ (4 строки): Бесплатная\nсмена", spec)
        self.assertIn("Сохрани эти переносы строк и эти зоны буквально", spec)

    def test_zero_heading_slot_keeps_story_content_in_one_body_block(self):
        contract = '{"text_slots":{"heading_lines":0,"description_lines":3,"bullet_heading_lines":0,"bullet_body_lines":0}}'
        spec = build_slide_text_spec("Первое предложение. Второе предложение.", contract, "story")
        self.assertIn("ЗАГОЛОВОК (0 строк):", spec)
        self.assertIn("ОПИСАНИЕ (3 строки): Первое", spec)
        self.assertIn("предложение.", spec)

    def test_story_without_heading_uses_description_slot_for_bullets(self):
        contract = '{"text_slots":{"heading_lines":0,"description_lines":10,"bullet_heading_lines":0,"bullet_body_lines":0}}'
        spec = build_slide_text_spec("• Сириус: смена в Сочи.", contract, "story")
        self.assertIn("ОПИСАНИЕ (10 строк): Сириус:", spec)
        self.assertIn("смена", spec)
        self.assertIn("Сочи.", spec)
        self.assertNotIn("ОПИСАНИЕ (0 строк): нет", spec)

    def test_composition_contract_is_reused_in_every_slide_prompt(self):
        contract = '{"heading":{"top":"12%"},"body":{"top":"38%"},"cta":{"bottom":"8%"}}'
        prompts = build_slide_prompts("Заголовок. Основной текст. Ещё текст.", 3, "vk", "Подпишись", composition_contract=contract)
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all("Жёсткий невидимый каркас" in prompt for prompt in prompts))
        self.assertTrue(all('"heading"' not in prompt for prompt in prompts))
        self.assertTrue(all("невидимая техническая разметка" in prompt for prompt in prompts))
        self.assertTrue(all("заменено на маркер «•»" in prompt for prompt in prompts))

    def test_design_composition_analysis_returns_compact_contract(self):
        class FakeLlm:
            def _complete(self, messages, temperature):
                self.messages = messages
                self.temperature = temperature
                return '```json\n{"heading":{"top":"12%"}}\n```'

        client = FakeLlm()
        contract = analyze_design_composition(client, ["https://example.com/reference.png"], "carousel")
        self.assertEqual(contract, '{"heading":{"top":"12%"}}')
        self.assertEqual(client.temperature, 0.1)
        self.assertEqual(len(build_design_composition_analysis_prompt("carousel", ["https://example.com/reference.png"])), 2)

    def test_source_cta_is_removed_before_slide_composition(self):
        text = "Первый тезис. Остальные 7 мест у меня в Телеграм. Второй тезис."
        self.assertEqual(strip_source_cta(text), "Первый тезис. Второй тезис.")

    def test_russian_copy_rejects_latin_words(self):
        self.assertTrue(is_russian_text("Текст для пяти слайдов 5"))
        self.assertFalse(is_russian_text("Русский text"))
        self.assertFalse(is_russian_text("English text"))

    def test_package_count_fits_both_formats(self):
        self.assertEqual(suggest_package_slide_count("Один короткий тезис."), 1)
        self.assertEqual(suggest_package_slide_count(" ".join(["слово"] * 30)), 3)

    def test_source_prompt_does_not_allow_style_to_change_topic(self):
        prompt = build_reference_rewrite_prompt(
            [{"content_kind": "video", "title": "А ты?", "caption": "А ты?", "transcript": "Прощать или не прощать?", "body": "А ты?"}],
            "Автор пишет о тендерах и бизнесе",
        )
        text = prompt[1]["content"][0]["text"]
        self.assertIn("единственный источник смысла и фактов", text)
        self.assertIn("не добавляй бизнес", text)
        self.assertIn("Прощать или не прощать?", text)

    def test_package_reuses_body_slides_and_varies_only_final_cta_prompts(self):
        shared, finals = build_package_prompts(
            "Первый тезис. Второй тезис. Третий тезис.",
            3,
            "carousel",
            ["instagram", "vk"],
            {"instagram": "Смотри Instagram", "vk": "Переходи в VK"},
        )
        self.assertEqual(len(shared), 2)
        self.assertEqual(set(finals), {"instagram", "vk"})
        self.assertTrue(all("CTA не добавляй" in prompt for prompt in shared))
        self.assertIn("Смотри Instagram", finals["instagram"])
        self.assertIn("Переходи в VK", finals["vk"])
        self.assertIn("В нижней части слайда отрисуй CTA дословно", finals["instagram"])

    def test_package_reuses_custom_image_instructions_on_all_slides(self):
        shared, finals = build_package_prompts(
            "Первый тезис. Второй тезис. Третий тезис.",
            3,
            "carousel",
            ["instagram", "vk"],
            {},
            "Единая зелёная палитра и мягкий свет",
        )
        self.assertTrue(all("Единая зелёная палитра и мягкий свет" in prompt for prompt in shared))
        self.assertTrue(all("Единая зелёная палитра и мягкий свет" in prompt for prompt in finals.values()))

    def test_payload_keeps_one_caption_and_many_files(self):
        payload = build_carousel_payload(
            project_id=7,
            account_ids=[12, 12, 13],
            post_at=datetime.datetime(2026, 8, 23, 12, tzinfo=datetime.timezone.utc),
            file_ids=[101, 102, 103],
            content="Единый текст",
        )
        self.assertEqual(payload["account_ids"], [12, 13])
        self.assertEqual(payload["details"][0]["file_ids"], [101, 102, 103])
        self.assertEqual(payload["details"][0]["content"], "Единый текст")

    def test_cta_settings_ignore_unsupported_platforms(self):
        self.assertEqual(normalize_ctas({"instagram": "Ок", "youtube": "Нет"}), {"instagram": "Ок"})

    def test_telegram_is_supported_for_project_cta(self):
        self.assertEqual(normalize_ctas({"telegram": "Читать канал"}), {"telegram": "Читать канал"})

    def test_telegram_channel_code_is_normalized(self):
        self.assertEqual(_normalize_platform_code("telegram_channel"), "telegram")

    def test_reference_post_normalization_keeps_fresh_metadata(self):
        channel = models.ReferenceChannel(
            id=4,
            user_id=1,
            project_id=2,
            platform="youtube",
            source_url="https://youtube.com/@author",
        )
        post = extract_reference_post(channel, {
            "videoId": "abcdefghijk",
            "title": "Новый смысл",
            "publishedAt": "2026-08-23T10:00:00Z",
            "viewCount": 42,
        })
        self.assertEqual(post["source_url"], "https://youtube.com/@author")
        self.assertEqual(post["view_count"], 42)
        self.assertIsNotNone(post["published_at"])

    def test_reference_post_normalization_unwraps_instagram_media(self):
        channel = models.ReferenceChannel(id=5, user_id=1, project_id=2, platform="instagram", source_url="https://instagram.com/author")
        post = extract_reference_post(channel, {
            "media": {
                "id": "123_456",
                "code": "ABC123",
                "url": "https://www.instagram.com/reel/ABC123/",
                "caption": {"text": "Свежий пост"},
                "created_at": "2026-08-27T10:00:00Z",
                "play_count": 99,
            },
        })
        self.assertEqual(post["external_id"], "123_456")
        self.assertEqual(post["title"], "Свежий пост")
        self.assertEqual(post["view_count"], 99)


if __name__ == "__main__":
    unittest.main()
