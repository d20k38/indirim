FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy app
COPY . .

# Create non-root user
RUN useradd -m appuser || true
USER appuser

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app", "--workers", "1", "--threads", "4"]
