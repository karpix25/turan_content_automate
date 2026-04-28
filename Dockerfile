# Используем Node.js как базу (важно для Remotion)
FROM node:20-bullseye

# Устанавливаем системные зависимости (Python, FFmpeg, Chrome deps)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости Python
COPY hf-montage-test/requirements.txt ./hf-montage-test/
COPY backend/requirements.txt ./backend/
RUN pip3 install --no-cache-dir -r hf-montage-test/requirements.txt && \
    pip3 install --no-cache-dir -r backend/requirements.txt

# Копируем зависимости Remotion
COPY remotion-auto/package*.json ./remotion-auto/
RUN cd remotion-auto && npm install

# Копируем весь код
COPY . .

# Устанавливаем рабочую директорию для инструментов
WORKDIR /app/hf-montage-test

# По умолчанию запускаем бесконечный цикл или по инструкции (можно переопределить в compose)
CMD ["tail", "-f", "/dev/null"]
