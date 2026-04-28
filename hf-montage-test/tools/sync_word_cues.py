#!/usr/bin/env python3
import json
import re
from pathlib import Path

def sync_cues():
    root = Path.cwd()
    transcript_path = root / "data" / "deepgram_transcript.json"
    plan_path = root / "data" / "scene-plan.generated.json"
    index_path = root / "index.html"

    if not transcript_path.exists() or not plan_path.exists():
        print("Missing transcript or plan file.")
        return

    transcript = json.loads(transcript_path.read_text())
    plan = json.loads(plan_path.read_text())

    # Get words from Deepgram payload
    # Path: results.channels[0].alternatives[0].words
    try:
        words = transcript['results']['channels'][0]['alternatives'][0]['words']
    except (KeyError, IndexError):
        print("Could not find words in transcript JSON.")
        return

    scene_word_cues = []
    for scene in plan:
        start = scene['start']
        end = scene['end']
        
        # Filter words that start within this scene
        scene_words = [
            {"time": round(w['start'], 3), "text": w['punctuated_word'] if 'punctuated_word' in w else w['word']}
            for w in words
            if w['start'] >= start and w['start'] < end
        ]
        scene_word_cues.append(scene_words)

    # Inject into index.html
    html = index_path.read_text(encoding="utf-8")
    cues_json = json.dumps(scene_word_cues, ensure_ascii=False, indent=2)
    indented = "\n".join(f"      {line}" for line in cues_json.splitlines())
    repl = f'<script id="scene-word-cues" type="application/json">\n{indented}\n    </script>'
    
    pattern = r'<script id="scene-word-cues" type="application/json">[\s\S]*?</script>'
    updated, count = re.subn(pattern, repl, html, count=1)
    
    if count == 1:
        index_path.write_text(updated, encoding="utf-8")
        print(f"Successfully injected {len(scene_word_cues)} scene word cues into index.html")
    else:
        print("Could not find <script id='scene-word-cues'> in index.html")

if __name__ == "__main__":
    sync_cues()
