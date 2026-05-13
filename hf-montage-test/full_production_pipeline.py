import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path

# Конфигурация путей
PROJECT_ROOT = Path(__file__).parent.parent
HYPERFRAMES_DIR = PROJECT_ROOT.parent / "hyperframes-auto"
PIPELINE_SCRIPT = PROJECT_ROOT / "tools" / "smart_montage_pipeline.py"

# Telegram настройки (взяты из твоего .env)
TELEGRAM_BOT_TOKEN = "8604244712:AAHCW9nhY4xpJ2VQ9YfrySPMkje6eIsF78I"
TELEGRAM_CHAT_ID = "-1003833134695"

def run_command(cmd, cwd=None, env=None):
    print(f"\n🚀 Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"❌ Command failed with code {result.returncode}")
        sys.exit(1)

def send_to_telegram(file_path, caption):
    print(f"\n📤 Sending to Telegram: {file_path}")
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"document": f}
        )
    if resp.status_code == 200:
        print("✅ File sent successfully!")
    else:
        print(f"❌ Failed to send file: {resp.text}")

def main():
    parser = argparse.ArgumentParser(description="Full AI Video Production Pipeline")
    parser.add_argument("--input", required=True, help="Input video file from HeyGen")
    args = parser.parse_args()

    input_video = Path(args.input).absolute()
    if not input_video.exists():
        print(f"❌ Input file not found: {input_video}")
        sys.exit(1)

    # 1. Подготовка: Копируем видео в Hyperframes
    print("\n--- STAGE 1: PREPARATION ---")
    dest_video = HYPERFRAMES_DIR / "assets" / "input" / "source.mp4"
    dest_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_video, dest_video)
    print(f"Copied {input_video.name} to {dest_video}")

    # 2. Анализ и Сценарий (smart_montage_pipeline)
    print("\n--- STAGE 2: AI ANALYSIS & SCENE PLAN ---")
    # Пробрасываем ключи если их нет в окружении
    env = os.environ.copy()
    if "DEEPGRAM_API_KEY" not in env:
        env["DEEPGRAM_API_KEY"] = "450ea5b9ba0d4ea36246787fc264da1067357284"
    if "OPENROUTER_API_KEY" not in env:
        env["OPENROUTER_API_KEY"] = "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"

    run_command([
        "python3", str(PIPELINE_SCRIPT),
        "--video", str(dest_video),
        "--llm-model", "openai/gpt-4o-mini"
    ], cwd=PROJECT_ROOT, env=env)

    # 3. Рендер видео (Hyperframes)
    print("\n--- STAGE 3: HYPERFRAMES RENDERING ---")
    render_output = HYPERFRAMES_DIR / "renders" / "final_video.mp4"
    render_output.parent.mkdir(parents=True, exist_ok=True)

    run_command([
        "npm", "run", "prepare:heygen", "--",
        "--video", str(dest_video),
    ], cwd=HYPERFRAMES_DIR)
    run_command([
        "npm", "run", "apply:scene-plan",
    ], cwd=HYPERFRAMES_DIR)
    run_command([
        "npm", "run", "direct:timeline",
    ], cwd=HYPERFRAMES_DIR)
    run_command([
        "npm", "run", "generate:prompts",
    ], cwd=HYPERFRAMES_DIR)
    if os.environ.get("KIE_API_KEY", "").strip():
        run_command([
            "npm", "run", "generate:images",
        ], cwd=HYPERFRAMES_DIR)
    else:
        print("⚠️ KIE_API_KEY is not set; rendering with fallback HTML visuals.")
    run_command([
        "npm", "run", "render", "--",
        "--output", str(render_output),
        "--quality", "standard",
    ], cwd=HYPERFRAMES_DIR)

    # 4. Отправка в Telegram
    print("\n--- STAGE 4: TELEGRAM NOTIFICATION ---")
    if render_output.exists():
        send_to_telegram(render_output, f"🎬 Видео готово!\nИсходник: {input_video.name}")
    else:
        print(f"❌ Rendered file not found at {render_output}")

if __name__ == "__main__":
    main()
