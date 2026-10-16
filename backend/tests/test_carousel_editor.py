import copy
import json
import unittest
from unittest.mock import patch

from app.services.carousel_editor import PLAN_FORMAT, build_editorial_deck, build_plan, validate_plan, validate_assignment, review_deck
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


def assignments_fixture():
    return {'assignments': [{'beat_id': f'b{i}', 'item_ids': [f'i{i}']} for i in range(5)]}


class SequenceLlm:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.options = []

    def _complete(self, prompt, **kwargs):
        self.calls.append(copy.deepcopy(prompt))
        self.options.append(copy.deepcopy(kwargs))
        return json.dumps(next(self.responses), ensure_ascii=False)


class EditorialTests(unittest.TestCase):
    def test_plan_schema_requires_nonempty_assignments(self):
        properties = PLAN_FORMAT['json_schema']['schema']['properties']
        self.assertEqual(properties['items']['minItems'], 1)
        self.assertEqual(properties['beats']['minItems'], 1)
        self.assertEqual(properties['beats']['maxItems'], 5)
        self.assertEqual(properties['beats']['items']['properties']['item_ids']['minItems'], 1)

    def test_invalid_plan_assignments_are_repaired_without_rewriting_content(self):
        for invalid_ids in (None, [], 'i0', [0], [''], ['unknown'], ['i1']):
            with self.subTest(item_ids=invalid_ids):
                invalid = plan_fixture()
                invalid['beats'][0]['item_ids'] = invalid_ids
                llm = SequenceLlm(invalid, assignments_fixture())
                self.assertEqual(build_plan(llm, SOURCE, 'vk'), plan_fixture())
                self.assertEqual(len(llm.calls), 2)
                schema = llm.options[1]['response_format']['json_schema']['schema']
                entry = schema['properties']['assignments']['items']['properties']
                self.assertEqual(entry['item_ids']['items']['enum'], [f'i{i}' for i in range(5)])
                self.assertEqual(entry['beat_id']['enum'], [f'b{i}' for i in range(5)])

    def test_missing_item_ids_are_repaired_and_deck_still_passes_review(self):
        invalid = plan_fixture()
        del invalid['beats'][0]['item_ids']
        llm = SequenceLlm(invalid, assignments_fixture(), deck_fixture(), review_fixture())
        deck, frame = build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual(len(deck), 7)
        self.assertEqual(frame['editorial_plan'], plan_fixture())
        self.assertTrue(frame['editorial_review']['approved'])

    def test_assignment_repair_preserves_grouped_items(self):
        expected = plan_fixture()
        expected['beats'][0]['item_ids'] = ['i0', 'i1']
        expected['beats'].pop(1)
        invalid = copy.deepcopy(expected)
        invalid['beats'][0]['item_ids'] = []
        repair = {'assignments': [{'beat_id': b['id'], 'item_ids': b['item_ids']} for b in expected['beats']]}
        self.assertEqual(build_plan(SequenceLlm(invalid, repair), SOURCE, 'vk'), expected)

    def test_failed_assignment_repairs_have_a_bounded_budget(self):
        invalid = plan_fixture()
        invalid['beats'][0]['item_ids'] = []
        bad_repair = assignments_fixture()
        bad_repair['assignments'][0]['item_ids'] = ['unknown']
        llm = SequenceLlm(invalid, bad_repair, invalid, bad_repair)
        with self.assertRaisesRegex(ValueError, 'смысловой план'):
            build_plan(llm, SOURCE, 'vk')
        self.assertEqual(len(llm.calls), 4)

    def test_malformed_assignment_repairs_trigger_full_replanning(self):
        invalid = plan_fixture()
        invalid['beats'][0]['item_ids'] = []
        reordered = assignments_fixture()
        reordered['assignments'].reverse()
        missing = assignments_fixture()
        missing['assignments'].pop()
        for repair in ({}, {'assignments': [None]}, reordered, missing, 'not an object'):
            with self.subTest(repair=repair):
                llm = SequenceLlm(invalid, repair, plan_fixture())
                self.assertEqual(build_plan(llm, SOURCE, 'vk'), plan_fixture())
                self.assertEqual(len(llm.calls), 3)

    def test_invalid_source_evidence_shape_requires_full_replanning(self):
        invalid = plan_fixture()
        invalid['items'][4]['source_quote'] = None
        llm = SequenceLlm(invalid, plan_fixture())
        self.assertEqual(build_plan(llm, SOURCE, 'vk'), plan_fixture())
        self.assertEqual(llm.options[1]['response_format'], PLAN_FORMAT)

    def test_inexact_source_quotes_are_reselected_without_changing_ideas(self):
        invalid = plan_fixture()
        invalid['items'][0]['source_quote'] = 'Сначала сделайте паузу'
        quotes = SOURCE.split('. ')
        quotes = [quote if quote.endswith('.') else quote + '.' for quote in quotes]
        evidence = {'evidence': [{'item_id': f'i{i}', 'quote_id': f'quote_{i+1}'} for i in range(5)]}
        llm = SequenceLlm(invalid, evidence)
        repaired = build_plan(llm, SOURCE, 'vk')
        self.assertEqual(repaired['beats'], invalid['beats'])
        self.assertEqual([item['idea'] for item in repaired['items']], PHRASES)
        self.assertEqual([item['source_quote'] for item in repaired['items']], quotes)
        schema = llm.options[1]['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['evidence']['items']['properties']['quote_id']['enum'],
                         [f'quote_{i+1}' for i in range(5)])

    def test_evidence_and_assignment_can_both_be_repaired_in_one_plan(self):
        invalid = plan_fixture()
        invalid['items'][0]['source_quote'] = 'Выдумка'
        invalid['beats'][0]['item_ids'] = []
        quotes = [part.strip() + '.' for part in SOURCE.rstrip('.').split('. ')]
        evidence = {'evidence': [{'item_id': f'i{i}', 'quote_id': f'quote_{i+1}'} for i in range(5)]}
        llm = SequenceLlm(invalid, evidence, assignments_fixture())
        repaired = build_plan(llm, SOURCE, 'vk')
        self.assertEqual(repaired['beats'], plan_fixture()['beats'])
        self.assertEqual(len(llm.calls), 3)

    def test_invented_repair_evidence_is_not_accepted(self):
        invalid = plan_fixture()
        invalid['items'][0]['source_quote'] = 'Выдумка'
        evidence = {'evidence': [{'item_id': f'i{i}', 'quote_id': 'invented'} for i in range(5)]}
        llm = SequenceLlm(invalid, evidence, invalid, evidence)
        with self.assertRaisesRegex(ValueError, 'дословно выбрать'):
            build_plan(llm, SOURCE, 'vk')
        self.assertEqual(len(llm.calls), 4)

    def test_llm_selects_five_beats_even_for_short_source(self):
        llm = SequenceLlm(plan_fixture(), deck_fixture(), review_fixture())
        deck, frame = build_platform_deck(llm, SOURCE, 'vk', 'Сохраните')
        self.assertEqual(len(deck), 7)
        self.assertEqual([s['kicker'] for s in deck[1:-1]], [f'Приём {i}/5' for i in range(1, 6)])
        self.assertEqual(len(llm.calls), 3)
        self.assertTrue(frame['editorial_review']['approved'])
        self.assertEqual(frame['editorial_plan']['promised_count'], 5)
        schema = llm.options[1]['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['frame']['enum'], ['instruction'])
        self.assertEqual(schema['properties']['slides']['minItems'], 7)
        self.assertEqual(schema['properties']['slides']['maxItems'], 7)
        variants = schema['properties']['slides']['items']['anyOf']
        self.assertEqual([v['properties']['type']['enum'][0] for v in variants],
                         ['cover', 'text', 'text', 'text', 'text', 'text', 'cta'])

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

    def test_count_mismatch_repairs_only_the_cover_promise(self):
        invalid = plan_fixture()
        invalid['promised_count'] = 3
        invalid['promise'] = 'Три приёма для разговора'
        for count, promise in ((5, 'Пять приёмов для разговора'), (None, 'Как вести разговор')):
            with self.subTest(count=count):
                llm = SequenceLlm(invalid, {'promise': promise, 'promised_count': count})
                result = build_plan(llm, SOURCE, 'vk')
                self.assertEqual(result['promise'], promise)
                self.assertEqual(result['promised_count'], count)
                self.assertEqual(result['items'], invalid['items'])
                self.assertEqual(result['beats'], invalid['beats'])
                schema = llm.options[1]['response_format']['json_schema']['schema']
                self.assertEqual(schema['properties']['promised_count']['enum'], [5, None])

    def test_invalid_promise_repairs_have_bounded_budget(self):
        invalid = plan_fixture()
        invalid['promised_count'] = 3
        repair = {'promise': 'Три приёма', 'promised_count': 3}
        llm = SequenceLlm(invalid, repair, invalid, repair)
        with self.assertRaisesRegex(ValueError, 'promised_count'):
            build_plan(llm, SOURCE, 'vk')
        self.assertEqual(len(llm.calls), 4)

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

    def test_long_title_and_wrong_format_are_repaired_without_rewriting_other_slides(self):
        original = deck_fixture()
        invalid = copy.deepcopy(original)
        invalid['slides'][1]['title'] = 'Заголовок оказался слишком длинным поэтому его нужно сейчас сократить'
        invalid['slides'][3] = {
            'type': 'checklist', 'beat_id': 'b2', 'title': 'Уточните смысл',
            'items': ['Уточните смысл.', 'Переспросите собеседника.'],
        }
        # Assignment checks detect the wrong type first, then the long title.
        llm = SequenceLlm(plan_fixture(), invalid, original['slides'][3],
                          original['slides'][1], review_fixture())
        deck, _ = build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual([s['title'] for s in deck[:-1]], [s['title'] for s in original['slides'][:-1]])
        self.assertEqual(deck[2]['paragraphs'], original['slides'][2]['paragraphs'])
        self.assertEqual(deck[4]['paragraphs'], original['slides'][4]['paragraphs'])
        self.assertEqual(len(llm.calls), 5)
        for call_index, beat_id in ((2, 'b2'), (3, 'b0')):
            schema = llm.options[call_index]['response_format']['json_schema']['schema']
            self.assertEqual(schema['properties']['type']['enum'], ['text'])
            self.assertEqual(schema['properties']['beat_id']['enum'], [beat_id])
        self.assertIn('максимум 8', llm.calls[3][-1]['content'])

    def test_malformed_slide_repair_is_retried_locally(self):
        original = deck_fixture()
        invalid = copy.deepcopy(original)
        invalid['slides'][1]['title'] = 'Заголовок оказался слишком длинным поэтому его нужно сейчас сократить'
        llm = SequenceLlm(plan_fixture(), invalid, 'Не объект', original['slides'][1], review_fixture())
        deck, _ = build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual(deck[1]['title'], original['slides'][1]['title'])
        self.assertEqual(len(llm.calls), 5)
        self.assertEqual(llm.options[2]['response_format']['type'], 'json_schema')
        self.assertEqual(llm.options[3]['response_format']['type'], 'json_schema')

    def test_missing_beat_ids_are_restored(self):
        payload = deck_fixture()
        for slide in payload['slides'][1:-1]:
            slide.pop('beat_id')
        deck, _ = validate_assignment(payload, plan_fixture(), '')
        self.assertEqual([s['beat_id'] for s in deck[1:-1]], [f'b{i}' for i in range(5)])

    def test_failed_slide_repairs_have_a_bounded_budget(self):
        invalid = deck_fixture()
        invalid['slides'][1]['title'] = 'Заголовок оказался слишком длинным поэтому его нужно сейчас сократить'
        responses = [plan_fixture()]
        for _ in range(3):
            responses.extend([invalid, invalid['slides'][1], invalid['slides'][1]])
        llm = SequenceLlm(*responses)
        with self.assertRaisesRegex(ValueError, 'длиннее 8 слов'):
            build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual(len(llm.calls), 10)

    def test_approved_without_evidence_is_rejected(self):
        review = review_fixture()
        review['coverage'].pop()
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'Не все пункты'):
            review_deck(SequenceLlm(review, review), SOURCE, plan_fixture(), deck)

    def test_editor_cannot_invent_visible_evidence(self):
        review = review_fixture()
        review['coverage'][0]['evidence'] = 'Этой фразы нет на слайде'
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'отсутствует'):
            review_deck(SequenceLlm(review, review), SOURCE, plan_fixture(), deck)

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
            review_deck(SequenceLlm(review, review), SOURCE, plan_fixture(), deck)

    def test_review_metadata_is_repaired_without_rewriting_deck(self):
        review = review_fixture()
        review['coverage'][0]['evidence'] = 'Пересказ вместо дословной цитаты'
        llm = SequenceLlm(plan_fixture(), deck_fixture(), review, review_fixture())
        deck, frame = build_editorial_deck(llm, SOURCE, 'vk', '')
        self.assertEqual(len(llm.calls), 4)
        self.assertEqual(llm.options[2]['response_format'], llm.options[3]['response_format'])
        self.assertTrue(frame['editorial_review']['approved'])
        self.assertEqual(deck[1]['paragraphs'], deck_fixture()['slides'][1]['paragraphs'])

    def test_review_selects_exact_visible_excerpts_by_id(self):
        review = review_fixture()
        for index, entry in enumerate(review['coverage'], 2):
            del entry['evidence']
            entry['evidence_id'] = f'slide_{index}_part_2'
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        result = review_deck(SequenceLlm(review), SOURCE, plan_fixture(), deck)
        self.assertEqual([entry['evidence'] for entry in result['coverage']],
                         [phrase.capitalize() + '.' for phrase in PHRASES])

    def test_evidence_reference_cannot_point_at_another_slide(self):
        review = review_fixture()
        review['coverage'][0]['evidence_id'] = 'slide_3_part_2'
        deck, _ = validate_assignment(deck_fixture(), plan_fixture(), '')
        with self.assertRaisesRegex(ValueError, 'назначенном слайде'):
            review_deck(SequenceLlm(review, review), SOURCE, plan_fixture(), deck)

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

    def test_null_title_lines_use_renderer_balancing(self):
        deck = deck_fixture()
        deck['slides'][0]['title_lines'] = None
        slides, _ = validate_deck(deck, '')
        self.assertNotIn('title_lines', slides[0])
