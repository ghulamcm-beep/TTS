FROM python:3.11-slim

# Install system dependencies for sounddevice/PulseAudio
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libpulse-dev \
    pulseaudio \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Piper TTS
RUN pip install piper-tts

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy application
COPY src/ /app/src/
COPY models/ /app/models/

WORKDIR /app

ENV PYTHONPATH=/app

CMD ["python", "-m", "src.tts.main"]
