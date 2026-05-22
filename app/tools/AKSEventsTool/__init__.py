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
    name="get_aks_events",
    source="aks",
    description="Get recent Kubernetes events in an AKS namespace. Filters Warning events by default.",
    use_cases=[
        "Finding OOMKilled, BackOff, FailedMount, or probe failure events",
        "Correlating Kubernetes events with an alert timestamp",
        "Identifying scheduling failures or resource pressure events",
    ],
    requires=["cluster_name"],
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string", "description": "Kubernetes namespace. Use 'all' for all namespaces."},
            "warnings_only": {"type": "boolean", "default": True, "description": "Only return Warning events"},
        },
        "required": ["namespace"],
    },
    is_available=aks_available_or_backend,
    extract_params=extract_aks_workload_params,
)
def get_aks_events(
    namespace: str,
    warnings_only: bool = True,
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
    logger.info("[aks] get_aks_events cluster=%s ns=%s warnings_only=%s", cluster_name, namespace, warnings_only)
    try:
        core_v1, _ = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        ev_list = (core_v1.list_event_for_all_namespaces() if namespace == "all"
                   else core_v1.list_namespaced_event(namespace=namespace))
        events = []
        for e in ev_list.items:
            if warnings_only and e.type != "Warning":
                continue
            events.append({
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "namespace": e.metadata.namespace,
                "count": e.count,
                "first_time": str(e.first_timestamp),
                "last_time": str(e.last_timestamp),
            })
        events.sort(key=lambda x: x["last_time"] or "", reverse=True)
        return {"source": "aks", "available": True, "cluster_name": cluster_name,
                "namespace": namespace, "total": len(events), "events": events[:50], "error": None}
    except Exception as e:
        report_run_error(e, tool_name="get_aks_events", source="aks",
                         component="app.tools.AKSEventsTool", method="core_v1.list_namespaced_event",
                         logger=logger, extras={"cluster_name": cluster_name, "namespace": namespace})
        return {"source": "aks", "available": False, "error": str(e)}
