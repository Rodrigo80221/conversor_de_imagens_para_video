FROM python:3.11-slim

# Instala FFmpeg, gcc e Chromium + dependências necessárias para rodar headless no container
RUN apt-get update && \
    apt-get install -y \
      ffmpeg \
      gcc \
      chromium \
      fonts-dejavu-core \
      fonts-liberation \
      fonts-noto-color-emoji \
      curl \
      libnss3 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdrm2 \
      libxkbcommon0 \
      libxcomposite1 \
      libxdamage1 \
      libxrandr2 \
      libgbm1 \
      libasound2 \
      libpangocairo-1.0-0 \
      libpango-1.0-0 \
      libgtk-3-0 \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Baixar e instalar fontes personalizadas
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    curl -L "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf" -o /usr/share/fonts/truetype/custom/Poppins-SemiBold.ttf && \
    curl -L "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-SemiBold.ttf" -o /usr/share/fonts/truetype/custom/Montserrat-SemiBold.ttf && \
    curl -L "https://github.com/google/fonts/raw/main/ofl/inter/static/Inter-Bold.ttf" -o /usr/share/fonts/truetype/custom/Inter-Bold.ttf && \
    fc-cache -fv

# 👇 ADICIONE ESTA LINHA
ENV CHROME_BIN=/usr/bin/chromium

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]