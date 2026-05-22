from __future__ import annotations
import logging
from typing import Any, cast
from app.services.aks.aks_k8s_client import build_k8s_clients
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.aks_workload_helper import extract_aks_workload_params
from app.tools.utils.availability import aks_available_or_backend

logger = logging.getLogger(__name__)


@tool(
    name="list_aks_deployments",
    source="aks",
    description="List all Deployments in an AKS namespace with replica counts, availability, and rollout status.",
    use_cases=[
        "Checking if a deployment is degraded or rolling out",
        "Finding deployments with unavailable replicas",
        "Correlating deployment state with an alert",
    ],
    requires=["cluster_name"],
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string", "description": "Kubernetes namespace. Use 'all' for all namespaces."},
        },
        "required": ["namespace"],
    },
    is_available=aks_available_or_backend,
    extract_params=extract_aks_workload_params,
)
def list_aks_deployments(
    namespace: str,
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
    logger.info("[aks] list_aks_deployments cluster=%s ns=%s", cluster_name, namespace)
    if aks_backend is not None:
        return cast("dict[str, Any]", aks_backend.list_deployments(cluster_name=cluster_name, namespace=namespace))
    try:
        _, apps_v1 = build_k8s_clients(cluster_name, resource_group, subscription_id, credentials)
        dep_list = (apps_v1.list_deployment_for_all_namespaces() if namespace == "all"
                    else apps_v1.list_namespaced_deployment(namespace=namespace))
        deployments = []
        for d in dep_list.items:
            conditions = [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                          for c in (d.status.conditions or [])]
            deployments.append({
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "desired": d.spec.replicas,
                "ready": d.status.ready_replicas or 0,
                "available": d.status.available_replicas or 0,
                "updated": d.status.updated_replicas or 0,
                "strategy": d.spec.strategy.type if d.spec.strategy else None,
                "conditions": conditions,
            })
        degraded = [d for d in deployments if d["ready"] < (d["desired"] or 0)]
        return {"source": "aks", "available": True, "cluster_name": cluster_name, "namespace": namespace,
                "total": len(deployments), "deployments": deployments, "degraded": degraded, "error": None}
    except Exception as e:
        report_run_error(e, tool_name="list_aks_deployments", source="aks",
                         component="app.tools.AKSListDeploymentsTool", method="apps_v1.list_namespaced_deployment",
                         logger=logger, extras={"cluster_name": cluster_name, "namespace": namespace})
        return {"source": "aks", "available": False, "error": str(e)}
