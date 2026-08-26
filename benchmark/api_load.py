"""Minimal Mock-mode API baseline load test for v0.1.0.

Stdlib only so it can run inside the python:3.12-slim benchmark container.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import platform
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUEST_TIMEOUT_SECONDS = 30.0

PAYLOAD = {
    "session_id": "bench-v0.1.0",
    "message": "推荐一台5000元以内适合程序员的笔记本",
}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _send_request(base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/chat"
    body = json.dumps(PAYLOAD, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
            latency_ms = (time.perf_counter() - started) * 1000
            return {
                "ok": True,
                "status": response.status,
                "latency_ms": latency_ms,
                "timeout": False,
                "request_id_present": bool(response.headers.get("X-Request-ID")),
                "trace_id_present": bool(response.headers.get("X-Trace-ID")),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status": exc.code,
            "latency_ms": latency_ms,
            "timeout": False,
            "request_id_present": bool(exc.headers.get("X-Request-ID") if exc.headers else False),
            "trace_id_present": bool(exc.headers.get("X-Trace-ID") if exc.headers else False),
            "error": f"HTTP {exc.code}",
        }
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        timeout = isinstance(exc.reason, TimeoutError)
        return {
            "ok": False,
            "status": None,
            "latency_ms": latency_ms,
            "timeout": timeout,
            "request_id_present": False,
            "trace_id_present": False,
            "error": "timeout" if timeout else str(exc.reason),
        }


def _run_load(base_url: str, concurrency: int, total_requests: int) -> tuple[list[dict[str, Any]], float]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/health/live", timeout=10) as response:
        response.read()

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_send_request, base_url) for _ in range(total_requests)]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "ok": False,
                        "status": None,
                        "latency_ms": 0.0,
                        "timeout": False,
                        "request_id_present": False,
                        "trace_id_present": False,
                        "error": f"client_error: {exc!r}",
                    }
                )
    duration = time.perf_counter() - started
    return results, duration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.concurrency < 1 or args.requests < 1:
        parser.error("--concurrency and --requests must be positive")

    print(
        f"load_test starting base_url={args.base_url} concurrency={args.concurrency} requests={args.requests}",
        flush=True,
    )
    results, duration = _run_load(args.base_url, args.concurrency, args.requests)

    latencies = [item["latency_ms"] for item in results if item.get("ok")]
    success_count = sum(1 for item in results if item.get("ok"))
    timeout_count = sum(1 for item in results if item.get("timeout"))
    header_ok_count = sum(
        1
        for item in results
        if item.get("ok") and item.get("request_id_present") and item.get("trace_id_present")
    )
    error_samples = list(dict.fromkeys(item.get("error") for item in results if item.get("error")))[:10]

    summary = {
        "scenario": "v0.1.0_api_baseline",
        "endpoint": "POST /api/v1/chat",
        "payload": PAYLOAD,
        "concurrency": args.concurrency,
        "total_requests": args.requests,
        "successful_requests": success_count,
        "failed_requests": args.requests - success_count,
        "success_rate": round(success_count / args.requests, 4),
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(args.requests / duration, 2) if duration else 0.0,
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": round(_percentile(latencies, 50), 2) if latencies else None,
            "p95": round(_percentile(latencies, 95), 2) if latencies else None,
            "p99": round(_percentile(latencies, 99), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
        "timeout_requests": timeout_count,
        "observability_headers_present": header_ok_count,
        "error_samples": error_samples,
        "environment": {"llm_provider": "mock", "python": platform.python_version()},
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"result_written path={output_path.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
