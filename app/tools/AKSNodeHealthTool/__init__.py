from __future__ import annotations
import logging
from typing import Any
from app.services.aks.aks_k8s_client import build_k8s_clients
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_cluster_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="get_aks_node_health",
    source="aks",
    description="Get health status of all AKS nodes including conditions, capacity, and resource pressure flags.",
    use_cases=[
        "Checking for MemoryPressure, DiskPressure, or PIDPressure on nodes",
        "Verifying node Ready status during an incident",
        "Checking allocatable CPU/memory across the cluster",
    ],
    requires=["cluster_name"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def get_aks_node_health(
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
    logger.info("[aks] get_aks_node_health cluster=%s", cluster_name)
    try:
        core_v1, _ = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        node_list = core_v1.list_node()
        nodes = []
        for n in node_list.items:
            conditions = {c.type: c.status for c in (n.status.conditions or [])}
            capacity = dict(n.status.capacity or {})
            allocatable = dict(n.status.allocatable or {})
            nodes.append({
                "name": n.metadata.name,
                "ready": conditions.get("Ready") == "True",
                "memory_pressure": conditions.get("MemoryPressure") == "True",
                "disk_pressure": conditions.get("DiskPressure") == "True",
                "pid_pressure": conditions.get("PIDPressure") == "True",
                "instance_type": n.metadata.labels.get("node.kubernetes.io/instance-type") if n.metadata.labels else None,
                "zone": n.metadata.labels.get("topology.kubernetes.io/zone") if n.metadata.labels else None,
                "capacity_cpu": capacity.get("cpu"),
                "capacity_memory": capacity.get("memory"),
                "allocatable_cpu": allocatable.get("cpu"),
                "allocatable_memory": allocatable.get("memory"),
                "kernel_version": n.status.node_info.kernel_version if n.status.node_info else None,
                "kubelet_version": n.status.node_info.kubelet_version if n.status.node_info else None,
            })
        unhealthy = [n for n in nodes if not n["ready"] or n["memory_pressure"] or n["disk_pressure"]]
        return {"source": "aks", "available": True, "cluster_name": cluster_name,
                "total_nodes": len(nodes), "nodes": nodes, "unhealthy_nodes": unhealthy, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="get_aks_node_health", source="aks",
                         component="app.tools.AKSNodeHealthTool", method="core_v1.list_node",
                         logger=logger, extras={"cluster_name": cluster_name})
        return {"source": "aks", "available": False, "error": str(e)}
