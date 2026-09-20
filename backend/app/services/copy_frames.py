"""Library of copywriting frames for carousel decks.

A frame is a proven narrative structure (mistakes, before/after, myths,
instruction, insight). The pipeline assigns one frame per deck and the LLM
fills its slide roles with content from the source — so carousels get a
deliberate dramatic arc instead of a random slide order.
"""

import random

COPY_FRAMES = [
    {
        "id": "mistakes",
        "name": "Ошибки и ловушки",
        "description": "Разбор типовых ошибок: читатель узнаёт себя и получает план исправления.",
        "roles": [
            "обложка-хук: назови самую болезненную ошибку или её последствие",
            "обостри проблему: масштаб, цена ошибки или неожиданный факт (stat или text)",
            "перечисли типовые ошибки (checklist) или покажи «как делают все / как делают сильные» (comparison)",
            "объясни корень: почему люди совершают эти ошибки (text)",
            "дай правильный порядок действий (steps или checklist)",
        ],
    },
    {
        "id": "transformation",
        "name": "До / После",
        "description": "Контраст текущей и желаемой ситуации — структура, которая продаёт изменение.",
        "roles": [
            "обложка: обещание трансформации",
            "точка А: как делают большинство и к чему это приводит (text)",
            "сравнение точек А и Б (comparison)",
            "конкретика сдвига: цифра или факт (stat)",
            "шаги перехода из А в Б (steps)",
        ],
    },
    {
        "id": "myths",
        "name": "Мифы и правда",
        "description": "Разрушение распространённых заблуждений с опорой на факты.",
        "roles": [
            "обложка: главный миф в виде вопроса или смелого утверждения",
            "сравнение «миф / правда» (comparison)",
            "почему миф живёт: причина заблуждения (text)",
            "как на самом деле: факты и правила (checklist или stat)",
            "что читателю сделать по-другому (steps)",
        ],
    },
    {
        "id": "instruction",
        "name": "Инструкция",
        "description": "Пошаговый разбор: читатель получает готовый план действия.",
        "roles": [
            "обложка: результат, который получит читатель",
            "подготовка: что важно понять до старта (text)",
            "шаги по порядку (steps)",
            "частые ошибки при выполнении (checklist или comparison)",
            "закрепи пользу фактом или цифрой (stat)",
        ],
    },
    {
        "id": "insight",
        "name": "Инсайт с доказательством",
        "description": "Одна неочевидная мысль, раскрытая фактами и цитатой.",
        "roles": [
            "обложка: неочевидная мысль",
            "раскрой суть мысли (text)",
            "докажи цифрой или фактом (stat)",
            "цитата или ключевая формулировка из источника (quote)",
            "что это меняет в действиях читателя (checklist)",
        ],
    },
]

FRAME_BY_ID = {frame["id"]: frame for frame in COPY_FRAMES}


def pick_frame(frame_id: str | None = None) -> dict:
    if frame_id:
        return FRAME_BY_ID[frame_id]
    return random.choice(COPY_FRAMES)
