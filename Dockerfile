# Используем Node.js 22 как базу (важно для Hyperframes)
FROM node:22-bookworm

# Устанавливаем системные зависимости (Python, FFmpeg, Chrome deps)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    chromium \
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
RUN pip3 install --break-system-packages --no-cache-dir -r hf-montage-test/requirements.txt && \
    pip3 install --break-system-packages --no-cache-dir -r backend/requirements.txt

# Копируем зависимости Hyperframes
COPY hyperframes-auto/package*.json ./hyperframes-auto/
RUN cd hyperframes-auto && npm install

# Копируем весь код
COPY . .

# Устанавливаем рабочую директорию для инструментов
WORKDIR /app/hf-montage-test

# По умолчанию запускаем бесконечный цикл или по инструкции (можно переопределить в compose)
CMD ["tail", "-f", "/dev/null"]
