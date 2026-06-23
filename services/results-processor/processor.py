"""Results processor — consumes scan results from RabbitMQ, stores them to /data."""

import json
import logging
import os
import signal
import sqlite3
import time
from pathlib import Path

import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
SCAN_RESULTS_EXCHANGE = "scan.results"
RESULTS_QUEUE = "scan.results.processor"
DB_PATH = Path("/data/results.db")

_shutdown = False


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_results (
            scan_id      TEXT PRIMARY KEY,
            target       TEXT NOT NULL,
            scan_type    TEXT NOT NULL,
            status       TEXT NOT NULL,
            started_at   TEXT,
            completed_at TEXT,
            open_ports   TEXT,
            error        TEXT,
            raw_output   TEXT
        )
        """
    )
    conn.commit()
    return conn


def store_result(conn: sqlite3.Connection, result: dict):
    conn.execute(
        """
        INSERT OR REPLACE INTO scan_results
            (scan_id, target, scan_type, status, started_at, completed_at, open_ports, error, raw_output)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.get("scan_id"),
            result.get("target"),
            result.get("scan_type"),
            result.get("status"),
            result.get("started_at"),
            result.get("completed_at"),
            json.dumps(result.get("open_ports", [])),
            result.get("error"),
            result.get("raw_output"),
        ),
    )
    conn.commit()


def handle_result(conn: sqlite3.Connection, channel, method, properties, body):
    result = json.loads(body)
    scan_id = result.get("scan_id", "unknown")
    target = result.get("target", "unknown")
    status = result.get("status", "unknown")
    open_ports = result.get("open_ports", [])

    log.info(
        "scan_id=%-36s  target=%-30s  status=%-10s  open_ports=%d",
        scan_id, target, status, len(open_ports),
    )

    try:
        store_result(conn, result)
        channel.basic_ack(method.delivery_tag)
    except Exception as exc:
        log.error("Failed to store result for scan_id=%s: %s", scan_id, exc)
        channel.basic_nack(method.delivery_tag, requeue=False)


def connect_with_retry(url: str, retries: int = 10, delay: float = 3.0):
    for attempt in range(1, retries + 1):
        try:
            params = pika.URLParameters(url)
            connection = pika.BlockingConnection(params)
            log.info("Connected to RabbitMQ")
            return connection
        except Exception as exc:
            log.warning("RabbitMQ not ready (attempt %d/%d): %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay)


def main():
    global _shutdown

    def _handle_sigterm(signum, frame):
        global _shutdown
        log.info("SIGTERM received, shutting down gracefully...")
        _shutdown = True

    signal.signal(signal.SIGTERM, _handle_sigterm)

    conn = init_db()
    connection = connect_with_retry(RABBITMQ_URL)
    channel = connection.channel()

    channel.exchange_declare(exchange=SCAN_RESULTS_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=RESULTS_QUEUE, durable=True)
    channel.queue_bind(queue=RESULTS_QUEUE, exchange=SCAN_RESULTS_EXCHANGE)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(
        queue=RESULTS_QUEUE,
        on_message_callback=lambda ch, m, p, b: handle_result(conn, ch, m, p, b),
    )

    log.info("Waiting for scan results. Press CTRL+C to exit.")
    try:
        while not _shutdown:
            connection.process_data_events(time_limit=1)
    except KeyboardInterrupt:
        pass
    finally:
        connection.close()
        conn.close()
        log.info("Processor shut down cleanly.")


if __name__ == "__main__":
    main()
