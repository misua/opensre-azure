from __future__ import annotations
import logging
from typing import Any
from app.services.aks.management_client import describe_aks_cluster
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_cluster_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="describe_aks_cluster",
    source="aks",
    description="Get detailed AKS cluster metadata: Kubernetes version, network config, RBAC, addons, and OIDC issuer.",
    use_cases=[
        "Checking cluster Kubernetes version for compatibility issues",
        "Verifying RBAC and addon configuration",
        "Getting OIDC issuer URL for workload identity troubleshooting",
    ],
    requires=["cluster_name", "namespace"],
    input_schema={"type": "object", "properties": {}, "required": []},
    is_available=aks_available_or_backend,
    extract_params=extract_aks_cluster_params,
)
def describe_aks_cluster_tool(
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
    logger.info("[aks] describe_aks_cluster cluster=%s rg=%s", cluster_name, resource_group)
    try:
        info = describe_aks_cluster(resource_group, cluster_name, subscription_id, credentials)
        return {"source": "aks", "available": True, **info, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="describe_aks_cluster", source="aks",
                         component="app.tools.AKSDescribeClusterTool", method="managed_clusters.get",
                         logger=logger, extras={"cluster_name": cluster_name, "resource_group": resource_group})
        return {"source": "aks", "available": False, "error": str(e)}
