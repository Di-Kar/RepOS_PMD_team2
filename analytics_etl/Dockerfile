FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/

# Create state directory
RUN mkdir -p /app/state

# Set environment defaults
ENV PYTHONUNBUFFERED=1
ENV ETL_STATE_DIR=/app/state

ENTRYPOINT ["python", "src/main.py"]
