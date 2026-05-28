"""Azure Monitor Workspace — Prometheus query tool.

Queries the AMW Prometheus-compatible endpoint for metric time-series data.
Used to surface pre-incident trends in RCA reports (e.g. memory climbing
before an OOMKill, disk filling before an eviction).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool

logger = logging.getLogger(__name__)

_AMW_SCOPE = "https://prometheus.monitor.azure.com/.default"


def _amw_prometheus_available(sources: dict[str, dict]) -> bool:
    return bool(os.getenv("AMW_PROMETHEUS_ENDPOINT"))


def _amw_prometheus_extract_params(sources: dict[str, dict]) -> dict[str, Any]:
    return {"amw_endpoint": os.getenv("AMW_PROMETHEUS_ENDPOINT", "")}


@tool(
    name="query_amw_prometheus",
    display_name="AMW Prometheus",
    source="azure",
    description=(
        "Query Azure Monitor Workspace Prometheus for metric time-series data. "
        "Use this to retrieve pre-incident trends — e.g. memory growth, CPU spikes, "
        "disk fill rate — in the minutes or hours before an alert fired."
    ),
    use_cases=[
        "Check memory or CPU trend in the 30 minutes before an OOMKill or eviction",
        "Verify disk usage growth rate before a disk-full alert",
        "Correlate pod restart timing with metric anomalies",
        "Compare current metric value against recent baseline",
    ],
    requires=[],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "PromQL expression to evaluate. "
                    "Examples: "
                    "container_memory_working_set_bytes{namespace='chaos-targets',pod='rabbitmq-0'}, "
                    "rate(container_cpu_usage_seconds_total{namespace='chaos-targets'}[5m]), "
                    "kubelet_volume_stats_available_bytes{namespace='chaos-targets'}"
                ),
            },
            "start": {
                "type": "string",
                "description": (
                    "Range start as Unix timestamp or ISO8601. "
                    "Defaults to 30 minutes before 'end'."
                ),
            },
            "end": {
                "type": "string",
                "description": "Range end as Unix timestamp or ISO8601. Defaults to now.",
            },
            "step": {
                "type": "string",
                "description": "Query resolution step (e.g. '60s', '5m'). Defaults to '60s'.",
            },
        },
        "required": ["query"],
    },
    is_available=_amw_prometheus_available,
    extract_params=_amw_prometheus_extract_params,
)
def query_amw_prometheus(
    query: str,
    start: str = "",
    end: str = "",
    step: str = "60s",
    amw_endpoint: str = "",
    amw_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Query AMW Prometheus for time-series metric data.

    Returns up to 300 data points per series. The LLM should use the values
    to describe trends — rising, falling, stable — relative to the alert time.
    """
    # Env var always wins
    amw_endpoint = os.getenv("AMW_PROMETHEUS_ENDPOINT") or amw_endpoint

    if amw_backend is not None:
        return amw_backend.query_range(query=query, start=start, end=end, step=step)

    if not amw_endpoint:
        return {
            "source": "amw_prometheus",
            "available": False,
            "error": "AMW_PROMETHEUS_ENDPOINT not configured",
            "series": [],
        }

    now = time.time()
    end_ts = end or str(now)
    start_ts = start or str(now - 1800)  # 30 minutes

    try:
        import requests
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token = credential.get_token(_AMW_SCOPE)

        url = f"{amw_endpoint.rstrip('/')}/api/v1/query_range"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token.token}"},
            params={"query": query, "start": start_ts, "end": end_ts, "step": step},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        result = data.get("data", {}).get("result", [])
        series = []
        for s in result:
            series.append({
                "metric": s.get("metric", {}),
                "values": s.get("values", []),
            })

        return {
            "source": "amw_prometheus",
            "available": True,
            "query": query,
            "start": start_ts,
            "end": end_ts,
            "step": step,
            "total_series": len(series),
            "series": series,
        }

    except Exception as e:
        report_run_error(
            e,
            tool_name="query_amw_prometheus",
            source="azure",
            component="app.tools.AMWPrometheusQueryTool",
            method="requests.get /api/v1/query_range",
            logger=logger,
            extras={"query": query, "amw_endpoint": amw_endpoint},
        )
        return {
            "source": "amw_prometheus",
            "available": False,
            "query": query,
            "error": str(e),
            "series": [],
        }
