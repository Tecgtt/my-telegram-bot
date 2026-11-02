FROM python:3.10-slim

# Install system dependencies (ffmpeg and curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Setup non-root user for Hugging Face Spaces compatibility
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy dependency definition
COPY --chown=user requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy bot source code
COPY --chown=user . .

# Expose default port
ENV PORT=7860
EXPOSE 7860

# Run bot
CMD ["python3", "bot.py"]
