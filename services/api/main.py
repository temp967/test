import ipaddress
import json
import os
import re
import uuid
from datetime import datetime, timezone

import pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

app = FastAPI(title="Scan API")

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
SCAN_JOBS_QUEUE = "scan.jobs"

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]

_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def _is_safe_target(target: str) -> bool:
    try:
        addr = ipaddress.ip_address(target)
        return not any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(target))


class ScanRequest(BaseModel):
    target: str
    scan_type: str = "port_scan"

    @field_validator("scan_type")
    @classmethod
    def validate_scan_type(cls, v: str) -> str:
        allowed = {"port_scan"}
        if v not in allowed:
            raise ValueError(f"scan_type must be one of {allowed}")
        return v


class ScanResponse(BaseModel):
    scan_id: str
    status: str
    target: str
    scan_type: str
    queued_at: str


def _publish_job(job: dict):
    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue=SCAN_JOBS_QUEUE, durable=True)
    channel.basic_publish(
        exchange="",
        routing_key=SCAN_JOBS_QUEUE,
        body=json.dumps(job),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()


@app.post("/scans", response_model=ScanResponse, status_code=202)
def submit_scan(request: ScanRequest):
    if not _is_safe_target(request.target):
        raise HTTPException(
            status_code=400,
            detail="Target must be a public hostname or IP address.",
        )

    scan_id = str(uuid.uuid4())
    queued_at = datetime.now(timezone.utc).isoformat()

    job = {
        "scan_id": scan_id,
        "target": request.target,
        "scan_type": request.scan_type,
        "queued_at": queued_at,
    }

    _publish_job(job)

    return ScanResponse(
        scan_id=scan_id,
        status="queued",
        target=request.target,
        scan_type=request.scan_type,
        queued_at=queued_at,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
