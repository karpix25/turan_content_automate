# Remotion Auto Montage

Проект заточен под твой формат: разговорный YouTube (15-20 минут), быстрый темп речи, чередование чистого кадра с лицом и графических оверлеев.
Формат кадра: `16:9` (`1920x1080`).

## Быстрый запуск

```bash
cd remotion-auto
npm install
npm run render:auto
```

По умолчанию берутся файлы из `../hf-montage-test`:
- `source_optimized_45s.mp4`
- `data/scene-plan.generated.json`
- `data/scene-word-cues.generated.json`

Результат: `../hf-montage-test/renders/remotion-auto.mp4`.

## Пошаговая настройка под твой стиль

### Шаг 1. Правила монтажа (темп и чередование)

Файл: `src/montage/youtube-rules.ts`

Главные параметры:
- `cleanSegmentSec`: сколько держим чистое лицо без крупной плашки.
- `lowerThirdSegmentSec`: сколько держим нижнюю плашку.
- `chartOrInsightSegmentSec`: длина блока графика или выделенной мысли.
- `maxTitleLines`, `maxSteps`, `maxBars`, `maxCueWords`: ограничители, чтобы не перегружать кадр.
- `openingSec`: длина открывающего блока (сейчас 15 секунд).

Режимы можно задавать прямо в `scene-plan.generated.json` через `mode`:
- `clean` / `face`
- `lower-third` / `overlay`
- `chart`
- `insight`

Если `mode` не указан, система сама чередует режимы в YouTube-стиле.

Пресеты (задаются через `--preset`):
- `balanced`: базовый баланс, около 50% чистого лица.
- `calm`: более спокойный монтаж, меньше графики.
- `data`: больше акцента на цифры, факты, сравнения.

### Шаг 2. Дизайн (цвета, шрифты, атмосфера)

Файл: `src/montage/theme.ts`

Тема по умолчанию: `youtubeBusiness`.

Что крутить:
- `fontMain`, `fontAccent`
- `textMain`, `textMuted`
- `accent`, `cta`
- `bgOverlay`, `panel`, `panelStrong`, `insightGlow`

### Шаг 3. Визуализация мысли и графики

Файл: `src/AutoMontage.tsx`

Что уже реализовано:
- `clean`: чистый разговорный кадр + аккуратные cue-чипы.
- `lowerThird`: нижняя плашка с тезисами.
- `chart`: боковая карточка с графиками (`bars`).
- `insight`: крупная подсветка ключевой мысли (`insight`) + CTA.

### Шаг 4. Рендер с параметрами

```bash
cd remotion-auto
npm run render:auto -- \
  --video ../hf-montage-test/source_optimized_45s.mp4 \
  --scene-plan ../hf-montage-test/data/scene-plan.generated.json \
  --word-cues ../hf-montage-test/data/scene-word-cues.generated.json \
  --out ../hf-montage-test/renders/remotion-custom.mp4 \
  --theme youtubeBusiness \
  --preset balanced \
  --cue-window-sec 0.95
```

Быстрые превью пресетов (45 секунд):

```bash
cd remotion-auto
npm run render:auto -- --preset balanced --max-duration-sec 45 --out ../hf-montage-test/renders/preview-balanced.mp4
npm run render:auto -- --preset calm --max-duration-sec 45 --out ../hf-montage-test/renders/preview-calm.mp4
npm run render:auto -- --preset data --max-duration-sec 45 --out ../hf-montage-test/renders/preview-data.mp4
```

## Полный автопайплайн с твоим генератором сцен

```bash
cd hf-montage-test
python3 tools/smart_montage_pipeline.py \
  --video source_optimized_45s.mp4 \
  --index index.html \
  --language ru \
  --deepgram-model nova-3 \
  --utt-split 0.65 \
  --max-scenes 8

cd ../remotion-auto
npm run render:auto
```

## Dry run (без рендера)

```bash
cd remotion-auto
npm run render:auto -- --dry-run
```
