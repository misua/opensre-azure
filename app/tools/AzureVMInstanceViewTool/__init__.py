from __future__ import annotations

import logging
import os
from typing import Any

from app.services.azure_vm.vm_client import get_azure_vm_instance_view
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool
from app.tools.utils.availability import azure_vm_available_or_backend
from app.tools.utils.azure_vm_helper import extract_azure_vm_params

logger = logging.getLogger(__name__)


@tool(
    name="get_azure_vm_status",
    source="azure_vm",
    display_name="Azure VM status",
    description=(
        "Get the detailed runtime status (instance view) of a single Azure VM: power and "
        "provisioning state, OS name/version, VM agent health, disk states, and boot "
        "diagnostics. Call list_azure_vms first if you do not know the VM name."
    ),
    use_cases=[
        "Confirm whether an alerting VM is running, stopped, or deallocated",
        "Check VM agent health and provisioning state during an incident",
        "Inspect disk attach state for a disk-related VM alert",
    ],
    requires=[],
    input_schema={
        "type": "object",
        "properties": {
            "vm_name": {
                "type": "string",
                "description": "Name of the virtual machine to inspect.",
            },
            "resource_group": {
                "type": "string",
                "description": "Resource group the VM lives in. Defaults to the configured VM resource group.",
            },
        },
        "required": ["vm_name"],
    },
    is_available=azure_vm_available_or_backend,
    extract_params=extract_azure_vm_params,
)
def get_azure_vm_status_tool(
    vm_name: str = "",
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

    # vm_name is supplied by the LLM, not by extract_params, so it is absent when this
    # tool is pre-seeded. Return a clean hint rather than erroring in that case.
    if not vm_name:
        return {
            "source": "azure_vm",
            "available": True,
            "instance_view": None,
            "note": "vm_name is required — call list_azure_vms first, then re-call with a VM name.",
        }

    logger.info("[azure_vm] get_azure_vm_status rg=%s vm=%s", resource_group, vm_name)

    if azure_vm_backend is not None:
        backend_result: dict[str, Any] = azure_vm_backend.instance_view(
            resource_group=resource_group, vm_name=vm_name
        )
        return backend_result

    try:
        view = get_azure_vm_instance_view(resource_group, vm_name, subscription_id, credentials)
        return {
            "source": "azure_vm",
            "available": True,
            "subscription_id": subscription_id,
            "instance_view": view,
            "error": None,
        }
    except Exception as e:
        report_run_error(
            e,
            tool_name="get_azure_vm_status",
            source="azure_vm",
            component="app.tools.AzureVMInstanceViewTool",
            method="virtual_machines.instance_view",
            logger=logger,
            extras={"resource_group": resource_group, "vm_name": vm_name},
        )
        return {"source": "azure_vm", "available": False, "error": str(e), "instance_view": None}
