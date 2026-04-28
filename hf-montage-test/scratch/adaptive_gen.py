import json
import os
import httpx
import re
from pathlib import Path
from dotenv import load_dotenv

# Загружаем ключи из корня проекта
load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

WORKSPACE_DIR = Path(__file__).parent.parent
TRANSCRIPT_PATH = WORKSPACE_DIR / "data/deepgram_transcript.json"
DATA_DIR = WORKSPACE_DIR / "data"
INDEX_PATH = WORKSPACE_DIR / "index.html"
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

def extract_json(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(text)

def generate_scene_plan(transcript_text):
    print("🤖 Анализирую текст через LLM...")
    prompt = f"""
    Ты - профессиональный видео-редактор. Тебе нужно разбить текст выступления на логические сцены.
    Для каждой сцены выдели заголовок и основные тезисы.
    
    ВАЖНО: Найди точную фразу в тексте, с которой должна начинаться сцена.
    
    Формат ответа строго JSON:
    {{
      "scenes": [
        {{
          "match_phrase": "точное начало фразы из текста",
          "title": "Хлесткий заголовок",
          "items": ["Тезис 1", "Тезис 2", "Тезис 3"]
        }}
      ]
    }}
    
    Текст:
    {transcript_text}
    """
    
    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "google/gemini-2.0-flash-001",
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=60.0
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        return extract_json(content)
    except Exception as e:
        print(f"❌ Ошибка LLM: {e}")
        return None

def align_scenes_with_timestamps(plan, all_words):
    print("⏱️ Сопоставляю сцены с таймингами...")
    aligned_scenes = []
    full_text = " ".join([w['word'].lower() for w in all_words])
    
    for i, s in enumerate(plan['scenes']):
        phrase = s['match_phrase'].lower()
        phrase_words = phrase.split()
        if not phrase_words: continue
            
        start_index = full_text.find(phrase_words[0])
        char_count = 0
        found_word_idx = 0
        for idx, w in enumerate(all_words):
            if char_count >= start_index:
                found_word_idx = idx
                break
            char_count += len(w['word']) + 1
            
        start_time = all_words[found_word_idx]['start']
        
        aligned_scenes.append({
            "id": f"scene-{i}",
            "start": start_time,
            "mode": "mode-full" if i == 0 else "mode-mini",
            "content": {
                "title": s['title'],
                "items": s['items']
            }
        })
    
    for i in range(len(aligned_scenes) - 1):
        aligned_scenes[i]['end'] = aligned_scenes[i+1]['start']
    aligned_scenes[-1]['end'] = all_words[-1]['end']
    return aligned_scenes

def update_index_html(scene_plan, all_words, video_filename="Untitled Video_1080p.mp4"):
    print(f"📝 Обновляю {INDEX_PATH.name}...")
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    
    total_dur = int(all_words[-1]['end'])
    
    # 1. Заменяем DURATIONS (очень аккуратно, по шаблону)
    # Ищем data-duration="..." и заменяем на новое значение
    html = re.sub(r'data-duration="\d+"', f'data-duration="{total_dur}"', html)
    
    # 2. Заменяем SRC (тоже аккуратно)
    # Ищем src="....mp4" и заменяем на наше видео
    html = re.sub(r'src="[^"]+\.mp4"', f'src="{video_filename}"', html)
    
    # 3. Обновляем TOTAL_DURATION в JS
    html = re.sub(r'const TOTAL_DURATION = \d+;', f'const TOTAL_DURATION = {total_dur + 1};', html)
    
    # 4. Обновляем JSON блоки (эти Regex работают хорошо)
    plan_json = json.dumps(scene_plan, ensure_ascii=False, indent=2)
    html = re.sub(
        r'(<script type="application/json" id="scene-plan">).*?(</script>)',
        f'\\1\n{plan_json}\n\\2',
        html,
        flags=re.DOTALL
    )
    
    cues = {}
    for scene in scene_plan:
        scene_words = [
            {"time": w['start'], "text": w['word']} 
            for w in all_words 
            if w['start'] >= scene['start'] and w['start'] < scene['end']
        ]
        cues[scene['id']] = scene_words
        
    cues_json = json.dumps(cues, ensure_ascii=False, indent=2)
    html = re.sub(
        r'(<script type="application/json" id="scene-word-cues">).*?(</script>)',
        f'\\1\n{cues_json}\n\\2',
        html,
        flags=re.DOTALL
    )
    
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

def main():
    if not TRANSCRIPT_PATH.exists():
        print(f"❌ Файл транскрипта не найден: {TRANSCRIPT_PATH}")
        return

    with open(TRANSCRIPT_PATH, 'r') as f:
        data = json.load(f)
    
    all_words = data['results']['channels'][0]['alternatives'][0]['words']
    full_text = data['results']['channels'][0]['alternatives'][0]['transcript']
    
    plan = generate_scene_plan(full_text)
    if not plan: return
    
    aligned_plan = align_scenes_with_timestamps(plan, all_words)
    update_index_html(aligned_plan, all_words)
    print("✅ Адаптивный монтаж готов! Можно запускать рендер.")

if __name__ == "__main__":
    main()
