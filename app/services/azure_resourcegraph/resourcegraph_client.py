"""Azure Resource Graph helper — cross-subscription KQL queries.

Mirrors ``app/services/azure_vm/vm_client.py``: lazy SDK imports, credential
resolution via explicit Service Principal or ``DefaultAzureCredential``, and
plain-dict returns suitable for direct JSON serialisation into tool results.

Resource Graph only returns resources the calling identity is allowed to read,
so the breadth of results is bounded by the identity's RBAC (Reader at the
relevant subscription scope).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.services.aks.utils import stored_credentials_to_azure_creds

logger = logging.getLogger(__name__)

# Hard cap so a broad query can't return an unbounded payload into the LLM context.
_MAX_ROWS = 200


def _get_credential(credentials: dict[str, Any] | None) -> Any:
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    sp = stored_credentials_to_azure_creds(credentials)
    if sp:
        return ClientSecretCredential(**sp)
    return DefaultAzureCredential()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def query_resource_graph(
    query: str,
    subscriptions: list[str],
    credentials: dict[str, Any] | None = None,
    max_rows: int = _MAX_ROWS,
) -> dict[str, Any]:
    """Run a KQL query against Azure Resource Graph across the given subscriptions.

    Returns at most ``max_rows`` rows; ``truncated`` flags when more matched than
    were returned so the caller knows to narrow the query.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import (
        QueryRequest,
        QueryRequestOptions,
    )

    credential = _get_credential(credentials)
    client = ResourceGraphClient(credential)

    request = QueryRequest(
        subscriptions=subscriptions,
        query=query,
        options=QueryRequestOptions(top=max_rows),
    )
    response = client.resources(request)

    rows: list[dict[str, Any]] = []
    data: Any = response.data or []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append({str(k): _jsonable(v) for k, v in item.items()})

    total = response.total_records if response.total_records is not None else len(rows)
    return {
        "query": query,
        "subscriptions": subscriptions,
        "total_records": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "results": rows,
    }
