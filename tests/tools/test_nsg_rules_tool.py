"""Unit tests for the Azure NSG rules tool (get_nsg_rules).

Exercise availability gating, param extraction, and the tool function via an
injected ``nsg_backend`` so no live Azure access or azure-mgmt-network SDK is
required.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tools.NetworkSecurityGroupRulesTool import (
    _azure_subscription_available,
    _azure_subscription_extract_params,
    get_nsg_rules_tool,
)


class _MockNsgBackend:
    def list_nsgs(self, resource_group: str = "") -> dict[str, Any]:
        return {
            "source": "azure",
            "available": True,
            "resource_group": resource_group,
            "total": 1,
            "network_security_groups": [{"name": "d-nsg-opensre-poc", "custom_rule_count": 2}],
        }

    def get_nsg_rules(self, resource_group: str = "", nsg_name: str = "") -> dict[str, Any]:
        return {
            "source": "azure",
            "available": True,
            "nsg": {
                "name": nsg_name,
                "resource_group": resource_group,
                "security_rules": [
                    {"name": "deny-5805", "priority": 200, "access": "Deny", "direction": "Inbound"}
                ],
                "default_security_rules": [
                    {"name": "DenyAllInBound", "priority": 65500, "access": "Deny"}
                ],
            },
        }


class TestAvailability:
    def test_available_when_subscription_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        assert _azure_subscription_available({}) is True

    def test_unavailable_without_subscription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_SUBSCRIPTION_ID", raising=False)
        assert _azure_subscription_available({}) is False

    def test_extract_params_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-9")
        assert _azure_subscription_extract_params({})["subscription_id"] == "sub-9"


class TestGetNsgRulesTool:
    def test_lists_nsgs_when_no_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        result = get_nsg_rules_tool(resource_group="d-rg", nsg_backend=_MockNsgBackend())
        assert result["available"] is True
        assert result["total"] == 1
        assert result["network_security_groups"][0]["name"] == "d-nsg-opensre-poc"

    def test_returns_rules_for_named_nsg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        result = get_nsg_rules_tool(
            nsg_name="d-nsg-opensre-poc", resource_group="d-rg", nsg_backend=_MockNsgBackend()
        )
        assert result["available"] is True
        assert result["nsg"]["security_rules"][0]["access"] == "Deny"
        assert result["nsg"]["default_security_rules"][0]["name"] == "DenyAllInBound"

    def test_unavailable_without_subscription_or_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_SUBSCRIPTION_ID", raising=False)
        result = get_nsg_rules_tool(nsg_name="x", resource_group="rg", subscription_id="")
        assert result["available"] is False
        assert "error" in result

    def test_hint_when_name_without_resource_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
        result = get_nsg_rules_tool(nsg_name="x", resource_group="")
        assert result["available"] is True
        assert result["rules"] is None
        assert "note" in result
