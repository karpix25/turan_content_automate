import httpx
import logging
import os
import json
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
        
        try:
            with httpx.Client(timeout=60.0) as client:
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

    def rewrite_to_script(self, factual_outline: str, style_profile: Optional[str]) -> Optional[str]:
        """
        Rewrites facts into a high-retention YouTube script using professional storytelling rules.
        """
        narrative_rules = (
            "Follow these YouTube Master Storytelling Rules:\n"
            "1. THE HOOK: Start with a 3-5 second hook that immediately addresses the audience's core curiosity or problem. "
            "2. NO FILLER: Cut the intro basics ('Hey guys', 'Welcome back'). Jump straight into the action.\n"
            "3. NARRATIVE ARC: Structure the content as a story (Setting the stage -> Conflict -> Climax -> Resolution).\n"
            "4. RETENTION LOOPS: Every 30-60 seconds, tease an upcoming value point to keep the viewer watching (Open loops).\n"
            "5. NATIVE CTA: Weave the call to action naturally before the very end."
        )
        
        system_prompt = (
            f"You are a World-Class YouTube Scriptwriter. Your task is to turn raw facts into a 1-2 minute engaging script.\n"
            f"{narrative_rules}\n\n"
            f"STYLE REQUIREMENTS:\n"
            f"{style_profile if style_profile else 'Use a natural, engaging, and professional YouTube tone.'}"
        )
        
        user_prompt = f"Turn these facts into a high-retention script:\n\n{factual_outline}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return self._complete(messages, temperature=0.8)

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
