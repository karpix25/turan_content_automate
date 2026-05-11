import httpx
import logging
import os
import json
import re
from typing import Any, List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Client for OpenRouter API to access Gemini 2.5 Pro and other models.
    """
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model_id: Optional[str] = None):
        self.api_key = api_key.strip()
        self.model_id = model_id or os.getenv("OPENROUTER_MODEL_ID", "google/gemini-2.5-pro-latest")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://turan-automate.ai", # Optional for OpenRouter
            "X-Title": "Turan Content Automate",
            "Content-Type": "application/json"
        }

    def _complete(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> Optional[str]:
        if not self.api_key:
            logger.error("OpenRouter API key is missing")
            return None
            
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": temperature
        }
        timeout_seconds = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "180"))
        
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(f"{self.BASE_URL}/chat/completions", headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenRouter request failed: {e}")
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
            "Хук: используй такой же хук, если он сильный; если можно усилить без смены смысла, сделай лучше и резче.\n"
            "Длина: финальный текст должен быть примерно на 10% короче очищенного оригинала.\n"
            f"Цель: около {target_chars} символов с пробелами. Диапазон: {min_chars}-{max_chars} символов.\n"
            f"{voice_speed_line}"
            "Запрещено добавлять CTA, рекламу, подпишись/лайк/комментарий/директ/ссылка/сохрани/репост.\n"
            "Не растягивай в YouTube-сценарий, не добавляй главы, не объясняй тему шире оригинала.\n"
            "Пиши естественно для русской озвучки: короткие фразы, живой темп, без канцелярита.\n"
            "Не выдумывай новых фактов. Не добавляй мета-фразы про видео или сценарий.\n"
            f"Стиль автора учитывать мягко: {style_profile if style_profile else 'живой, уверенный, разговорный'}\n"
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
            "- Do not invent new facts.\n"
            "- Keep it natural and ready for voiceover.\n"
            "- Do not add calls to action, ads, sponsor mentions, self-promo, subscribe/like/comment/follow fragments.\n"
            "- Preserve stress marks written as one uppercase letter inside Russian words when they are present.\n"
            f"- Preserve style: {style_profile if style_profile else 'natural professional YouTube delivery'}\n"
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
        Builds a 9:16 cover prompt for short vertical clips using the Vizard title.
        """
        title = re.sub(r"\s+", " ", (clip_title or "")).strip()
        context = re.sub(r"\s+", " ", (context_text or title)).strip()
        if not title and not context:
            return None

        cover_text = title
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
                        "content": f"Заголовок клипа:\n{title or context}",
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
            words = title.split()
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
            f"Контекст:\n{context[:1200] or title}"
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
