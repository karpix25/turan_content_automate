# Используем Node.js 22 как базу (важно для Hyperframes)
FROM node:22-bookworm-slim

# Устанавливаем системные зависимости (Python, FFmpeg, Chrome deps)
ENV DEBIAN_FRONTEND=noninteractive
ENV CHROME_BIN=/usr/bin/chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    python3 \
    python3-pip \
    ffmpeg \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости Python
COPY hf-montage-test/requirements.txt ./hf-montage-test/
COPY backend/requirements.txt ./backend/
RUN pip3 install --break-system-packages --no-cache-dir -r hf-montage-test/requirements.txt && \
    pip3 install --break-system-packages --no-cache-dir -r backend/requirements.txt

# Копируем зависимости Remotion и Hyperframes
COPY remotion-auto/package*.json ./remotion-auto/
COPY hyperframes-auto/package*.json ./hyperframes-auto/
RUN cd remotion-auto && npm ci --no-audit --no-fund
RUN cd hyperframes-auto && npm ci --omit=dev --no-audit --no-fund

# Копируем весь код
COPY . .

# Устанавливаем рабочую директорию для инструментов
WORKDIR /app/hf-montage-test

# По умолчанию запускаем бесконечный цикл или по инструкции (можно переопределить в compose)
CMD ["tail", "-f", "/dev/null"]
