"""Azure management-plane helpers for Virtual Machines — inventory and instance view.

Mirrors the AKS management client (``app/services/aks/management_client.py``): lazy
SDK imports, credential resolution via explicit Service Principal or
``DefaultAzureCredential``, and plain-dict returns suitable for direct JSON
serialisation into tool results.
"""

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


def _status_by_prefix(statuses: list[Any] | None, prefix: str) -> str:
    """Return the suffix of the first status code matching ``prefix`` (e.g. 'PowerState/')."""
    for s in statuses or []:
        code = getattr(s, "code", "") or ""
        if code.startswith(prefix):
            return code[len(prefix) :]
    return "unknown"


def _enum_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _rg_from_id(resource_id: str | None) -> str:
    if not resource_id:
        return ""
    lowered = resource_id.lower()
    marker = "/resourcegroups/"
    if marker not in lowered:
        return ""
    start = lowered.index(marker) + len(marker)
    return resource_id[start:].split("/")[0]


def list_azure_vms(
    subscription_id: str,
    resource_group: str = "",
    credentials: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """List VMs in a resource group (or the whole subscription) with power state.

    Power state requires a per-VM instance-view call; it is best-effort and falls
    back to 'unknown' if that call fails (e.g. missing read permission on one VM).
    """
    from azure.mgmt.compute import ComputeManagementClient

    credential = _get_credential(credentials)
    client = ComputeManagementClient(credential, subscription_id)

    iterator = (
        client.virtual_machines.list(resource_group)
        if resource_group
        else client.virtual_machines.list_all()
    )

    vms: list[dict[str, Any]] = []
    for vm in iterator:
        rg = resource_group or _rg_from_id(vm.id)
        os_disk = (
            vm.storage_profile.os_disk
            if vm.storage_profile and vm.storage_profile.os_disk
            else None
        )
        power = "unknown"
        try:
            iv = client.virtual_machines.instance_view(rg, str(vm.name))
            power = _status_by_prefix(iv.statuses, "PowerState/")
        except Exception:  # noqa: BLE001 — instance view is best-effort enrichment
            logger.debug("[azure_vm] instance_view failed for %s/%s", rg, vm.name)
        vms.append(
            {
                "name": vm.name,
                "resource_group": rg,
                "location": vm.location,
                "vm_size": vm.hardware_profile.vm_size if vm.hardware_profile else None,
                "os_type": _enum_str(os_disk.os_type) if os_disk else None,
                "power_state": power,
                "provisioning_state": vm.provisioning_state,
                "tags": dict(vm.tags or {}),
            }
        )
    return vms


def get_azure_vm_instance_view(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the detailed runtime status (instance view) for a single VM."""
    from azure.mgmt.compute import ComputeManagementClient

    credential = _get_credential(credentials)
    client = ComputeManagementClient(credential, subscription_id)
    iv = client.virtual_machines.instance_view(resource_group, vm_name)

    agent = iv.vm_agent
    agent_status = "unknown"
    if agent and agent.statuses:
        agent_status = agent.statuses[0].display_status or agent.statuses[0].code or "unknown"

    return {
        "name": vm_name,
        "resource_group": resource_group,
        "power_state": _status_by_prefix(iv.statuses, "PowerState/"),
        "provisioning_state": _status_by_prefix(iv.statuses, "ProvisioningState/"),
        "computer_name": iv.computer_name,
        "os_name": iv.os_name,
        "os_version": iv.os_version,
        "vm_agent": {
            "status": agent_status,
            "version": agent.vm_agent_version if agent else None,
        },
        "disks": [
            {
                "name": d.name,
                "statuses": [s.display_status or s.code for s in (d.statuses or [])],
            }
            for d in (iv.disks or [])
        ],
        "boot_diagnostics_console_uri": (
            iv.boot_diagnostics.console_screenshot_blob_uri if iv.boot_diagnostics else None
        ),
        "statuses": [
            {
                "code": s.code,
                "level": _enum_str(getattr(s, "level", None)),
                "display_status": s.display_status,
                "time": str(s.time) if getattr(s, "time", None) else None,
            }
            for s in (iv.statuses or [])
        ],
    }
