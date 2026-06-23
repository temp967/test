#!/usr/bin/env bash
# Grader script: verifies that results-processor cannot reach the internet.
set -euo pipefail

SERVICE="results-processor"

echo "==> Checking internet isolation for $SERVICE..."

if docker compose exec "$SERVICE" \
    python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5); print('reachable')" \
    2>/dev/null | grep -q reachable; then
    echo "FAIL: $SERVICE can reach the internet. Check docker-compose.yml networks."
    exit 1
else
    echo "PASS: $SERVICE correctly cannot reach the internet."
fi

echo ""
echo "==> Checking RabbitMQ reachability from $SERVICE..."

RABBITMQ_USER=$(grep RABBITMQ_USER .env | cut -d= -f2)
RABBITMQ_PASS=$(grep RABBITMQ_PASS .env | cut -d= -f2)

if docker compose exec "$SERVICE" \
    python -c "import pika; c=pika.BlockingConnection(pika.URLParameters('amqp://${RABBITMQ_USER}:${RABBITMQ_PASS}@rabbitmq:5672/')); c.close(); print('ok')" \
    2>/dev/null | grep -q ok; then
    echo "PASS: $SERVICE can reach RabbitMQ over internal-net."
else
    echo "FAIL: $SERVICE cannot reach RabbitMQ. Check that both are on internal-net."
    exit 1
fi
