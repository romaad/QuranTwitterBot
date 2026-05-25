FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directory for SQLite persistence — mount a volume here
RUN mkdir -p /app/data

CMD ["python", "bot.py"]
