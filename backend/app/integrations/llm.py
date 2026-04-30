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

    def rewrite_to_script(
        self,
        source_text: str,
        style_profile: Optional[str],
        min_minutes: int = 10,
        max_minutes: int = 15,
        words_per_minute: int = 130,
    ) -> Optional[str]:
        """
        Rewrites source transcript/facts into a high-retention YouTube script.
        Target duration is controlled by min/max minutes.
        """
        min_words = max(200, int(min_minutes * words_per_minute))
        max_words = max(min_words + 150, int(max_minutes * words_per_minute))
        target_words = int((min_words + max_words) / 2)

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
            f"- Target spoken duration: {min_minutes}-{max_minutes} minutes.\n"
            f"- Keep output between {min_words} and {max_words} words.\n"
            f"- Aim close to {target_words} words.\n"
            f"- Return only final script text with natural paragraphs."
        )
        
        user_prompt = f"Rewrite this source material into a complete script:\n\n{source_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return self._complete(messages, temperature=0.8)

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

        system_prompt = (
            "Ты креативный директор YouTube-обложек. "
            "Сделай промт для генератора изображения, который даст высокий CTR.\n"
            "Требования:\n"
            "- Язык: русский.\n"
            "- 1-3 коротких предложения, без списков.\n"
            "- Четко передай главный конфликт/обещание видео.\n"
            "- Визуал: крупный план, сильная эмоция, контрастный фон, чистая композиция.\n"
            "- Добавляй 1-3 тематических визуальных маркера по теме ролика: узнаваемые логотипы, иконки, интерфейсные элементы, предметы или символы ниши.\n"
            "- Для тем про маркетплейсы обязательно предложи узнаваемые элементы маркетплейсов (например карточки товара, корзина, логотипы/иконки площадок, графики продаж в кабинете продавца).\n"
            "- Тематические элементы должны поддерживать главный конфликт, а не быть декором ради декора.\n"
            "- Не перегружай кадр: один главный герой и ограниченное число вторичных элементов.\n"
            "- Должен быть триггер и интрига без кликбейта-обмана.\n"
            "- Если релевантно, укажи короткий текст на обложке (до 4 слов).\n"
            "- Не добавляй технические параметры типа 16:9, 4k, lens, seed.\n"
            "- Верни только финальный промт."
        )
        user_prompt = (
            f"Заголовок видео:\n{(video_title or '').strip() or 'Без заголовка'}\n\n"
            "Суть видео и факты:\n"
            f"{source_outline[:5000]}\n\n"
            "Фрагмент сценария:\n"
            f"{source_script[:5000]}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.85)
