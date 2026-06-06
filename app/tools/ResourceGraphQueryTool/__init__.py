"""Azure Resource Graph query tool — cross-subscription KQL.

Answers "what exists / what's orphaned across Azure?" — e.g. NICs with no VM,
unattached disks, public IPs not associated with anything — in one query.
Gated purely on ``AZURE_SUBSCRIPTION_ID`` being set, mirroring the env-driven
availability of ``AMWPrometheusQueryTool`` (same ``source="azure"``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.azure_resourcegraph.resourcegraph_client import query_resource_graph
from app.tools._telemetry import report_run_error
from app.tools.tool_decorator import tool

logger = logging.getLogger(__name__)


def _resource_graph_available(_sources: dict[str, dict]) -> bool:
    return bool(os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("AZURE_VM_SUBSCRIPTION_ID"))


def _resource_graph_extract_params(_sources: dict[str, dict]) -> dict[str, Any]:
    return {
        "subscription_id": (
            os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("AZURE_VM_SUBSCRIPTION_ID", "")
        )
    }


def _configured_subscriptions(subscription_id: str) -> list[str]:
    """Subscriptions to query: explicit AZURE_RESOURCE_GRAPH_SUBSCRIPTIONS, else the default."""
    raw = os.getenv("AZURE_RESOURCE_GRAPH_SUBSCRIPTIONS", "").strip()
    if raw:
        subs = [s.strip() for s in raw.split(",") if s.strip()]
        if subs:
            return subs
    return [subscription_id] if subscription_id else []


@tool(
    name="query_azure_resource_graph",
    source="azure",
    display_name="Azure Resource Graph",
    description=(
        "Run a read-only KQL query against Azure Resource Graph across one or more "
        "subscriptions. Use this to inventory resources or find orphaned/misconfigured ones "
        "during an investigation — e.g. NICs with no VM, unattached disks, public IPs not "
        "associated with anything, resources by tag, or resources in a given region. "
        "Returns at most 200 rows; narrow the query if results are truncated."
    ),
    use_cases=[
        "Find orphaned resources after a cleanup (NICs/disks/IPs left behind)",
        "Inventory VMs or other resources across subscriptions and regions",
        "Locate a resource by name or tag to get its subscription and resource group",
        "Identify which NSGs, public IPs, or disks exist before drilling in",
    ],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "KQL query for Resource Graph. Examples: "
                    "\"Resources | where type =~ 'microsoft.network/networkinterfaces' "
                    "| where isnull(properties.virtualMachine) "
                    '| project name, resourceGroup, location"; '
                    "\"Resources | where type =~ 'microsoft.compute/disks' "
                    "| where properties.diskState == 'Unattached' | project name, resourceGroup\"; "
                    "\"Resources | where type =~ 'microsoft.compute/virtualmachines' "
                    '| project name, location, resourceGroup"'
                ),
            },
        },
        "required": ["query"],
    },
    is_available=_resource_graph_available,
    extract_params=_resource_graph_extract_params,
)
def query_azure_resource_graph_tool(
    query: str = "",
    subscription_id: str = "",
    credentials: dict[str, Any] | None = None,
    resource_graph_backend: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    subscription_id = (
        os.getenv("AZURE_SUBSCRIPTION_ID")
        or os.getenv("AZURE_VM_SUBSCRIPTION_ID")
        or subscription_id
    )

    if not query:
        return {
            "source": "azure",
            "available": True,
            "results": None,
            "note": "A KQL 'query' is required, e.g. \"Resources | project name, type | limit 10\".",
        }

    if resource_graph_backend is not None:
        backend_result: dict[str, Any] = resource_graph_backend.query(query=query)
        return backend_result

    subscriptions = _configured_subscriptions(subscription_id)
    if not subscriptions:
        return {
            "source": "azure",
            "available": False,
            "error": "AZURE_SUBSCRIPTION_ID is not configured",
            "results": None,
        }

    logger.info("[azure] resource_graph subs=%s query=%s", subscriptions, query)
    try:
        result = query_resource_graph(query, subscriptions, credentials)
        return {
            "source": "azure",
            "available": True,
            **result,
            "error": None,
        }
    except Exception as e:
        report_run_error(
            e,
            tool_name="query_azure_resource_graph",
            source="azure",
            component="app.tools.ResourceGraphQueryTool",
            method="resourcegraph.resources",
            logger=logger,
            extras={"query": query, "subscriptions": subscriptions},
        )
        return {"source": "azure", "available": False, "error": str(e), "results": None}
