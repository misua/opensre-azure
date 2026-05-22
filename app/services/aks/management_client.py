"""Azure management plane helpers for AKS — cluster and node pool metadata."""
from __future__ import annotations

import logging
from typing import Any

from app.services.aks.utils import stored_credentials_to_azure_creds

logger = logging.getLogger(__name__)


def _get_credential(credentials: dict[str, Any] | None) -> Any:
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    sp = stored_credentials_to_azure_creds(credentials)
    if sp:
        return ClientSecretCredential(**sp)
    return DefaultAzureCredential()


def list_aks_clusters(
    subscription_id: str,
    credentials: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from azure.mgmt.containerservice import ContainerServiceClient
    credential = _get_credential(credentials)
    client = ContainerServiceClient(credential, subscription_id)
    clusters = []
    for c in client.managed_clusters.list():
        clusters.append({
            "name": c.name,
            "location": c.location,
            "resource_group": c.id.split("/resourcegroups/")[1].split("/")[0] if c.id else "",
            "kubernetes_version": c.kubernetes_version,
            "provisioning_state": c.provisioning_state,
            "power_state": c.power_state.code if c.power_state else "Unknown",
            "node_count": sum(p.count or 0 for p in (c.agent_pool_profiles or [])),
            "fqdn": c.fqdn,
            "tags": dict(c.tags or {}),
        })
    return clusters


def describe_aks_cluster(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from azure.mgmt.containerservice import ContainerServiceClient
    credential = _get_credential(credentials)
    client = ContainerServiceClient(credential, subscription_id)
    c = client.managed_clusters.get(resource_group, cluster_name)
    return {
        "name": c.name,
        "location": c.location,
        "kubernetes_version": c.kubernetes_version,
        "provisioning_state": c.provisioning_state,
        "power_state": c.power_state.code if c.power_state else "Unknown",
        "fqdn": c.fqdn,
        "node_resource_group": c.node_resource_group,
        "network_plugin": c.network_profile.network_plugin if c.network_profile else None,
        "dns_prefix": c.dns_prefix,
        "rbac_enabled": c.enable_rbac,
        "oidc_issuer": c.oidc_issuer_profile.issuer_url if c.oidc_issuer_profile else None,
        "addons": {k: v.enabled for k, v in (c.addon_profiles or {}).items()},
        "tags": dict(c.tags or {}),
    }


def list_aks_node_pools(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    credentials: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from azure.mgmt.containerservice import ContainerServiceClient
    credential = _get_credential(credentials)
    client = ContainerServiceClient(credential, subscription_id)
    pools = []
    for p in client.agent_pools.list(resource_group, cluster_name):
        pools.append({
            "name": p.name,
            "vm_size": p.vm_size,
            "count": p.count,
            "min_count": p.min_count,
            "max_count": p.max_count,
            "enable_auto_scaling": p.enable_auto_scaling,
            "mode": p.mode,
            "os_type": p.os_type,
            "kubernetes_version": p.current_orchestrator_version,
            "provisioning_state": p.provisioning_state,
            "power_state": p.power_state.code if p.power_state else "Unknown",
            "node_taints": list(p.node_taints or []),
            "node_labels": dict(p.node_labels or {}),
        })
    return pools
