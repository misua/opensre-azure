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
    name="get_aks_deployment_status",
    source="aks",
    description="Get detailed rollout status for a specific AKS Deployment including replica history and conditions.",
    use_cases=[
        "Diagnosing a stuck or failed rollout",
        "Checking observed vs desired generation",
        "Inspecting deployment conditions after an alert",
    ],
    requires=["cluster_name"],
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "deployment_name": {"type": "string", "description": "Name of the deployment to inspect"},
        },
        "required": ["namespace", "deployment_name"],
    },
    is_available=aks_available_or_backend,
    extract_params=extract_aks_workload_params,
)
def get_aks_deployment_status(
    namespace: str,
    deployment_name: str = "",
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
    logger.info("[aks] get_aks_deployment_status cluster=%s ns=%s dep=%s", cluster_name, namespace, deployment_name)
    try:
        _, apps_v1 = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        d = apps_v1.read_namespaced_deployment_status(deployment_name, namespace)
        conditions = [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                      for c in (d.status.conditions or [])]
        return {
            "source": "aks", "available": True, "cluster_name": cluster_name,
            "name": d.metadata.name, "namespace": d.metadata.namespace,
            "desired": d.spec.replicas, "ready": d.status.ready_replicas or 0,
            "available": d.status.available_replicas or 0, "updated": d.status.updated_replicas or 0,
            "observed_generation": d.status.observed_generation,
            "desired_generation": d.metadata.generation,
            "strategy": d.spec.strategy.type if d.spec.strategy else None,
            "conditions": conditions, "error": None,
        }
    except Exception as e:
        report_run_error(e, tool_name="get_aks_deployment_status", source="aks",
                         component="app.tools.AKSDeploymentStatusTool",
                         method="apps_v1.read_namespaced_deployment_status",
                         logger=logger, extras={"cluster_name": cluster_name, "namespace": namespace})
        return {"source": "aks", "available": False, "error": str(e)}
