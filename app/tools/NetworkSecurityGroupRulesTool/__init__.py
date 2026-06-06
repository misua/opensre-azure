"""Azure Network Security Group rule-inspection tool.

Answers "is a firewall rule blocking traffic to this service/VM?" by dumping an
NSG's effective rules (custom + default), priority-ordered. Gated purely on
``AZURE_SUBSCRIPTION_ID`` being set, mirroring the env-driven availability of
``AMWPrometheusQueryTool`` (same ``source="azure"``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.azure_network.network_client import (
    get_nsg_rules,
    list_network_security_groups,
)
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool

logger = logging.getLogger(__name__)


def _azure_subscription_available(_sources: dict[str, dict]) -> bool:
    return bool(os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("AZURE_VM_SUBSCRIPTION_ID"))


def _azure_subscription_extract_params(_sources: dict[str, dict]) -> dict[str, Any]:
    return {
        "subscription_id": (
            os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("AZURE_VM_SUBSCRIPTION_ID", "")
        )
    }


@tool(
    name="get_nsg_rules",
    source="azure",
    display_name="Azure NSG rules",
    description=(
        "Inspect Azure Network Security Group (NSG) rules to diagnose blocked or allowed "
        "traffic. Provide an NSG name to get its full effective rule set (custom + default "
        "rules, priority-ordered). Omit the NSG name to list the NSGs in a resource group "
        "first. Use this when a service or VM is unreachable, a health probe fails, or you "
        "suspect a leftover deny/allow rule."
    ),
    use_cases=[
        "Check whether an NSG rule is blocking inbound/outbound traffic to a service or VM",
        "Find a leftover deny/allow rule after a VM or resource was deleted",
        "Confirm a subnet allows the outbound path a workload needs",
        "List which NSGs exist in a resource group before drilling into one",
    ],
    requires=[],
    input_schema={
        "type": "object",
        "properties": {
            "nsg_name": {
                "type": "string",
                "description": (
                    "Name of the NSG to inspect. Omit to list NSGs in the resource group "
                    "(or subscription) so you can pick one."
                ),
            },
            "resource_group": {
                "type": "string",
                "description": (
                    "Resource group the NSG lives in. Required when nsg_name is given; "
                    "for listing, omit to list across the whole subscription."
                ),
            },
        },
        "required": [],
    },
    is_available=_azure_subscription_available,
    extract_params=_azure_subscription_extract_params,
)
def get_nsg_rules_tool(
    nsg_name: str = "",
    resource_group: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    nsg_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    subscription_id = (
        os.getenv("AZURE_SUBSCRIPTION_ID")
        or os.getenv("AZURE_VM_SUBSCRIPTION_ID")
        or subscription_id
    )

    if nsg_backend is not None:
        if nsg_name:
            backend_rules: dict[str, Any] = nsg_backend.get_nsg_rules(
                resource_group=resource_group, nsg_name=nsg_name
            )
            return backend_rules
        backend_list: dict[str, Any] = nsg_backend.list_nsgs(resource_group=resource_group)
        return backend_list

    if not subscription_id:
        return {
            "source": "azure",
            "available": False,
            "error": "AZURE_SUBSCRIPTION_ID is not configured",
            "rules": None,
        }

    # No NSG named yet → list candidates so the LLM can pick one (mirrors list_azure_vms).
    if not nsg_name:
        logger.info("[azure] list NSGs sub=%s rg=%s", subscription_id, resource_group or "<all>")
        try:
            groups = list_network_security_groups(subscription_id, resource_group, credentials)
            return {
                "source": "azure",
                "available": True,
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "total": len(groups),
                "network_security_groups": groups,
                "note": "Call again with an nsg_name (and its resource_group) to see its rules.",
                "error": None,
            }
        except Exception as e:
            report_run_error(
                e,
                tool_name="get_nsg_rules",
                source="azure",
                component="app.tools.NetworkSecurityGroupRulesTool",
                method="network_security_groups.list",
                logger=logger,
                extras={"subscription_id": subscription_id, "resource_group": resource_group},
            )
            return {"source": "azure", "available": False, "error": str(e), "rules": None}

    if not resource_group:
        return {
            "source": "azure",
            "available": True,
            "rules": None,
            "note": "resource_group is required together with nsg_name.",
        }

    logger.info("[azure] get_nsg_rules rg=%s nsg=%s", resource_group, nsg_name)
    try:
        result = get_nsg_rules(subscription_id, resource_group, nsg_name, credentials)
        return {
            "source": "azure",
            "available": True,
            "subscription_id": subscription_id,
            "nsg": result,
            "error": None,
        }
    except Exception as e:
        report_run_error(
            e,
            tool_name="get_nsg_rules",
            source="azure",
            component="app.tools.NetworkSecurityGroupRulesTool",
            method="network_security_groups.get",
            logger=logger,
            extras={"resource_group": resource_group, "nsg_name": nsg_name},
        )
        return {"source": "azure", "available": False, "error": str(e), "nsg": None}
