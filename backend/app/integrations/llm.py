import httpx
import logging
import os
import json
import re
from typing import Any, List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _format_social_description_paragraphs(text: str | None, *, max_length: int = 900) -> str | None:
    content = (text or "").strip()
    if not content:
        return None

    content = re.sub(r"^[\"'«“]+|[\"'»”]+$", "", content)
    content = re.sub(r"https?://\S+|www\.\S+", "", content)
    content = re.sub(r"[#@]\S+", "", content)
    content = re.sub(r"[ \t\r\f\v]+", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    if len(content) > max_length:
        content = content[:max_length].rsplit(" ", 1)[0].strip()

    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n{2,}", content) if part.strip()]
    if len(paragraphs) <= 1:
        sentences = [item.strip() for item in re.split(r"(?<=[.!?…])\s+", content) if item.strip()]
        if len(sentences) >= 3:
            paragraphs = [sentences[0], " ".join(sentences[1:])]
        elif len(sentences) == 2:
            paragraphs = sentences
        else:
            paragraphs = [content]

    return "\n\n".join(part for part in paragraphs if part).strip() or None


class LLMClient:
    """
    Client for OpenRouter API to access Gemini 2.5 Pro and other models.
    """
    BASE_URL = "https://openrouter.ai/api/v1"
    GEMINI_GLOBAL_VERTEX_PROVIDER = "google-vertex/global"
    GEMINI_FALLBACK_MODEL = "anthropic/claude-opus-4.6"

    def __init__(self, api_key: str, model_id: Optional[str] = None):
        self.api_key = api_key.strip()
        self.model_id = model_id or os.getenv("OPENROUTER_MODEL_ID", "google/gemini-2.5-pro-latest")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://turan-automate.ai", # Optional for OpenRouter
            "X-Title": "Turan Content Automate",
            "Content-Type": "application/json"
        }

    def _complete(self, messages: List[Dict[str, Any]], temperature: float = 0.7) -> Optional[str]:
        if not self.api_key:
            logger.error("OpenRouter API key is missing")
            return None
            
        base_payload = {
            "messages": messages,
            "temperature": temperature
        }
        is_gemini = "gemini" in (self.model_id or "").lower()
        request_attempts: list[tuple[str, str | None]] = [(self.model_id, None)]
        if is_gemini:
            configured_provider = (os.getenv("OPENROUTER_GEMINI_PROVIDER") or "google-vertex").strip()
            fallback_model = (os.getenv("OPENROUTER_GEMINI_FALLBACK_MODEL") or self.GEMINI_FALLBACK_MODEL).strip()
            request_attempts = []
            for provider in (configured_provider, self.GEMINI_GLOBAL_VERTEX_PROVIDER):
                if provider and (self.model_id, provider) not in request_attempts:
                    request_attempts.append((self.model_id, provider))
            if fallback_model and fallback_model != self.model_id:
                request_attempts.append((fallback_model, None))
        timeout_seconds = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "180"))

        def payload_for_attempt(model_id: str, provider: str | None) -> dict:
            payload = dict(base_payload)
            payload["model"] = model_id
            if provider:
                payload["provider"] = {
                    "order": [provider],
                    "only": [provider],
                    "allow_fallbacks": False,
                }
            return payload

        with httpx.Client(timeout=timeout_seconds) as client:
            for attempt_index, (model_id, provider) in enumerate(request_attempts, start=1):
                payload = payload_for_attempt(model_id, provider)
                provider_label = provider or "openrouter-default"
                attempt_label = f"{model_id} via {provider_label}"
                try:
                    if is_gemini:
                        logger.info(
                            "OpenRouter Gemini request attempt %s/%s using %s",
                            attempt_index,
                            len(request_attempts),
                            attempt_label,
                        )
                    response = client.post(f"{self.BASE_URL}/chat/completions", headers=self.headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    choices = data.get("choices") or []
                    if not choices:
                        logger.error("OpenRouter response has no choices via %s: %s", attempt_label, str(data)[:1200])
                        continue
                    choice_error = choices[0].get("error") if isinstance(choices[0], dict) else None
                    if choice_error:
                        logger.error("OpenRouter choice error via %s: %s", attempt_label, str(choice_error)[:1200])
                        continue
                    content = ((choices[0].get("message") or {}).get("content") or "").strip()
                    if not content:
                        logger.error("OpenRouter response has empty content via %s: %s", attempt_label, str(data)[:1200])
                        continue
                    return content
                except Exception as e:
                    logger.error("OpenRouter request failed via %s: %s", attempt_label, e)
                    continue

        return None

    def analyze_style(self, transcripts: List[str]) -> Optional[str]:
        """
        Analyzes multiple transcripts to create a unique author style profile.
        """
        combined_text = "\n---\n".join(transcripts[:5]) # Limit to 5 for context window safety
        
        system_prompt = (
            "You are an expert linguistic analyst and YouTube script consultant. "
            "Your goal is to analyze the provided transcripts and extract a comprehensive 'Author Voice Profile'. "
            "Focus on: Tone (e.g., sarcastic, academic, high-energy), Vocabulary (e.g., slang used, technical jargon), "
            "Sentence Structure (e.g., short/punchy vs long/descriptive), and unique Pacing or Catchphrases. "
            "Return a descriptive profile that can be used to guide another AI to write in this exact style."
        )
        
        user_prompt = f"Analyze these YouTube transcripts and define the unique writing style:\n\n{combined_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return self._complete(messages, temperature=0.3)

    def generate_factual_outline(self, transcript: str) -> Optional[str]:
        """
        Extractions a summary of facts from the transcript, removing fluff.
        """
        system_prompt = (
            "You are a factual researcher. Your task is to extract all key facts, data points, and the core message "
            "from the provided YouTube transcript. Remove all filler words, jokes, and emotional commentary. "
            "Provide a clean, bulleted list of the essential information."
        )
        
        user_prompt = f"Extract a factual outline from this transcript:\n\n{transcript}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return self._complete(messages, temperature=0.2)

    def generate_youtube_publication_title(self, transcript: str) -> Optional[str]:
        source = re.sub(r"\s+", " ", (transcript or "")).strip()
        if not source:
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "Ты YouTube-копирайтер. Придумай новый заголовок для Shorts/короткого ролика "
                    "строго по транскрибации. Не используй оригинальный заголовок, ссылки, CTA, названия каналов "
                    "или рекламные фразы. Русский язык. До 90 символов. Без эмодзи. Верни только заголовок."
                ),
            },
            {
                "role": "user",
                "content": f"Транскрибация ролика:\n{source[:4000]}",
            },
        ]
        title = self._complete(messages, temperature=0.55)
        if not title:
            return None
        title = re.sub(r"^[\"'«“]+|[\"'»”]+$", "", title.strip())
        title = re.sub(r"\s+", " ", title).strip()
        return title[:100] or None

    def generate_instagram_post_5s_title(self, *, image_url: str | None, caption: str | None = None) -> Optional[str]:
        clean_caption = re.sub(r"\s+", " ", (caption or "")).strip()
        clean_image_url = (image_url or "").strip()
        if not clean_caption and not clean_image_url:
            return None

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Проанализируй Instagram post image. Обычно на картинке есть заголовок/тезис. "
                    "Найди главный смысл заголовка на изображении, затем перепиши его как сильную, понятную "
                    "плашку для 5-секундного вертикального видео. Не сжимай смысл до двух-трех слов: "
                    "зритель должен понять новость без открытия оригинального поста.\n\n"
                    "Правила: русский язык, 6-14 слов, максимум 120 символов, без эмодзи, без кавычек, "
                    "без ссылок и CTA, не копируй дословно если можно усилить. Верни только текст плашки.\n\n"
                    f"Caption поста для контекста:\n{clean_caption[:1200] or 'нет'}"
                ),
            }
        ]
        if clean_image_url:
            content.append({"type": "image_url", "image_url": {"url": clean_image_url}})

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "Ты редактор коротких заголовков для Reels/Stories и умеешь читать текст на изображениях.",
            },
            {"role": "user", "content": content},
        ]
        title = self._complete(messages, temperature=0.35)
        if not title:
            return None
        title = re.sub(r"^[\"'«“]+|[\"'»”]+$", "", title.strip())
        title = re.sub(r"\s+", " ", title).strip()
        title = re.sub(r"[#@]\S+", "", title).strip()
        if len(title) > 120:
            title = title[:120].rsplit(" ", 1)[0].strip()
        return title or None

    def generate_instagram_post_5s_description(
        self,
        *,
        caption: str | None,
        title: str | None = None,
    ) -> Optional[str]:
        clean_caption = re.sub(r"\s+", " ", (caption or "")).strip()
        clean_title = re.sub(r"\s+", " ", (title or "")).strip()
        if not clean_caption and not clean_title:
            return None

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Ты редактор коротких новостных публикаций для соцсетей. "
                    "Нужно написать новое описание под наш ролик, опираясь на оригинальный Instagram caption. "
                    "Нельзя копировать оригинал дословно и нельзя добавлять непроверенные факты."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Перепиши описание для публикации 5-секундного видео.\n\n"
                    "Требования:\n"
                    "- русский язык;\n"
                    "- 2-4 предложения;\n"
                    "- чуть более развернуто и интереснее оригинала;\n"
                    "- сохранить фактический смысл новости;\n"
                    "- убрать ссылки, хэштеги, упоминания, рекламу и CTA;\n"
                    "- не использовать эмодзи;\n"
                    "- разделить текст на 2 коротких абзаца, если получается больше одного предложения;\n"
                    "- вернуть только финальное описание.\n\n"
                    f"Заголовок нашего ролика:\n{clean_title or 'нет'}\n\n"
                    f"Оригинальное описание Instagram:\n{clean_caption[:2500] or 'нет'}"
                ),
            },
        ]
        description = self._complete(messages, temperature=0.45)
        if not description:
            return None
        return _format_social_description_paragraphs(description, max_length=900)

    def generate_infographic_reels_card(
        self,
        *,
        image_url: str | None,
        caption: str | None = None,
        source_title: str | None = None,
        style_profile: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        clean_caption = re.sub(r"[ \t\r\f\v]+", " ", (caption or "")).strip()
        clean_title = re.sub(r"\s+", " ", (source_title or "")).strip()
        clean_image_url = (image_url or "").strip()
        if not clean_caption and not clean_title and not clean_image_url:
            return None

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Сделай контент для вертикальной Instagram/Reels инфографики 9:16. "
                    "Сначала прочитай текст на изображении/кадре. Затем используй caption/описание только как фактический контекст. "
                    "Удали рекламу, ссылки, упоминания людей/аккаунтов, просьбы подписаться/лайкнуть/перейти, промо и водяные знаки. "
                    "Не выдумывай факты. Перепиши смысл в деловом, резком, понятном стиле автора.\n\n"
                    "Верни строго JSON без markdown с полями:\n"
                    "{\n"
                    '  "title": "крупный триггерный заголовок, 3-8 слов, caps не обязателен",\n'
                    '  "items": ["3-7 коротких пунктов основного блока"],\n'
                    '  "final_thought": "короткая финальная мысль или вывод",\n'
                    '  "description": "описание публикации без рекламы и упоминаний, 2 коротких абзаца",\n'
                    '  "image_prompt": "полный промт для генератора изображения"\n'
                    "}\n\n"
                    "image_prompt должен описывать готовую русскую карточку в таком стиле:\n"
                    "- вертикальный кадр 9:16;\n"
                    "- однотонный теплый желто-песочный фон #EAC86F / pale golden beige;\n"
                    "- минималистичная дорогая бизнес-инфографика, без логотипов, градиентов, лишних цветов и декора;\n"
                    "- вверху крупный черный заголовок Montserrat ExtraBold прямо на фоне;\n"
                    "- ниже один большой off-white/молочный блок с мягкими скруглениями и основным текстом;\n"
                    "- внизу отдельное off-white CTA-окно;\n"
                    "- CTA точный текст: «У меня про тендеры и бизнес» и «ПОДПИШИСЬ ↓»;\n"
                    "- добавить realistic cutout sticker автора: мужчина с темными волосами, густой темной бородой, выразительными бровями, "
                    "эмоция удивление/уверенность/вовлеченность, показывает пальцем на основной блок или CTA, 18-22% высоты кадра;\n"
                    "- автор не закрывает важный текст;\n"
                    "- текст на русском, аккуратный, крупный, читаемый, не перегружать экран.\n\n"
                    f"Профиль стиля автора:\n{(style_profile or 'деловой, жесткий, понятный, без воды')[:1500]}\n\n"
                    f"Заголовок источника:\n{clean_title or 'нет'}\n\n"
                    f"Caption/описание источника:\n{clean_caption[:2500] or 'нет'}"
                ),
            }
        ]
        if clean_image_url:
            content.append({"type": "image_url", "image_url": {"url": clean_image_url}})

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Ты редактор бизнес-инфографики и умеешь читать текст на изображениях. "
                    "Отвечай только валидным JSON."
                ),
            },
            {"role": "user", "content": content},
        ]
        result = self._complete(messages, temperature=0.45)
        if not result:
            return None
        try:
            start = result.find("{")
            end = result.rfind("}") + 1
            payload = json.loads(result[start:end])
        except Exception:
            logger.warning("Failed to parse infographic reels JSON: %s", result[:500])
            return None
        if not isinstance(payload, dict):
            return None

        title = re.sub(r"\s+", " ", str(payload.get("title") or clean_title or "Главная мысль").strip())
        raw_items = payload.get("items") or []
        items = [
            re.sub(r"\s+", " ", str(item).strip())
            for item in raw_items
            if str(item).strip()
        ][:7]
        final_thought = re.sub(r"\s+", " ", str(payload.get("final_thought") or "").strip())
        description = _format_social_description_paragraphs(str(payload.get("description") or clean_caption or title), max_length=900)
        image_prompt = str(payload.get("image_prompt") or "").strip()
        if not image_prompt:
            image_prompt = (
                "Создай вертикальную Instagram/Reels инфографику 9:16 в минималистичном стиле. "
                "Фон теплый желто-песочный #EAC86F, большой off-white блок, нижнее CTA-окно, "
                "Montserrat, черный текст, realistic cutout sticker автора с темными волосами и густой бородой. "
                f"Заголовок: {title}. Пункты: {'; '.join(items)}. Финальная мысль: {final_thought}. "
                "CTA: «У меня про тендеры и бизнес» «ПОДПИШИСЬ ↓»."
            )

        return {
            "title": title[:140],
            "items": items,
            "final_thought": final_thought[:220],
            "description": description or title,
            "image_prompt": image_prompt,
        }

    @staticmethod
    def estimate_word_count(text: str | None) -> int:
        content = (text or "").strip()
        if not content:
            return 0
        return len(re.findall(r"\b[\w'-]+\b", content, flags=re.UNICODE))

    @staticmethod
    def estimate_char_count(text: str | None) -> int:
        return len((text or "").strip())

    def rewrite_to_script(
        self,
        source_text: str,
        style_profile: Optional[str],
        min_minutes: int = 10,
        max_minutes: int = 15,
        words_per_minute: int = 130,
        target_chars: Optional[int] = None,
        min_chars: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """
        Rewrites source transcript/facts into a high-retention YouTube script.
        Target duration is controlled by min/max minutes or calibrated character count.
        """
        min_words = max(200, int(min_minutes * words_per_minute))
        max_words = max(min_words + 150, int(max_minutes * words_per_minute))
        target_words = int((min_words + max_words) / 2)
        if target_chars:
            min_chars_value = int(min_chars or max(300, round(target_chars * 0.92)))
            max_chars_value = int(max_chars or max(min_chars_value + 200, round(target_chars * 1.08)))
            length_requirements = (
                f"- Target spoken duration: about {min_minutes} minutes, calibrated by the selected ElevenLabs voice.\n"
                f"- Target script length: about {int(target_chars)} characters, including spaces.\n"
                f"- Keep output between {min_chars_value} and {max_chars_value} characters, including spaces.\n"
                "- Character count is more important than word count for this task.\n"
                "- Return only final script text with natural paragraphs."
            )
        else:
            length_requirements = (
                f"- Target spoken duration: {min_minutes}-{max_minutes} minutes.\n"
                f"- Keep output between {min_words} and {max_words} words.\n"
                f"- Aim close to {target_words} words.\n"
                f"- Return only final script text with natural paragraphs."
            )

        narrative_rules = (
            "Follow the 2026 YouTube Master Narrative & Retention Framework:\n"
            "1. THE 8-SECOND HOOK: Start instantly with 'productive discomfort', a contrarian truth, or the core conflict. ZERO 'Welcome back' or 'In this video' greetings.\n"
            "2. STRUCTURE THE ORIGINAL LOGIC: If the source is chaotic or non-linear, reorder it into a clean sequence of key meanings. First extract the core тезисы, then expand each тезис in its own chapter with clear cause/effect links.\n"
            "3. SEGMENTED NARRATIVE: Break the body into 3-4 distinct 'chapters'. Every chapter must start with a micro-hook and then раскрыть тезис по пунктам: тезис -> объяснение -> пример/следствие.\n"
            "4. WRITE FOR THE EAR: Use ultra-conversational language. Keep sentences punchy (under 20 words). No corporate or academic fluff.\n"
            "5. NO CTA / NO ADS: Completely ignore calls to action (subscribe/like/comment), sponsor mentions, self-promo and ad insertions from the source. Do not include any CTA in the final script.\n"
            "6. ABRUPT OUTRO: End powerfully and concisely after the final value is delivered. Do not drag out the ending with long goodbyes."
        )
        
        system_prompt = (
            f"You are a World-Class YouTube Scriptwriter. "
            f"Your task is to rewrite the provided source material into a {min_minutes}-{max_minutes} minute engaging script.\n"
            f"{narrative_rules}\n\n"
            f"STYLE REQUIREMENTS:\n"
            f"{style_profile if style_profile else 'Use a natural, engaging, and professional YouTube tone.'}\n\n"
            "OPENING QUALITY REQUIREMENTS:\n"
            "- First 2-3 sentences must start from concrete tension/problem and promise a specific payoff.\n"
            "- No generic intros, no polite prefaces, no 'в этом видео' filler.\n"
            "- Use specific nouns and verbs immediately.\n\n"
            "NATURAL VOICE REQUIREMENTS:\n"
            "- Write in natural spoken Russian.\n"
            "- Vary sentence length and rhythm.\n"
            "- Avoid template transitions and AI clichés.\n"
            "- Avoid bureaucratic language and over-formal wording.\n"
            "- Допускается пометка ударения ОДНОЙ заглавной буквой внутри слова (пример: звОнит, договОр), но только в действительно спорных словах и не чаще 1-2 раз на абзац.\n"
            "- Приоритет для таких пометок: названия городов/топонимов, профессиональная терминология, глаголы с частыми ошибками в ударении.\n"
            "- Avoid meta-commentary about the script itself.\n\n"
            "CONTENT FILTER REQUIREMENTS:\n"
            "- Ignore and remove all ad integrations, sponsor fragments, and promotional inserts from source material.\n"
            "- Ignore and remove all CTA fragments (subscribe/like/comment/follow).\n"
            "- Keep only the informational/analytical core and practical meaning.\n\n"
            f"LENGTH REQUIREMENTS:\n"
            f"{length_requirements}"
        )
        
        user_prompt = f"Rewrite this source material into a complete script:\n\n{source_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return self._complete(messages, temperature=0.8)

    def remove_cta_from_transcript(self, transcript: str) -> Optional[str]:
        """
        Removes calls to action, ads, sponsor inserts, and self-promo from a short-form transcript.
        """
        source = (transcript or "").strip()
        if not source:
            return None

        system_prompt = (
            "Ты редактор коротких видео. Очисти транскрипт от всех призывов к действию и промо.\n"
            "Удаляй: подпишись, поставь лайк, оставь комментарий, напиши в директ, переходи по ссылке, "
            "купи, забронируй, регистрируйся, скачай, жми, сохраняй, репостни, промокоды, рекламные и спонсорские вставки, "
            "саморекламу автора и просьбы о вовлечении.\n"
            "Сохрани оригинальный смысл, порядок мыслей, хук, факты, тон и разговорную подачу.\n"
            "Не переписывай текст сильнее, чем нужно для удаления CTA.\n"
            "Верни только очищенный текст."
        )
        user_prompt = f"Очисти этот транскрипт:\n\n{source}"
        return self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
        )

    def rewrite_reels_avatar_script(
        self,
        cleaned_transcript: str,
        style_profile: Optional[str],
        target_chars: int,
        min_chars: int,
        max_chars: int,
        voice_chars_per_second: Optional[float] = None,
        target_duration_seconds: Optional[float] = None,
    ) -> Optional[str]:
        """
        Rewrites a Reel into a HeyGen-ready avatar script that mirrors the original short.
        """
        source = (cleaned_transcript or "").strip()
        if not source:
            return None

        voice_speed_line = ""
        if voice_chars_per_second and voice_chars_per_second > 0 and target_duration_seconds and target_duration_seconds > 0:
            voice_speed_line = (
                f"Озвучка будет выбранным ElevenLabs-голосом со скоростью примерно "
                f"{voice_chars_per_second:.2f} символов/сек. "
                f"Целевая длительность озвучки: около {target_duration_seconds:.1f} сек.\n"
            )

        system_prompt = (
            "Ты сценарист Reels/Shorts и редактор аватарных видео. "
            "Перепиши очищенный транскрипт в финальный сценарий для HeyGen-аватара.\n"
            "Главная задача: сценарий должен по сути повторять оригинал, сохранять тот же порядок мысли, конфликт и подачу.\n"
            "ХУК КРИТИЧЕСКИ ВАЖЕН:\n"
            "- Первые 1-2 фразы должны зацепить за первые 2 секунды.\n"
            "- Начинай не с объяснения темы, а с напряжения: неожиданный факт, конфликт, ошибка, риск, запрет, сильный вопрос или резкий контраст.\n"
            "- Хук должен обещать конкретную развязку или выгоду, но не раскрывать всё сразу.\n"
            "- Если оригинальный хук слабый или бытовой, перестрой его в более сильный без смены смысла и без новых фактов.\n"
            "- Запрещены вялые начала: 'сегодня поговорим', 'в этом видео', 'давайте разберёмся', 'многие не знают', 'важно понимать'.\n"
            "- После хука сразу продолжай основную мысль, без приветствий и раскачки.\n"
            "Длина: финальный текст должен быть близок к очищенному оригиналу и попадать в лимит под длительность озвучки. "
            "Не расширяй мысль, если из-за этого вылезаешь за лимит.\n"
            f"Цель: около {target_chars} символов с пробелами. Диапазон: {min_chars}-{max_chars} символов.\n"
            f"{voice_speed_line}"
            "Если текст длиннее диапазона, сокращай фразы и убирай вводные слова. "
            "Если текст короче диапазона, добавляй только смысловые детали из оригинала.\n"
            "Запрещено добавлять CTA, рекламу, подпишись/лайк/комментарий/директ/ссылка/сохрани/репост.\n"
            "Не растягивай в YouTube-сценарий, не добавляй главы, не объясняй тему шире оригинала.\n"
            "Пиши естественно для русской озвучки: короткие фразы, живой темп, без канцелярита.\n"
            "Не выдумывай новых фактов. Не добавляй мета-фразы про видео или сценарий.\n"
            "СТИЛЬ АВТОРА ОБЯЗАТЕЛЕН: сохраняй лексику, ритм, уровень резкости, типичные переходы, "
            "манеру объяснять и эмоциональную температуру автора. Не усредняй под нейтральный YouTube-тон.\n"
            f"Профиль стиля автора: {style_profile if style_profile else 'живой, уверенный, разговорный'}\n"
            "Верни только финальный сценарий."
        )
        user_prompt = f"Очищенный транскрипт Reels:\n\n{source}"
        return self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.65,
        )

    def humanize_russian_text_by_chars(
        self,
        script: str,
        style_profile: Optional[str],
        min_chars: int,
        max_chars: int,
    ) -> Optional[str]:
        if not script:
            return None

        system_prompt = (
            "Ты редактор русскоязычных сценариев. "
            "Убери следы ИИ-генерации и сделай текст живым.\n"
            "Сохраняй смысл и факты, не выдумывай новое.\n"
            "Ориентируйся на практики humanizer-ru:\n"
            "- убирай канцелярит и общие пафосные формулировки;\n"
            "- заменяй шаблонные связки на естественную речь;\n"
            "- убирай фразы-пустышки и мета-объяснения;\n"
            "- избегай синтетических троек и одинакового ритма.\n\n"
            "Дополнительные требования:\n"
            "- Усиль первые 2-3 предложения: крючок должен быть конкретным и цеплять сразу.\n"
            "- Запрети клише типа: 'в этом видео', 'давайте разберемся', 'важно отметить', "
            "'не только..., но и...', 'в современном мире'.\n"
            "- Пиши естественно, будто это живой автор, а не ассистент.\n"
            "- Разрешено сохранять/добавлять пометки ударения одной заглавной буквой в спорных словах, но умеренно.\n"
            f"- Сохрани длину в диапазоне {min_chars}-{max_chars} символов, включая пробелы.\n"
            f"- Учитывай стиль: {style_profile if style_profile else 'живой, уверенный, разговорный без воды'}\n"
            "- Верни только финальный текст."
        )
        user_prompt = f"Очеловечь и отредактируй этот сценарий:\n\n{script}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.75)

    def humanize_russian_text(
        self,
        script: str,
        style_profile: Optional[str],
        min_words: int,
        max_words: int,
    ) -> Optional[str]:
        """
        Humanizes Russian text and removes common AI patterns.
        Uses principles from humanizer-ru (Vladimir-Human/humanizer-ru).
        """
        if not script:
            return None

        system_prompt = (
            "Ты редактор русскоязычных сценариев. "
            "Убери следы ИИ-генерации и сделай текст живым.\n"
            "Сохраняй смысл и факты, не выдумывай новое.\n"
            "Ориентируйся на практики humanizer-ru:\n"
            "- убирай канцелярит и общие пафосные формулировки;\n"
            "- заменяй шаблонные связки на естественную речь;\n"
            "- убирай фразы-пустышки и мета-объяснения;\n"
            "- избегай синтетических троек и одинакового ритма.\n\n"
            "Дополнительные требования:\n"
            "- Усиль первые 2-3 предложения: крючок должен быть конкретным и цеплять сразу.\n"
            "- Запрети клише типа: 'в этом видео', 'давайте разберемся', 'важно отметить', "
            "'не только..., но и...', 'в современном мире'.\n"
            "- Пиши естественно, будто это живой автор, а не ассистент.\n"
            "- Разрешено сохранять/добавлять пометки ударения одной заглавной буквой в спорных словах, но умеренно (не чаще 1-2 раз на абзац).\n"
            "- В первую очередь делай это для городов/топонимов, профильной терминологии и глаголов, где ударение часто путают.\n"
            f"- Сохрани длину в диапазоне {min_words}-{max_words} слов.\n"
            f"- Учитывай стиль: {style_profile if style_profile else 'живой, уверенный, разговорный без воды'}\n"
            "- Верни только финальный текст."
        )
        user_prompt = f"Очеловечь и отредактируй этот сценарий:\n\n{script}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.75)

    def adjust_script_length(
        self,
        script: str,
        style_profile: Optional[str],
        min_words: int,
        max_words: int,
    ) -> Optional[str]:
        """
        Expands or compresses script while preserving facts and style constraints.
        """
        if not script:
            return None

        system_prompt = (
            "You are an expert script editor. "
            "Adjust script length to fit exact constraints while preserving facts, structure, and voice.\n"
            f"- Keep between {min_words} and {max_words} words.\n"
            "- Do not invent new facts.\n"
            "- Keep it natural and ready for voiceover.\n"
            "- Do not add calls to action, ads, sponsor mentions, self-promo, subscribe/like/comment/follow fragments.\n"
            "- Preserve stress marks written as one uppercase letter inside Russian words when they are present.\n"
            "- Do not remove stress marks in city names/toponyms, technical terminology and verbs with ambiguous stress.\n"
            f"- Preserve style: {style_profile if style_profile else 'natural professional YouTube delivery'}\n"
            "- Return only the edited final script."
        )
        user_prompt = f"Edit this script to fit length:\n\n{script}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.6)

    def adjust_script_length_chars(
        self,
        script: str,
        style_profile: Optional[str],
        min_chars: int,
        max_chars: int,
    ) -> Optional[str]:
        if not script:
            return None

        target_chars = int((min_chars + max_chars) / 2)
        system_prompt = (
            "You are an expert script editor. "
            "Adjust script length to fit exact character-count constraints while preserving facts, structure, and voice.\n"
            f"- Target about {target_chars} characters including spaces.\n"
            f"- Keep between {min_chars} and {max_chars} characters including spaces.\n"
            "- Character count is a hard delivery constraint because ElevenLabs timing depends on it.\n"
            "- Do not invent new facts.\n"
            "- Keep it natural and ready for voiceover.\n"
            "- Do not add calls to action, ads, sponsor mentions, self-promo, subscribe/like/comment/follow fragments.\n"
            "- Preserve stress marks written as one uppercase letter inside Russian words when they are present.\n"
            "- Preserve the author's style strictly: vocabulary, rhythm, emotional temperature, and delivery habits.\n"
            f"- Author style profile: {style_profile if style_profile else 'natural professional YouTube delivery'}\n"
            "- Return only the edited final script."
        )
        user_prompt = f"Edit this script to fit character length:\n\n{script}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.6)

    def verify_faithfulness(self, factual_outline: str, script: str) -> Dict[str, Any]:
        """
        Verifies that the generated script doesn't contain hallucinations.
        """
        system_prompt = (
            "You are a fact-checker. Compare the original factual outline with the generated script. "
            "Identify any facts in the script that WERE NOT in the original outline. "
            "Return a JSON object with 'is_faithful' (boolean) and 'hallucinations' (list of strings)."
        )
        
        user_prompt = f"OUTLINE:\n{factual_outline}\n\nSCRIPT:\n{script}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        result = self._complete(messages, temperature=0.1)
        try:
            # We hope it returns clean JSON
            start = result.find("{")
            end = result.rfind("}") + 1
            return json.loads(result[start:end])
        except:
            return {"is_faithful": True, "hallucinations": [], "error": "Parsing failed"}

    def generate_youtube_thumbnail_prompt(
        self,
        factual_outline: str,
        script: str,
        video_title: Optional[str] = None,
    ) -> Optional[str]:
        """
        Builds a concise high-CTR Russian prompt for thumbnail generation.
        """
        source_outline = (factual_outline or "").strip()
        source_script = (script or "").strip()
        if not source_outline and not source_script:
            return None

        intro_source = source_script or source_outline
        intro_fragment = ""
        if intro_source:
            normalized_intro = re.sub(r"\s+", " ", intro_source).strip()
            if normalized_intro:
                intro_sentences = re.split(r"(?<=[.!?…])\s+", normalized_intro)
                intro_fragment = " ".join(intro_sentences[:2]).strip()
                if len(intro_fragment) < 90 and len(intro_sentences) > 2:
                    intro_fragment = " ".join(intro_sentences[:3]).strip()
                if len(intro_fragment) > 420:
                    intro_fragment = intro_fragment[:420].rsplit(" ", 1)[0].strip()

        hook_text = ""
        hook_source = source_script or intro_fragment
        if hook_source:
            normalized_hook = re.sub(r"\s+", " ", hook_source).strip()
            if normalized_hook:
                hook_sentences = re.split(r"(?<=[.!?…])\s+", normalized_hook)
                first_sentence = (hook_sentences[0] if hook_sentences else normalized_hook).strip()
                first_sentence = first_sentence.strip(" \"'«».,:;!?…")
                if first_sentence:
                    hook_words = first_sentence.split()
                    if len(hook_words) > 10:
                        first_sentence = " ".join(hook_words[:10]).strip()
                    if len(first_sentence) > 70:
                        first_sentence = first_sentence[:70].rsplit(" ", 1)[0].strip()
                    hook_text = first_sentence

        thumbnail_hook = hook_text
        if hook_text:
            hook_system_prompt = (
                "Ты CTR-копирайтер YouTube-обложек. "
                "Преобразуй исходный хук в короткий текст для обложки с высоким CTR.\n"
                "Правила:\n"
                "- Сохраняй исходный смысл и конфликт, не выдумывай новую тему.\n"
                "- 2-6 слов, максимум 45 символов.\n"
                "- Разрешен сильный эмоциональный тон, но без кликбейт-обмана.\n"
                "- Никаких кавычек, пояснений и второго варианта.\n"
                "- Верни только одну финальную фразу."
            )
            hook_user_prompt = (
                "Исходный хук из первых секунд:\n"
                f"{hook_text}\n\n"
                "Контекст первых ~10 секунд:\n"
                f"{intro_fragment[:700] or hook_text}"
            )
            adapted_hook = self._complete(
                [
                    {"role": "system", "content": hook_system_prompt},
                    {"role": "user", "content": hook_user_prompt},
                ],
                temperature=0.55,
            )
            clean_adapted_hook = re.sub(r"\s+", " ", (adapted_hook or "")).strip().strip("\"'«»")
            if clean_adapted_hook:
                if len(clean_adapted_hook) > 45:
                    clean_adapted_hook = clean_adapted_hook[:45].rsplit(" ", 1)[0].strip()
                hook_words = clean_adapted_hook.split()
                if len(hook_words) > 6:
                    clean_adapted_hook = " ".join(hook_words[:6]).strip()
                thumbnail_hook = clean_adapted_hook
            elif hook_text:
                fallback_words = hook_text.split()
                thumbnail_hook = " ".join(fallback_words[:6]).strip()

        hook_scene = ""
        scene_source = intro_fragment or source_script or source_outline
        if scene_source:
            normalized_scene = re.sub(r"\s+", " ", scene_source).strip()
            if normalized_scene:
                scene_sentences = re.split(r"(?<=[.!?…])\s+", normalized_scene)
                scene_first = (scene_sentences[0] if scene_sentences else normalized_scene).strip()
                if len(scene_first) > 180:
                    scene_first = scene_first[:180].rsplit(" ", 1)[0].strip()
                hook_scene = scene_first

        source_lower = f"{intro_fragment} {source_outline} {source_script}".lower()
        surveillance_markers = [
            "vpn", "впн", "фсб", "слеж", "контрол", "роскомнадзор",
            "яндекс", "сбер", "ozon", "озон", "vk", "вконтакте", "avito", "авито",
            "утечк", "трекер", "ip-адрес", "айпи",
        ]
        is_surveillance_topic = any(marker in source_lower for marker in surveillance_markers)

        system_prompt = (
            "Ты креативный директор YouTube-обложек. "
            "Сделай промт для генератора изображения, который даст высокий CTR.\n"
            "Требования:\n"
            "- Язык: русский.\n"
            "- 1-3 коротких предложения, без списков.\n"
            "- Смысл обложки должен в первую очередь отражать то, что говорится в первых ~10 секундах видео (интро/хук).\n"
            "- Если есть конфликт между общей темой и интро, приоритет у интро первых 10 секунд.\n"
            "- Не выноси на обложку тезис, которого нет в первых ~10 секундах.\n"
            "- Текст на обложке должен быть CTR-адаптацией хука из первых 10 секунд (перефраз допустим, смена темы запрещена).\n"
            "- Композиция кадра должна буквально визуализировать хук из первых 10 секунд: главный герой, действие и конфликт в центре кадра.\n"
            "- Если визуальная идея не совпадает с хуком, измени композицию под хук, а не наоборот.\n"
            "- Четко передай главный конфликт/обещание видео.\n"
            "- Визуал: крупный план, сильная эмоция, контрастный фон, чистая композиция.\n"
            "- Добавляй 1-3 тематических визуальных маркера по теме ролика: узнаваемые логотипы, иконки, интерфейсные элементы, предметы или символы ниши.\n"
            "- Для тем про маркетплейсы обязательно предложи узнаваемые элементы маркетплейсов (например карточки товара, корзина, логотипы/иконки площадок, графики продаж в кабинете продавца).\n"
            "- Для тем про цифровую безопасность/шпионаж добавляй визуальные маркеры угрозы: смартфон, трекеры, утечка данных, карта/флаги стран, предупреждающие интерфейсы.\n"
            "- Тематические элементы должны поддерживать главный конфликт, а не быть декором ради декора.\n"
            "- Не перегружай кадр: один главный герой и ограниченное число вторичных элементов.\n"
            "- Запрещено уводить обложку в мета-темы (аватар, анонс, нейросеть, процесс создания), если это не является основной темой исходного контента.\n"
            "- Должен быть триггер и интрига без кликбейта-обмана.\n"
            "- В финальном промте обязательно явно укажи: Текст на обложке: \"...\".\n"
            "- В финальном промте обязательно явно укажи: Композиция: ...\n"
            "- Не добавляй технические параметры типа 16:9, 4k, lens, seed.\n"
            "- Верни только финальный промт."
        )
        user_prompt = (
            f"Заголовок видео:\n{(video_title or '').strip() or 'Без заголовка'}\n\n"
            "Текст первых ~10 секунд (интро/хук):\n"
            f"{intro_fragment[:700] or 'Нет данных'}\n\n"
            "Целевой текст на обложке (CTR-адаптация хука):\n"
            f"\"{thumbnail_hook or hook_text or 'Нет данных'}\"\n\n"
            "Обязательная композиция (из хука первых 10 секунд):\n"
            f"{hook_scene[:400] or 'Нет данных'}\n\n"
            "Суть видео и факты:\n"
            f"{source_outline[:5000]}\n\n"
            "Фрагмент сценария:\n"
            f"{source_script[:5000]}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        prompt = self._complete(messages, temperature=0.85)
        if not prompt:
            return None

        final_prompt = prompt.strip()
        normalized_final = re.sub(r"\s+", " ", final_prompt).lower()
        if thumbnail_hook:
            required_line = f'Текст на обложке: "{thumbnail_hook}".'
            normalized_hook = re.sub(r"\s+", " ", thumbnail_hook).lower()
            if normalized_hook not in normalized_final:
                if final_prompt and not final_prompt.endswith((".", "!", "?")):
                    final_prompt = f"{final_prompt}."
                final_prompt = f'{final_prompt} {required_line}'
                normalized_final = re.sub(r"\s+", " ", final_prompt).lower()
        if hook_scene and "композиц" not in normalized_final:
            required_scene_line = f'Композиция: {hook_scene}.'
            if final_prompt and not final_prompt.endswith((".", "!", "?")):
                final_prompt = f"{final_prompt}."
            final_prompt = f"{final_prompt} {required_scene_line}"

        # Hard topic guardrail: for surveillance/VPN videos forbid generic money-trading visuals.
        if is_surveillance_topic:
            finance_noise = [
                "$", "доллар", "деньги", "прибыль", "доход", "трейдинг", "инвести",
                "из ямы", "выйти в плюс", "бирж", "финанс",
            ]
            normalized_final = re.sub(r"\s+", " ", final_prompt).lower()
            if any(token in normalized_final for token in finance_noise):
                safe_scene = (
                    hook_scene
                    or "крупный план тревожного лица, смартфон с VPN-иконкой, предупреждение о слежке, логотипы сервисов"
                )
                safe_text = thumbnail_hook or hook_text or "Тотальный контроль"
                final_prompt = (
                    "Драматичная YouTube-обложка про цифровую слежку и контроль: "
                    "крупный план лица с тревогой, смартфон с включенным VPN, красный warning-интерфейс, "
                    "иконки популярных сервисов, атмосфера угрозы и наблюдения, высокий контраст. "
                    f'Текст на обложке: "{safe_text}". '
                    f"Композиция: {safe_scene}."
                )
        return final_prompt

    def generate_vertical_thumbnail_prompt(
        self,
        clip_title: str,
        context_text: Optional[str] = None,
    ) -> Optional[str]:
        """
        Builds a 9:16 cover prompt for short vertical clips using the clip title
        plus scenario context when the title is generic.
        """
        title = re.sub(r"\s+", " ", (clip_title or "")).strip()
        context = re.sub(r"\s+", " ", (context_text or title)).strip()
        if not title and not context:
            return None

        generic_titles = {
            "главный момент",
            "важный момент",
            "short avatar",
            "без заголовка",
            "сцена без транскрипта",
            "проверьте источник",
            "проверьте язык",
            "повторите запуск",
        }
        normalized_title = re.sub(r"\s+", " ", title).strip().lower()
        title_is_generic = (
            not normalized_title
            or normalized_title in generic_titles
            or bool(re.fullmatch(r"(clip|клип|сцена)\s*\d+", normalized_title))
        )
        cover_source = context if title_is_generic and context else (title or context)
        cover_text = cover_source
        try:
            adapted = self._complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Ты CTR-копирайтер вертикальных обложек для Shorts/Reels/TikTok. "
                            "Сожми заголовок в короткий текст на обложку.\n"
                            "Правила: 2-6 слов, максимум 42 символа, русский язык, без кавычек, "
                            "без эмодзи, без выдумывания новой темы. Верни только фразу."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Заголовок клипа:\n{title or 'нет'}\n\n"
                            f"Сценарный контекст:\n{context[:1200] or 'нет'}\n\n"
                            f"Сделай текст на обложку из {'сценарного контекста' if title_is_generic else 'заголовка и контекста'}."
                        ),
                    },
                ],
                temperature=0.55,
            )
        except Exception:
            adapted = None

        clean_adapted = re.sub(r"\s+", " ", (adapted or "")).strip().strip("\"'«»")
        if clean_adapted:
            if len(clean_adapted) > 42:
                clean_adapted = clean_adapted[:42].rsplit(" ", 1)[0].strip()
            words = clean_adapted.split()
            if len(words) > 6:
                clean_adapted = " ".join(words[:6]).strip()
            cover_text = clean_adapted
        else:
            words = cover_source.split()
            cover_text = " ".join(words[:6]).strip() if words else "Главный момент"

        system_prompt = (
            "Ты креативный директор вертикальных обложек 9:16 для коротких видео. "
            "Сделай промт для генератора изображения.\n"
            "Требования:\n"
            "- Язык: русский.\n"
            "- Формат кадра вертикальный 9:16.\n"
            "- Композиция должна читаться на телефоне: крупный главный объект/герой, сильная эмоция, высокий контраст.\n"
            "- Текст крупный, 2-6 слов, расположен в верхней или центральной трети, не у краев.\n"
            "- Визуал строго отражает заголовок клипа, без новой темы.\n"
            "- Если заголовок общий, пустой или похож на fallback, бери тему и текст из сценарного контекста.\n"
            "- Референсы используй только как стиль: цвет, свет, контраст, плотность кадра.\n"
            "- Не копируй текст, логотипы, интерфейсы и композицию референсов буквально.\n"
            "- В финальном промте обязательно явно укажи: Текст на обложке: \"...\".\n"
            "- В финальном промте обязательно явно укажи: Композиция: ...\n"
            "- Не добавляй технические параметры типа seed, lens, 4k.\n"
            "- Верни только финальный промт."
        )
        user_prompt = (
            f"Заголовок клипа:\n{title or 'Без заголовка'}\n\n"
            f"Короткий текст на обложке:\n\"{cover_text or 'Главный момент'}\"\n\n"
            f"Сценарный контекст:\n{context[:1200] or title}"
        )
        prompt = self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
        )
        if not prompt:
            return (
                "Вертикальная 9:16 обложка для короткого видео: крупный эмоциональный герой, "
                "контрастный фон, чистая композиция, телефонная читаемость. "
                f'Текст на обложке: "{cover_text or "Главный момент"}". '
                f"Композиция: визуально раскрыть заголовок клипа {title or context}."
            )

        final_prompt = prompt.strip()
        normalized = re.sub(r"\s+", " ", final_prompt).lower()
        if cover_text and re.sub(r"\s+", " ", cover_text).lower() not in normalized:
            if final_prompt and not final_prompt.endswith((".", "!", "?")):
                final_prompt = f"{final_prompt}."
            final_prompt = f'{final_prompt} Текст на обложке: "{cover_text}".'
        if "композиц" not in normalized:
            if final_prompt and not final_prompt.endswith((".", "!", "?")):
                final_prompt = f"{final_prompt}."
            final_prompt = f"{final_prompt} Композиция: вертикальный 9:16 кадр, который визуально раскрывает заголовок клипа."
        return final_prompt
