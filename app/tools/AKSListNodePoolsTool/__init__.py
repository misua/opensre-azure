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
    name="list_aks_node_pools",
    source="aks",
    description="List all node pools in the AKS cluster with VM SKU, count, autoscaling config, and power state.",
    use_cases=[
        "Checking node pool scale-down or provisioning issues",
        "Verifying node pool VM sizes and autoscaling bounds",
        "Identifying stopped or degraded node pools",
    ],
    requires=["cluster_name"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def list_aks_node_pools_tool(
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
    logger.info("[aks] list_aks_node_pools cluster=%s rg=%s", cluster_name, resource_group)
    try:
        pools = list_aks_node_pools(resource_group, cluster_name, subscription_id, credentials)
        degraded = [p for p in pools if p["provisioning_state"] != "Succeeded" or p["power_state"] != "Running"]
        return {"source": "aks", "available": True, "cluster_name": cluster_name,
                "total": len(pools), "node_pools": pools, "degraded": degraded, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="list_aks_node_pools", source="aks",
                         component="app.tools.AKSListNodePoolsTool", method="agent_pools.list",
                         logger=logger, extras={"cluster_name": cluster_name, "resource_group": resource_group})
        return {"source": "aks", "available": False, "error": str(e)}
