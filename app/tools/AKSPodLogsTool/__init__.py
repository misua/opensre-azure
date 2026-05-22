from __future__ import annotations
import logging
from typing import Any
from app.services.aks.aks_k8s_client import build_k8s_clients
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_workload_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="get_aks_pod_logs",
    source="aks",
    description="Fetch logs from a specific AKS pod. Supports previous container instance, tail lines, and time window.",
    use_cases=[
        "Reading crash logs from a failed container",
        "Inspecting application errors after a restart",
        "Fetching broker or consumer logs during an incident",
    ],
    requires=["cluster_name"],
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "pod_name": {"type": "string", "description": "Full pod name"},
            "container": {"type": "string", "description": "Container name (omit for single-container pods)", "default": ""},
            "tail_lines": {"type": "integer", "default": 100, "description": "Last N lines to return"},
            "previous": {"type": "boolean", "default": False, "description": "Fetch logs from previous (crashed) container instance"},
        },
        "required": ["namespace", "pod_name"],
    },
    is_available=aks_available_or_backend,
    extract_params=extract_aks_workload_params,
)
def get_aks_pod_logs(
    namespace: str,
    pod_name: str = "",
    container: str = "",
    tail_lines: int = 100,
    previous: bool = False,
    cluster_name: str = "",
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    import os
    cluster_name = os.getenv("AKS_CLUSTER_NAME") or cluster_name
    resource_group = os.getenv("AKS_RESOURCE_GROUP") or resource_group
    subscription_id = os.getenv("AKS_SUBSCRIPTION_ID") or os.getenv("AZURE_SUBSCRIPTION_ID") or subscription_id
    logger.info("[aks] get_aks_pod_logs cluster=%s ns=%s pod=%s previous=%s", cluster_name, namespace, pod_name, previous)
    try:
        core_v1, _ = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        kwargs: dict[str, Any] = {"tail_lines": tail_lines, "previous": previous}
        if container:
            kwargs["container"] = container
        logs = core_v1.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        return {
            "source": "aks", "available": True, "cluster_name": cluster_name,
            "namespace": namespace, "pod_name": pod_name, "container": container,
            "previous": previous, "tail_lines": tail_lines,
            "logs": logs, "line_count": len(logs.splitlines()), "error": None,
        }
    except Exception as e:
        report_run_error(e, tool_name="get_aks_pod_logs", source="aks",
                         component="app.tools.AKSPodLogsTool", method="core_v1.read_namespaced_pod_log",
                         logger=logger, extras={"cluster_name": cluster_name, "namespace": namespace, "pod": pod_name})
        return {"source": "aks", "available": False, "error": str(e)}
