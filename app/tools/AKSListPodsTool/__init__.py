"""AKS pod listing tool — Kubernetes Python SDK backed via Azure SDK auth."""

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
    name="list_aks_pods",
    source="aks_core",
    description="List all pods in an AKS namespace with their status, phase, restart counts, and conditions.",
    use_cases=[
        "Discovering what pods exist before fetching logs",
        "Finding which pods are crashing, pending, or failed",
        "Checking restart counts for crash-looping containers",
        "Getting pod IP addresses and node assignments",
    ],
    requires=["cluster_name"],
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "Kubernetes namespace to inspect. Use 'all' to scan all namespaces.",
            },
        },
        "required": ["namespace"],
    },
    is_available=aks_available_or_backend,
    extract_params=extract_aks_workload_params,
)
def list_aks_pods(
    namespace: str,
    cluster_name: str = "",
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    aks_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """List all pods in an AKS namespace with status, phase, restart counts, and conditions.

    When ``aks_backend`` is provided (e.g. a fixture backend from tests) the
    call short-circuits and returns the backend's response directly.
    Cluster connection params are pulled from integration config — the LLM only
    needs to specify namespace.
    """
    import os
    # Env vars always win — LLM-provided values are unreliable for infra params
    cluster_name = os.getenv("AKS_CLUSTER_NAME") or cluster_name
    resource_group = os.getenv("AKS_RESOURCE_GROUP") or resource_group
    subscription_id = (
        os.getenv("AKS_SUBSCRIPTION_ID") or os.getenv("AZURE_SUBSCRIPTION_ID") or subscription_id
    )
    logger.info("[aks] list_aks_pods cluster=%s ns=%s sub=%s rg=%s", cluster_name, namespace, subscription_id, resource_group)
    if aks_backend is not None:
        return cast(
            "dict[str, Any]",
            aks_backend.list_pods(cluster_name=cluster_name, namespace=namespace),
        )
    try:
        core_v1, _ = build_k8s_clients(
            cluster_name=cluster_name,
            resource_group=resource_group,
            subscription_id=subscription_id,
            credentials=credentials,
        )
        pod_list = (
            core_v1.list_pod_for_all_namespaces()
            if namespace == "all"
            else core_v1.list_namespaced_pod(namespace=namespace)
        )

        pods = []
        for pod in pod_list.items:
            containers = []
            for cs in pod.status.container_statuses or []:
                state: dict[str, Any] = {}
                if cs.state.running:
                    state = {"running": True, "started_at": str(cs.state.running.started_at)}
                elif cs.state.waiting:
                    state = {
                        "waiting": True,
                        "reason": cs.state.waiting.reason,
                        "message": cs.state.waiting.message,
                    }
                elif cs.state.terminated:
                    state = {
                        "terminated": True,
                        "exit_code": cs.state.terminated.exit_code,
                        "reason": cs.state.terminated.reason,
                        "message": cs.state.terminated.message,
                    }
                containers.append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": state,
                })
            conditions = [
                {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                for c in (pod.status.conditions or [])
            ]
            pods.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "node_name": pod.spec.node_name,
                "pod_ip": pod.status.pod_ip,
                "containers": containers,
                "conditions": conditions,
                "start_time": str(pod.status.start_time),
            })

        failing = [p for p in pods if p["phase"] not in ("Running", "Succeeded")]
        crashing = [p for p in pods if any(c["restart_count"] > 3 for c in p["containers"])]
        return {
            "source": "aks",
            "available": True,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "total_pods": len(pods),
            "pods": pods,
            "failing_pods": failing,
            "high_restart_pods": crashing,
            "error": None,
        }
    except Exception as e:
        report_run_error(
            e,
            tool_name="list_aks_pods",
            source="aks",
            component="app.tools.AKSListPodsTool",
            method="core_v1.list_namespaced_pod",
            logger=logger,
            extras={"cluster_name": cluster_name, "namespace": namespace},
        )
        return {"source": "aks", "available": False, "namespace": namespace, "error": str(e)}
