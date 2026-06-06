"""Azure management-plane helpers for Network Security Groups — rule inspection.

Mirrors ``app/services/azure_vm/vm_client.py``: lazy SDK imports, credential
resolution via explicit Service Principal or ``DefaultAzureCredential``, and
plain-dict returns suitable for direct JSON serialisation into tool results.

Returns both the NSG's custom ``security_rules`` and the platform
``default_security_rules`` (e.g. AllowVnetInBound / DenyAllInBound), because the
default rules are frequently the ones that actually decide whether traffic is
allowed — the upstream reference script omitted them.
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


def _enum_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _serialize_rule(rule: Any) -> dict[str, Any]:
    """Flatten a SecurityRule into a plain dict, handling singular/plural fields.

    The Azure SDK exposes both ``source_port_range`` (single) and
    ``source_port_ranges`` (list); the same applies to address prefixes. We
    surface whichever is populated so the LLM sees the effective value.
    """
    return {
        "name": rule.name,
        "priority": rule.priority,
        "direction": _enum_str(rule.direction),
        "access": _enum_str(rule.access),
        "protocol": _enum_str(rule.protocol),
        "source_port_range": rule.source_port_range,
        "source_port_ranges": list(rule.source_port_ranges or []),
        "destination_port_range": rule.destination_port_range,
        "destination_port_ranges": list(rule.destination_port_ranges or []),
        "source_address_prefix": rule.source_address_prefix,
        "source_address_prefixes": list(rule.source_address_prefixes or []),
        "destination_address_prefix": rule.destination_address_prefix,
        "destination_address_prefixes": list(rule.destination_address_prefixes or []),
        "description": rule.description,
    }


def _rules_sorted(rules: list[Any] | None) -> list[dict[str, Any]]:
    serialized = [_serialize_rule(r) for r in (rules or [])]
    # Lower priority number = evaluated first; sort so the LLM reads them in order.
    return sorted(serialized, key=lambda r: (r["priority"] is None, r["priority"] or 0))


def list_network_security_groups(
    subscription_id: str,
    resource_group: str = "",
    credentials: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """List NSGs in a resource group (or the whole subscription) with a rule count."""
    from azure.mgmt.network import NetworkManagementClient

    credential = _get_credential(credentials)
    client = NetworkManagementClient(credential, subscription_id)

    iterator = (
        client.network_security_groups.list(resource_group)
        if resource_group
        else client.network_security_groups.list_all()
    )

    groups: list[dict[str, Any]] = []
    for nsg in iterator:
        subnets = [s.id for s in (nsg.subnets or [])]
        nics = [n.id for n in (nsg.network_interfaces or [])]
        groups.append(
            {
                "name": nsg.name,
                "location": nsg.location,
                "custom_rule_count": len(nsg.security_rules or []),
                "attached_subnets": subnets,
                "attached_nics": nics,
            }
        )
    return groups


def get_nsg_rules(
    subscription_id: str,
    resource_group: str,
    nsg_name: str,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the custom and default security rules for a single NSG, priority-ordered."""
    from azure.mgmt.network import NetworkManagementClient

    credential = _get_credential(credentials)
    client = NetworkManagementClient(credential, subscription_id)
    nsg = client.network_security_groups.get(resource_group, nsg_name)

    return {
        "name": nsg.name,
        "resource_group": resource_group,
        "location": nsg.location,
        "attached_subnets": [s.id for s in (nsg.subnets or [])],
        "attached_nics": [n.id for n in (nsg.network_interfaces or [])],
        "security_rules": _rules_sorted(nsg.security_rules),
        "default_security_rules": _rules_sorted(nsg.default_security_rules),
    }
