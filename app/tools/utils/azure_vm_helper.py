"""Shared helpers for Azure VM investigation tools."""

from __future__ import annotations

from typing import Any


def extract_azure_vm_params(sources: dict[str, dict]) -> dict[str, Any]:
    """Extract common parameters for Azure VM operations (list / instance view)."""
    vm = sources.get("azure_vm")
    if vm is None:
        raise ValueError("Sources dictionary must contain an 'azure_vm' key with VM configuration")

    return {
        "subscription_id": vm.get("subscription_id", ""),
        "resource_group": vm.get("resource_group", ""),
        "credentials": vm.get("credentials"),
        "azure_vm_backend": vm.get("_backend"),
    }
