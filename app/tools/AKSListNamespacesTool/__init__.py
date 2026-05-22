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
    name="list_aks_namespaces",
    source="aks",
    description="List all Kubernetes namespaces in the AKS cluster with their status.",
    use_cases=[
        "Discovering namespaces before scoping further queries",
        "Checking namespace phase and conditions",
    ],
    requires=["cluster_name", "namespace"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def list_aks_namespaces(
    cluster_name: str = "",
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    aks_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    import os
    cluster_name = os.getenv("AKS_CLUSTER_NAME") or cluster_name
    resource_group = os.getenv("AKS_RESOURCE_GROUP") or resource_group
    subscription_id = os.getenv("AKS_SUBSCRIPTION_ID") or os.getenv("AZURE_SUBSCRIPTION_ID") or subscription_id
    logger.info("[aks] list_aks_namespaces cluster=%s", cluster_name)
    try:
        core_v1, _ = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        ns_list = core_v1.list_namespace()
        namespaces = [{"name": n.metadata.name, "phase": n.status.phase,
                       "labels": dict(n.metadata.labels or {})} for n in ns_list.items]
        return {"source": "aks", "available": True, "cluster_name": cluster_name,
                "total": len(namespaces), "namespaces": namespaces, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="list_aks_namespaces", source="aks",
                         component="app.tools.AKSListNamespacesTool", method="core_v1.list_namespace",
                         logger=logger, extras={"cluster_name": cluster_name})
        return {"source": "aks", "available": False, "error": str(e)}
