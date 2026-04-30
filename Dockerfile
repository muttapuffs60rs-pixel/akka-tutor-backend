# Use a lightweight Python image
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (sometimes needed for PDF processing/Pyton libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Optimize pip to use less cache/memory
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Match the port Render is looking for
EXPOSE 8080

# Use the PORT environment variable if Render provides one, otherwise default to 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]