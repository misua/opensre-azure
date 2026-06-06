"""Unit tests for the Azure Resource Graph tool (query_azure_resource_graph).

Exercise availability gating, subscription resolution, and the tool function via
an injected ``resource_graph_backend`` so no live Azure access or
azure-mgmt-resourcegraph SDK is required.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tools.ResourceGraphQueryTool import (
    _configured_subscriptions,
    _resource_graph_available,
    _resource_graph_extract_params,
    query_azure_resource_graph_tool,
)


class _MockResourceGraphBackend:
    def query(self, query: str = "") -> dict[str, Any]:
        return {
            "source": "azure",
            "available": True,
            "query": query,
            "total_records": 1,
            "returned": 1,
            "truncated": False,
            "results": [{"name": "orphan-nic-1", "resourceGroup": "d-rg"}],
        }


class TestAvailability:
    def test_available_when_subscription_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        assert _resource_graph_available({}) is True

    def test_unavailable_without_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_SUBSCRIPTION_ID", raising=False)
        assert _resource_graph_available({}) is False

    def test_extract_params_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-7")
        assert _resource_graph_extract_params({})["subscription_id"] == "sub-7"


class TestConfiguredSubscriptions:
    def test_defaults_to_single_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_RESOURCE_GRAPH_SUBSCRIPTIONS", raising=False)
        assert _configured_subscriptions("sub-1") == ["sub-1"]

    def test_parses_csv_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_RESOURCE_GRAPH_SUBSCRIPTIONS", "a, b ,c")
        assert _configured_subscriptions("ignored") == ["a", "b", "c"]

    def test_empty_when_no_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_RESOURCE_GRAPH_SUBSCRIPTIONS", raising=False)
        assert _configured_subscriptions("") == []


class TestQueryTool:
    def test_queries_via_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        result = query_azure_resource_graph_tool(
            query="Resources | project name",
            resource_graph_backend=_MockResourceGraphBackend(),
        )
        assert result["available"] is True
        assert result["returned"] == 1
        assert result["results"][0]["name"] == "orphan-nic-1"

    def test_hint_when_no_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        result = query_azure_resource_graph_tool(query="")
        assert result["available"] is True
        assert result["results"] is None
        assert "note" in result

    def test_unavailable_without_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_SUBSCRIPTION_ID", raising=False)
        result = query_azure_resource_graph_tool(query="Resources", subscription_id="")
        assert result["available"] is False
        assert "error" in result
