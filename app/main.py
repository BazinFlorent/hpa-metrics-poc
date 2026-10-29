"""Minimal FastAPI workload for a Kubernetes HPA/Prometheus demonstration."""

import asyncio
import time
from enum import Enum

from fastapi import FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="HPA Metrics POC", version="0.1.0")

REQUESTS = Counter(
    "demo_http_requests_total",
    "Completed work requests, partitioned by HTTP status and workload mode.",
    ["method", "mode", "status"],
)
IN_PROGRESS = Gauge(
    "demo_http_requests_in_progress",
    "Work requests currently being processed by this application instance.",
)
DURATION = Histogram(
    "demo_http_request_duration_seconds",
    "Time spent processing a work request.",
    ["mode"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


class WorkMode(str, Enum):
    cpu = "cpu"
    io = "io"


def consume_cpu(duration_ms: int) -> None:
    """Busy-loop until the requested duration has elapsed (demo only)."""
    deadline = time.perf_counter() + duration_ms / 1000
    while time.perf_counter() < deadline:
        pass


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/work", tags=["work"])
async def work(
    request: Request,
    mode: WorkMode = WorkMode.cpu,
    duration_ms: int = Query(default=100, ge=1, le=5000),
) -> dict[str, str | int]:
    """Generate a bounded CPU or I/O workload and expose per-pod metrics."""
    start = time.perf_counter()
    status = "200"
    IN_PROGRESS.inc()
    try:
        if mode is WorkMode.cpu:
            # Do not block the ASGI event loop with the busy-loop.
            await run_in_threadpool(consume_cpu, duration_ms)
        else:
            await asyncio.sleep(duration_ms / 1000)
        return {"mode": mode.value, "duration_ms": duration_ms, "pod": request.app.state.pod_name}
    except Exception:
        status = "500"
        raise
    finally:
        DURATION.labels(mode=mode.value).observe(time.perf_counter() - start)
        REQUESTS.labels(method="GET", mode=mode.value, status=status).inc()
        IN_PROGRESS.dec()


import os
app.state.pod_name = os.getenv("HOSTNAME", "local")
