"""Scanner service — consumes scan jobs from RabbitMQ and runs nmap."""

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

import nmap
import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
SCAN_JOBS_QUEUE = "scan.jobs"
SCAN_RESULTS_EXCHANGE = "scan.results"

_shutdown = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_port_scan(target: str) -> dict:
    nm = nmap.PortScanner()
    nm.scan(target, arguments="-T4 -F")
    open_ports = []
    if target in nm.all_hosts():
        tcp = nm[target].get("tcp", {})
        open_ports = [port for port, info in tcp.items() if info["state"] == "open"]
    return {"open_ports": open_ports, "raw_output": nm.get_nmap_last_output().decode("utf-8", errors="replace")}


def process_job(channel, method, properties, body):
    job = json.loads(body)
    scan_id = job["scan_id"]
    target = job["target"]
    scan_type = job["scan_type"]
    started_at = _now()

    log.info("Starting %s scan for %s (scan_id=%s)", scan_type, target, scan_id)

    result = {
        "scan_id": scan_id,
        "target": target,
        "scan_type": scan_type,
        "started_at": started_at,
    }

    try:
        if scan_type == "port_scan":
            scan_data = run_port_scan(target)
        else:
            raise ValueError(f"Unknown scan_type: {scan_type}")

        result.update({"status": "completed", "completed_at": _now(), **scan_data})
        log.info("Completed scan_id=%s: %d open ports", scan_id, len(result.get("open_ports", [])))
    except Exception as exc:
        result.update({"status": "failed", "completed_at": _now(), "error": str(exc)})
        log.error("scan_id=%s failed: %s", scan_id, exc)

    channel.exchange_declare(exchange=SCAN_RESULTS_EXCHANGE, exchange_type="fanout", durable=True)
    channel.basic_publish(
        exchange=SCAN_RESULTS_EXCHANGE,
        routing_key="",
        body=json.dumps(result),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    channel.basic_ack(method.delivery_tag)


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

    connection = connect_with_retry(RABBITMQ_URL)
    channel = connection.channel()
    channel.queue_declare(queue=SCAN_JOBS_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=SCAN_JOBS_QUEUE, on_message_callback=process_job)

    log.info("Waiting for scan jobs. Press CTRL+C to exit.")
    try:
        while not _shutdown:
            connection.process_data_events(time_limit=1)
    except KeyboardInterrupt:
        pass
    finally:
        connection.close()
        log.info("Scanner shut down cleanly.")


if __name__ == "__main__":
    main()
