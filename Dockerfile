FROM python:3.11-slim

# System deps: portaudio for sounddevice, pulseaudio for Linux audio output
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libpulse-dev \
    pulseaudio-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Install dependencies (layer-cached unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY src/ ./src/
COPY models/ ./models/

ENV PYTHONPATH=/app

CMD ["uv", "run", "python", "-m", "src.tts.main"]
