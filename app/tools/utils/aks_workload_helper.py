"""Shared helpers for AKS workload investigation tools."""

from __future__ import annotations

from typing import Any


def _aks_creds(aks: dict) -> dict:
    """Extract Azure credentials from AKS source."""
    return {
        "subscription_id": aks.get("subscription_id", ""),
        "resource_group": aks.get("resource_group", ""),
        "credentials": aks.get("credentials"),
    }


def extract_aks_workload_params(sources: dict[str, dict]) -> dict[str, Any]:
    """Extract common parameters for AKS workload operations (pods/deployments/events/logs)."""
    aks = sources.get("aks")
    if aks is None:
        raise ValueError("Sources dictionary must contain an 'aks' key with cluster configuration")

    return {
        "cluster_name": aks.get("cluster_name", ""),
        "namespace": aks.get("namespace") or "all",
        "aks_backend": aks.get("_backend"),
        **_aks_creds(aks),
    }


def extract_aks_cluster_params(sources: dict[str, dict]) -> dict[str, Any]:
    """Extract parameters for cluster-level operations."""
    aks = sources.get("aks")
    if aks is None:
        raise ValueError("Sources dictionary must contain an 'aks' key with cluster configuration")

    return {
        "cluster_name": aks.get("cluster_name", ""),
        "resource_group": aks.get("resource_group", ""),
        **_aks_creds(aks),
    }
