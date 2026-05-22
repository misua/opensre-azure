from __future__ import annotations
from typing import Any


def stored_credentials_to_azure_creds(
    credentials: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize stored Azure SP credentials for use with ClientSecretCredential."""
    if not credentials:
        return None
    tenant_id = credentials.get("tenant_id")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not (tenant_id and client_id and client_secret):
        return None
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
    }
