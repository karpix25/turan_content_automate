import copy
import json
import unittest
from unittest.mock import patch

from app.services.carousel_editor import build_editorial_deck, validate_plan, validate_assignment, review_deck
from app.services.carousel_blocks import build_platform_deck, validate_deck

SOURCE = 'Первый приём: сделайте паузу. Второй приём: задайте вопрос. Третий приём: уточните смысл. Четвёртый приём: приведите пример. Пятый приём: подведите итог.'
PHRASES = ['сделайте паузу', 'задайте вопрос', 'уточните смысл', 'приведите пример', 'подведите итог']


def plan_fixture():
    return {'frame': 'instruction', 'promise': 'Пять приёмов для разговора', 'promised_count': 5,
            'items': [{'id': f'i{i}', 'idea': phrase, 'source_quote': phrase} for i, phrase in enumerate(PHRASES)],
            'beats': [{'id': f'b{i}', 'purpose': phrase, 'item_ids': [f'i{i}'], 'format': 'text',
                       'format_reason': 'Самостоятельное объяснение', 'transition': 'Следующий приём'} for i, phrase in enumerate(PHRASES)]}


def deck_fixture():
    return {'frame': 'instruction', 'slides': [
        {'type': 'cover', 'title': 'Пять приёмов для разговора'},
        *[{'type': 'text', 'beat_id': f'b{i}', 'kicker': f'Приём {i+1}/5',
           'title': phrase.capitalize(), 'paragraphs': [phrase.capitalize() + '.']} for i, phrase in enumerate(PHRASES)],
        {'type': 'cta', 'cta': ''}]}


def review_fixture():
    return {'approved': True, 'issues': [], 'coverage': [
        {'item_id': f'i{i}', 'slide_index': i+2, 'evidence': phrase.capitalize() + '.'} for i, phrase in enumerate(PHRASES)]}


class SequenceLlm:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def _complete(self, prompt, **kwargs):
        self.calls.append(copy.deepcopy(prompt))
        return json.dumps(next(self.responses), ensure_ascii=False)


class EditorialTests(unittest.TestCase):
    def test_llm_selects_five_beats_even_for_short_source(self):
        llm = SequenceLlm(plan_fixture(), deck_fixture(), review_fixture())
        deck, frame = build_platform_deck(llm, SOURCE, 'vk', 'Сохраните')
        self.assertEqual(len(deck), 7)
        self.assertEqual([s['kicker'] for s in deck[1:-1]], [f'Приём {i}/5' for i in range(1, 6)])
        self.assertEqual(len(llm.calls), 3)
        self.assertTrue(frame['editorial_review']['approved'])
        self.assertEqual(frame['editorial_plan']['promised_count'], 5)

    def test_plan_cannot_lose_a_promised_item(self):
        plan = plan_fixture()
        plan['beats'].pop()
        with self.assertRaisesRegex(ValueError, 'Все items'):
            validate_plan(plan, SOURCE)

    def test_plan_cannot_invent_source_evidence(self):
        plan = plan_fixture()
        plan['items'][0]['source_quote'] = 'Несуществующий факт'
        with self.assertRaisesRegex(ValueError, 'дословная'):
            validate_plan(plan, SOURCE)

    def test_plan_count_matches_extracted_items(self):
        plan = plan_fixture()
        plan['promised_count'] = 6
        with self.assertRaisesRegex(ValueError, 'promised_count'):
            validate_plan(plan, SOURCE)

    def test_slide_assignment_cannot_reorder_beats(self):
        deck = deck_fixture()
        deck['slides'][1], deck['slides'][2] = deck['slides'][2], deck['slides'][1]
        with self.assertRaisesRegex(ValueError, 'beat_id'):
            validate_assignment(deck, plan_fixture(), '')

    def test_editor_criticism_goes_back_to_writer(self):
        rejected = {'approved': False, 'issues': ['На обложке пять приёмов, пятый не объяснён'], 'coverage': []}
        llm = SequenceLlm(plan_fixture(), deck_fixture(), rejected, deck_fixture(), review_fixture())
        deck, _ = build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual(len(deck), 7)
        self.assertIn('пятый не объяснён', llm.calls[3][-1]['content'])

    def test_approved_without_evidence_is_rejected(self):
        review = review_fixture()
        review['coverage'].pop()
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'Не все пункты'):
            review_deck(SequenceLlm(review), SOURCE, plan_fixture(), deck)

    def test_editor_cannot_invent_visible_evidence(self):
        review = review_fixture()
        review['coverage'][0]['evidence'] = 'Этой фразы нет на слайде'
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'отсутствует'):
            review_deck(SequenceLlm(review), SOURCE, plan_fixture(), deck)

    def test_repeated_editor_rejection_stops_generation(self):
        rejected = {'approved': False, 'issues': ['Обещанные пункты не раскрыты'], 'coverage': []}
        llm = SequenceLlm(plan_fixture(), deck_fixture(), rejected, deck_fixture(), rejected, deck_fixture(), rejected)
        with self.assertRaisesRegex(ValueError, 'не прошла редактуру'):
            build_editorial_deck(llm, SOURCE, 'vk', '')

    def test_cover_does_not_count_as_delivery(self):
        review = review_fixture()
        review['coverage'][0]['slide_index'] = 1
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'основном слайде'):
            review_deck(SequenceLlm(review), SOURCE, plan_fixture(), deck)

    def test_failed_editorial_does_not_call_mechanical_fallback(self):
        llm = SequenceLlm({}, {})
        with patch('app.services.carousel_blocks.build_fallback_deck') as fallback:
            with self.assertRaisesRegex(ValueError, 'смысловой план'):
                build_platform_deck(llm, SOURCE, 'vk', '')
            fallback.assert_not_called()

    def test_model_paragraphs_are_preserved(self):
        deck = deck_fixture()
        deck['slides'][1]['paragraphs'] = ['Первая мысль. Второе предложение.', 'Отдельное пояснение.']
        slides, _ = validate_deck(deck, '')
        self.assertEqual(slides[1]['paragraphs'], deck['slides'][1]['paragraphs'])
        self.assertEqual(slides[1]['body'], 'Первая мысль. Второе предложение. Отдельное пояснение.')

    def test_title_lines_cannot_change_title_or_end_in_preposition(self):
        deck = deck_fixture()
        deck['slides'][0]['title_lines'] = ['Пять приёмов', 'для разговора']
        validate_deck(deck, '')
        deck['slides'][0]['title_lines'] = ['Пять приёмов для', 'разговора']
        with self.assertRaisesRegex(ValueError, 'предлог'):
            validate_deck(deck, '')
