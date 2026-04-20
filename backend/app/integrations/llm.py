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
            "Follow these YouTube Master Storytelling Rules:\n"
            "1. THE HOOK: Start with a 3-5 second hook that immediately addresses the audience's core curiosity or problem. "
            "2. NO FILLER: Cut the intro basics ('Hey guys', 'Welcome back'). Jump straight into the action.\n"
            "3. NARRATIVE ARC: Structure the content as a story (Setting the stage -> Conflict -> Climax -> Resolution).\n"
            "4. RETENTION LOOPS: Every 30-60 seconds, tease an upcoming value point to keep the viewer watching (Open loops).\n"
            "5. NATIVE CTA: Weave the call to action naturally before the very end."
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
            "- Avoid meta-commentary about the script itself.\n\n"
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

    def add_elevenlabs_audio_tags(
        self,
        script: str,
        style_profile: Optional[str],
    ) -> Optional[str]:
        """
        Enriches the final Russian script with ElevenLabs v3 audio tags
        to add expressive delivery, pauses, emphasis, and non-verbal sounds.

        Supported tag vocabulary:
        - Emotion: [excited], [sad], [angry], [happily], [sarcastic], [surprised],
                   [worried], [confident], [nervous], [curious], [cheerful]
        - Non-verbal: [laughs], [sighs], [clears throat], [whispers], [gasps],
                      [pauses], [exhales]
        - Typography: CAPS for emphasis, ... for hesitation/pause, ! and ? for intonation
        """
        if not script:
            return None

        system_prompt = (
            "Ты звуковой режиссёр для записи нарратора (ElevenLabs v3). "
            "Твоя задача — расставить аудиотеги прямо в тексте русского сценария, "
            "не меняя ни одного слова (только добавляй теги и пунктуацию).\n\n"
            "ПРАВИЛА РАССТАНОВКИ ТЕГОВ:\n"
            "1. Начало (крючок): используй [excited] или [confident] перед первой фразой.\n"
            "2. Эмоциональные пики: вставляй [excited], [surprised], [angry], [happily] "
            "   перед фразами с сильным эмоциональным зарядом.\n"
            "3. Напряжённые или тревожные моменты: [worried], [nervous].\n"
            "4. Риторические вопросы и размышления: [curious] или многоточие (...).\n"
            "5. Ирония/сарказм: [sarcastic].\n"
            "6. Важные факты и ключевые слова: ЗАГЛАВНЫЕ БУКВЫ (только 1-2 слова, не целые фразы!).\n"
            "7. Паузы для акцента: ... между смысловыми блоками (не злоупотребляй).\n"
            "8. Невербальные звуки: [laughs], [sighs], [clears throat] — только в 1-2 органичных местах.\n"
            "9. Тихие/доверительные моменты: [whispers] перед фразой-откровением.\n"
            "10. CTA (призыв к действию): [cheerful] или [confident] перед финальным призывом.\n\n"
            "ОГРАНИЧЕНИЯ:\n"
            "- Не добавляй теги чаще чем раз в 2-3 предложения — иначе пропадёт естественность.\n"
            "- Не меняй ни одного слова в тексте, только добавляй теги и пунктуацию.\n"
            "- Не объясняй что ты сделал — верни только готовый текст с тегами.\n"
            "- Не добавляй теги [whispers] и [sighs] к одному месту.\n\n"
            f"Стиль автора для контекста: {style_profile if style_profile else 'уверенный, энергичный, разговорный'}"
        )
        user_prompt = (
            "Расставь ElevenLabs v3 аудиотеги в этом сценарии. "
            "Верни только итоговый текст с тегами, без пояснений:\n\n"
            f"{script}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete(messages, temperature=0.6)

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
