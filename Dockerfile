FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .
COPY telegram_handler.py .
COPY cookies.txt .

# Expose the port that the application will run on
EXPOSE $PORT

# Run the application
CMD ["python", "main.py"]
