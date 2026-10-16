"""Contract mutation tests and regressions for production carousel failures."""
import itertools

import pytest

from app.services.carousel_blocks import _is_dangling, validate_deck
from app.services.carousel_editor import validate_plan, build_plan
from test_carousel_editor import SOURCE, SequenceLlm, plan_fixture, deck_fixture


JSON_VALUES = [None, False, 0, 1.5, '', 'unknown', [], {}, [None], {'bad': True}]


@pytest.mark.parametrize('value', JSON_VALUES)
@pytest.mark.parametrize('field', ['frame', 'promise', 'promised_count', 'items', 'beats'])
def test_malformed_plan_fields_fail_with_repairable_errors(field, value):
    plan = plan_fixture()
    plan[field] = value
    try:
        validate_plan(plan, SOURCE)
    except ValueError:
        pass  # A model can repair a contract error; TypeError/KeyError must never escape.


@pytest.mark.parametrize('value', [value for value in JSON_VALUES if value != 'unknown'])
@pytest.mark.parametrize('section,field', [
    ('items', 'id'), ('items', 'idea'), ('items', 'source_quote'),
    ('beats', 'id'), ('beats', 'purpose'), ('beats', 'format'),
    ('beats', 'format_reason'), ('beats', 'transition'), ('beats', 'item_ids'),
])
def test_malformed_nested_plan_fields_are_repairable(section, field, value):
    plan = plan_fixture()
    plan[section][0][field] = value
    with pytest.raises(ValueError):
        validate_plan(plan, SOURCE)


@pytest.mark.parametrize('value', JSON_VALUES)
@pytest.mark.parametrize('field', ['frame', 'slides'])
def test_malformed_deck_fields_are_repairable(field, value):
    deck = deck_fixture()
    deck[field] = value
    with pytest.raises(ValueError):
        validate_deck(deck, '')


@pytest.mark.parametrize('value', JSON_VALUES)
@pytest.mark.parametrize('field', ['type', 'title', 'paragraphs', 'title_lines'])
def test_malformed_slide_fields_are_repairable(field, value):
    deck = deck_fixture()
    deck['slides'][1][field] = value
    try:
        validate_deck(deck, '')
    except ValueError:
        pass


def test_every_contiguous_grouping_of_five_items_is_valid():
    for breaks in itertools.product((False, True), repeat=4):
        plan = plan_fixture()
        beats = [plan['beats'][0]]
        for index, split in enumerate(breaks, 1):
            if split:
                beats.append(plan['beats'][index])
            else:
                beats[-1]['item_ids'].append(f'i{index}')
        plan['beats'] = beats
        assert validate_plan(plan, SOURCE) == plan


@pytest.mark.parametrize('frame', [[], {}, ['instruction'], {'id': 'instruction'}])
def test_bad_frame_response_reaches_llm_retry(frame):
    invalid = plan_fixture()
    invalid['frame'] = frame
    llm = SequenceLlm(invalid, plan_fixture())
    assert build_plan(llm, SOURCE, 'vk') == plan_fixture()
    assert len(llm.calls) == 2


@pytest.mark.parametrize('text', [
    'Вероятность примерно 1 к 1 000 000', 'Карты от 2 до 6',
    'Рост с 10 до 20%', 'Выпуск в 2026', 'Ставка от 5%',
    'Подходит для 3–5', 'Значение −1', 'Изменение +2',
])
def test_numeric_endings_are_complete(text):
    assert not _is_dangling(text)


@pytest.mark.parametrize('text', ['Проверка до', 'Сравнение с…', 'Переход от 2 до', 'Именно для'])
def test_real_dangling_endings_are_still_rejected(text):
    assert _is_dangling(text)


def test_production_103_probability_comparison_is_valid():
    deck = {'frame': 'insight', 'slides': [
        {'type': 'cover', 'title': 'Как доказать знание пароля'},
        {'type': 'comparison', 'title': 'Пароль известен или неизвестен',
         'left_title': 'Пароль известен', 'right_title': 'Пароль неизвестен',
         'left_items': ['Выходите с нужной стороны', 'Открываете секретную дверь'],
         'right_items': ['Вероятность угадать равна 50%', 'После повторов примерно 1 к 1 000 000']},
        {'type': 'cta'},
    ]}
    slides, _ = validate_deck(deck, '')
    assert slides[1]['right_items'] == deck['slides'][1]['right_items']


@pytest.mark.parametrize('value', ['+1', '0', '−1', '50%', '4:5', '9:16', '1 000 000', '10–20'])
def test_numeric_table_cells_are_valid(value):
    deck = {'frame': 'insight', 'slides': [
        {'type': 'cover', 'title': 'Как считать карты'},
        {'type': 'table', 'title': 'Значения карт', 'columns': ['Карты', 'Значение'],
         'rows': [['От 2 до 6', value], ['От 7 до 9', '0']]},
        {'type': 'cta'},
    ]}
    slides, _ = validate_deck(deck, '')
    assert slides[1]['rows'][0][1] == value


@pytest.mark.parametrize('value', ['', '---', 'null', 'NaN', '123 abc'])
def test_numeric_table_exception_does_not_accept_junk(value):
    deck = {'frame': 'insight', 'slides': [
        {'type': 'cover', 'title': 'Как считать карты'},
        {'type': 'table', 'title': 'Значения карт', 'columns': ['Карты', 'Значение'],
         'rows': [['От 2 до 6', value], ['От 7 до 9', '0']]},
        {'type': 'cta'},
    ]}
    with pytest.raises(ValueError):
        validate_deck(deck, '')
