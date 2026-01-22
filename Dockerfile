# Usamos a imagem oficial do Python 3.11 (leve e estável)
FROM python:3.11-slim

# Instala o FFmpeg e compiladores básicos (gcc) via gerenciador de pacotes do sistema
# Isso garante que o FFmpeg seja 100% compatível com este sistema
RUN apt-get update && \
    apt-get install -y ffmpeg gcc && \
    rm -rf /var/lib/apt/lists/*

# Define a pasta de trabalho
WORKDIR /app

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY . .

# Comando de inicialização (ajuste o nome do arquivo se não for main.py)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]