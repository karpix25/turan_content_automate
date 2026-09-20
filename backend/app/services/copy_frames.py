"""Library of copywriting frames for carousel decks.

A frame is a proven narrative structure (mistakes, before/after, myths,
instruction, insight). The LLM picks the frame that fits the source text,
returns its id in the deck and fills the frame's slide roles; Python
validates that content slides follow the frame's role order.

Roles describe CONTENT slides only (cover and the final CTA slide are
always fixed blocks). "blocks" lists the block types a role may be
rendered with.
"""

import random

COPY_FRAMES = [
    {
        "id": "mistakes",
        "name": "Ошибки и ловушки",
        "description": "Разбор типовых ошибок: читатель узнаёт себя и получает план исправления.",
        "roles": [
            {"hint": "обостри проблему: масштаб, цена ошибки, неожиданный факт",
             "blocks": ["stat", "text"]},
            {"hint": "покажи типовые ошибки: «как делают все / как делают сильные»",
             "blocks": ["comparison", "checklist"]},
            {"hint": "объясни корень: почему люди ошибаются",
             "blocks": ["text"]},
            {"hint": "дай правильный порядок действий",
             "blocks": ["steps", "checklist", "qa"]},
        ],
    },
    {
        "id": "transformation",
        "name": "До / После",
        "description": "Контраст текущей и желаемой ситуации — структура, которая продаёт изменение.",
        "roles": [
            {"hint": "точка А: как делают сейчас и к чему это ведёт",
             "blocks": ["text", "stat"]},
            {"hint": "контраст точек А и Б",
             "blocks": ["comparison", "qa"]},
            {"hint": "конкретика сдвига: цифра или факт",
             "blocks": ["stat"]},
            {"hint": "шаги перехода из А в Б",
             "blocks": ["steps", "checklist"]},
        ],
    },
    {
        "id": "myths",
        "name": "Мифы и правда",
        "description": "Разрушение распространённых заблуждений с опорой на факты.",
        "roles": [
            {"hint": "главный миф и почему в него верят",
             "blocks": ["text", "qa"]},
            {"hint": "миф против правды",
             "blocks": ["comparison"]},
            {"hint": "как на самом деле: факты и правила",
             "blocks": ["checklist", "stat", "qa"]},
            {"hint": "что читателю сделать по-другому",
             "blocks": ["steps", "checklist"]},
        ],
    },
    {
        "id": "instruction",
        "name": "Инструкция",
        "description": "Пошаговый разбор: читатель получает готовый план действия.",
        "roles": [
            {"hint": "что важно понять до старта",
             "blocks": ["text"]},
            {"hint": "шаги по порядку",
             "blocks": ["steps"]},
            {"hint": "частые ошибки при выполнении",
             "blocks": ["checklist", "comparison"]},
            {"hint": "подкрепи результат фактом или цитатой",
             "blocks": ["stat", "quote"]},
        ],
    },
    {
        "id": "insight",
        "name": "Инсайт с доказательством",
        "description": "Одна неочевидная мысль, раскрытая фактами и цитатой.",
        "roles": [
            {"hint": "раскрой суть неочевидной мысли",
             "blocks": ["text", "stat"]},
            {"hint": "докажи цифрой или фактом",
             "blocks": ["stat"]},
            {"hint": "цитата или ключевая формулировка из источника",
             "blocks": ["quote"]},
            {"hint": "что это меняет в действиях читателя",
             "blocks": ["checklist", "qa"]},
        ],
    },
]

FRAME_BY_ID = {frame["id"]: frame for frame in COPY_FRAMES}


def pick_frame(frame_id: str | None = None) -> dict:
    if frame_id:
        return FRAME_BY_ID[frame_id]
    return random.choice(COPY_FRAMES)


def frames_catalog_text() -> str:
    """Prompt-ready description of every frame for the LLM to choose from."""
    lines = []
    for frame in COPY_FRAMES:
        roles = "; ".join(
            f"{index}) {role['hint']} [{'/'.join(role['blocks'])}]"
            for index, role in enumerate(frame["roles"], start=1)
        )
        lines.append(f"- «{frame['name']}» (frame: \"{frame['id']}\") — {frame['description']}. Роли: {roles}")
    return "\n".join(lines)
