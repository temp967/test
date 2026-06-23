FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data is mounted as a named volume for result persistence.
RUN mkdir -p /data

CMD ["python", "processor.py"]
