from __future__ import annotations
import logging
from typing import Any
from app.services.aks.management_client import list_aks_clusters
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_cluster_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="list_aks_clusters",
    source="aks",
    description="List all AKS clusters in the Azure subscription with their location, Kubernetes version, and power state.",
    use_cases=[
        "Discovering which AKS clusters exist in the subscription",
        "Checking cluster power state and provisioning status",
        "Finding the cluster hosting an affected workload",
    ],
    requires=["cluster_name"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def list_aks_clusters_tool(
    cluster_name: str = "",
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    import os
    subscription_id = os.getenv("AKS_SUBSCRIPTION_ID") or os.getenv("AZURE_SUBSCRIPTION_ID") or subscription_id
    logger.info("[aks] list_aks_clusters sub=%s", subscription_id)
    try:
        clusters = list_aks_clusters(subscription_id, credentials)
        return {"source": "aks", "available": True, "subscription_id": subscription_id,
                "total": len(clusters), "clusters": clusters, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="list_aks_clusters", source="aks",
                         component="app.tools.AKSListClustersTool", method="managed_clusters.list",
                         logger=logger, extras={"subscription_id": subscription_id})
        return {"source": "aks", "available": False, "error": str(e)}
