from __future__ import annotations

import logging
import os
from typing import Any

from app.services.azure_vm.vm_client import list_azure_vms
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.availability import azure_vm_available_or_backend
from app.tools.utils.azure_vm_helper import extract_azure_vm_params

logger = logging.getLogger(__name__)


@tool(
    name="list_azure_vms",
    source="azure_vm",
    display_name="Azure VMs",
    description=(
        "List Azure virtual machines (Windows and Linux) in the subscription or a resource "
        "group, with power state, VM size, OS type, and provisioning state. Use this first to "
        "discover which VM an alert refers to before drilling into its status."
    ),
    use_cases=[
        "Discover which VMs exist and their current power state",
        "Find the VM named in a VM-down or high-resource alert",
        "Check whether a VM is running, stopped, or deallocated",
    ],
    requires=[],
    input_schema={
        "type": "object",
        "properties": {
            "resource_group": {
                "type": "string",
                "description": (
                    "Resource group to scope the listing to. Omit to list across the whole "
                    "subscription."
                ),
            }
        },
        "required": [],
    },
    is_available=azure_vm_available_or_backend,
    extract_params=extract_azure_vm_params,
)
def list_azure_vms_tool(
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    azure_vm_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    subscription_id = (
        os.getenv("AZURE_VM_SUBSCRIPTION_ID")
        or os.getenv("AZURE_SUBSCRIPTION_ID")
        or subscription_id
    )
    resource_group = resource_group or os.getenv("AZURE_VM_RESOURCE_GROUP", "")
    logger.info(
        "[azure_vm] list_azure_vms sub=%s rg=%s", subscription_id, resource_group or "<all>"
    )

    if azure_vm_backend is not None:
        backend_result: dict[str, Any] = azure_vm_backend.list_vms(resource_group=resource_group)
        return backend_result

    try:
        vms = list_azure_vms(subscription_id, resource_group, credentials)
        return {
            "source": "azure_vm",
            "available": True,
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "total": len(vms),
            "vms": vms,
            "error": None,
        }
    except Exception as e:
        report_run_error(
            e,
            tool_name="list_azure_vms",
            source="azure_vm",
            component="app.tools.AzureVMListTool",
            method="virtual_machines.list",
            logger=logger,
            extras={"subscription_id": subscription_id, "resource_group": resource_group},
        )
        return {"source": "azure_vm", "available": False, "error": str(e), "vms": []}
