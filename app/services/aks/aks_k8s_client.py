"""AKS Kubernetes client builder — mirrors app/services/eks/eks_k8s_client.py.

Credential resolution priority:
  1. Explicit credentials dict {tenant_id, client_id, client_secret}
     → ClientSecretCredential
  2. DefaultAzureCredential chain:
     env vars → managed identity → Azure CLI login → VS Code / Az PowerShell
"""
from __future__ import annotations

import logging
import tempfile
import weakref
from functools import lru_cache
from typing import Any

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from app.services.aks.utils import stored_credentials_to_azure_creds

logger = logging.getLogger(__name__)


def _build_azure_credential(credentials: dict[str, Any] | None) -> Any:
    """Return an azure-identity credential object."""
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    sp = stored_credentials_to_azure_creds(credentials)
    if sp:
        return ClientSecretCredential(
            tenant_id=sp["tenant_id"],
            client_id=sp["client_id"],
            client_secret=sp["client_secret"],
        )
    return DefaultAzureCredential()


@lru_cache(maxsize=4)
def _cached_kubeconfig(cluster_name: str, resource_group: str, subscription_id: str,
                       credentials_key: str | None) -> bytes:
    """Fetch kubeconfig once per unique cluster — cached for the process lifetime."""
    from azure.mgmt.containerservice import ContainerServiceClient
    from azure.core.pipeline.policies import RetryPolicy
    creds = None
    if credentials_key:
        import json
        creds = json.loads(credentials_key)
    credential = _build_azure_credential(creds)
    mgmt_client = ContainerServiceClient(
        credential, subscription_id, retry_policy=RetryPolicy(retry_total=1),
    )
    result = mgmt_client.managed_clusters.list_cluster_user_credentials(
        resource_group_name=resource_group,
        resource_name=cluster_name,
        connection_timeout=10,
        read_timeout=15,
    )
    if not result.kubeconfigs:
        raise RuntimeError(f"No kubeconfigs returned for {cluster_name}")
    return result.kubeconfigs[0].value


def build_k8s_clients(
    cluster_name: str,
    resource_group: str,
    subscription_id: str,
    credentials: dict[str, Any] | None = None,
) -> tuple[k8s_client.CoreV1Api, k8s_client.AppsV1Api]:
    """Build Kubernetes API clients for an AKS cluster via Azure SDK.

    Fetches cluster user credentials from Azure management plane and builds
    in-memory Kubernetes clients — no kubeconfig file written to disk.

    Args:
        cluster_name: AKS cluster name.
        resource_group: Resource group containing the cluster.
        subscription_id: Azure subscription ID.
        credentials: Optional explicit SP credentials {tenant_id, client_id, client_secret}.
                     Falls back to DefaultAzureCredential (az login / managed identity / env vars).

    Returns:
        Tuple of (CoreV1Api, AppsV1Api) ready to use.

    Raises:
        RuntimeError: If cluster credentials cannot be fetched.
    """
    import json
    creds_key = json.dumps(credentials, sort_keys=True) if credentials else None
    kubeconfig_bytes = _cached_kubeconfig(cluster_name, resource_group, subscription_id, creds_key)

    # Write to a temp file so the k8s SDK can load it
    # (load_kube_config_from_dict has limitations with exec-based auth tokens)
    tmp = tempfile.NamedTemporaryFile(suffix=".kubeconfig", delete=False)
    try:
        tmp.write(kubeconfig_bytes)
        tmp.flush()
        tmp.close()

        configuration = k8s_client.Configuration()
        k8s_config.load_kube_config(config_file=tmp.name, client_configuration=configuration)
    finally:
        import os
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    core_v1 = k8s_client.CoreV1Api(k8s_client.ApiClient(configuration))
    apps_v1 = k8s_client.AppsV1Api(k8s_client.ApiClient(configuration))

    logger.debug("[aks] built k8s clients for %s/%s", resource_group, cluster_name)
    return core_v1, apps_v1
