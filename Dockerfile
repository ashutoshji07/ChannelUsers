FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy just the cookies file first
COPY cookies.txt .

# Copy the rest of the application
COPY . .

# Run the bot
CMD ["python", "yt_to_telegram.py"]
