from __future__ import annotations
import logging
from typing import Any
from app.services.aks.management_client import list_aks_node_pools
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_cluster_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="get_aks_node_pool_health",
    source="aks",
    description="Get provisioning state and power state for each AKS node pool. Highlights any pools not in Succeeded/Running state.",
    use_cases=[
        "Checking if a node pool is stuck in creating/updating/deleting",
        "Verifying node pools are Running after a cluster operation",
        "Identifying node pools that have been stopped",
    ],
    requires=["cluster_name", "namespace"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def get_aks_node_pool_health(
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
    logger.info("[aks] get_aks_node_pool_health cluster=%s rg=%s", cluster_name, resource_group)
    try:
        pools = list_aks_node_pools(resource_group, cluster_name, subscription_id, credentials)
        health = [{"name": p["name"], "vm_size": p["vm_size"], "count": p["count"],
                   "provisioning_state": p["provisioning_state"], "power_state": p["power_state"],
                   "healthy": p["provisioning_state"] == "Succeeded" and p["power_state"] == "Running"}
                  for p in pools]
        unhealthy = [h for h in health if not h["healthy"]]
        return {"source": "aks", "available": True, "cluster_name": cluster_name,
                "total_pools": len(health), "pools": health, "unhealthy_pools": unhealthy, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="get_aks_node_pool_health", source="aks",
                         component="app.tools.AKSNodePoolHealthTool", method="agent_pools.list",
                         logger=logger, extras={"cluster_name": cluster_name, "resource_group": resource_group})
        return {"source": "aks", "available": False, "error": str(e)}
