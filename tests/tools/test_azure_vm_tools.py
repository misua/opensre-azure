"""Unit tests for the Azure VM tools (list_azure_vms, get_azure_vm_status).

These exercise availability gating, param extraction, and the tool functions via an
injected ``_backend`` so no live Azure access or azure-mgmt-compute SDK is required.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tools.AzureVMInstanceViewTool import get_azure_vm_status_tool
from app.tools.AzureVMListTool import list_azure_vms_tool
from app.tools.utils.availability import azure_vm_available_or_backend
from app.tools.utils.azure_vm_helper import extract_azure_vm_params


class _MockAzureVMBackend:
    """Matches the backend surface the tools call: list_vms() / instance_view()."""

    def list_vms(self, resource_group: str = "") -> dict[str, Any]:
        return {
            "source": "azure_vm",
            "available": True,
            "resource_group": resource_group,
            "total": 2,
            "vms": [
                {"name": "d-vm-linux-opensre-poc", "power_state": "running", "os_type": "Linux"},
                {
                    "name": "d-vm-win-opensre-poc",
                    "power_state": "deallocated",
                    "os_type": "Windows",
                },
            ],
        }

    def instance_view(self, resource_group: str = "", vm_name: str = "") -> dict[str, Any]:
        return {
            "source": "azure_vm",
            "available": True,
            "instance_view": {
                "name": vm_name,
                "resource_group": resource_group,
                "power_state": "running",
            },
        }


@pytest.fixture
def vm_sources() -> dict[str, dict]:
    return {
        "azure_vm": {
            "connection_verified": False,
            "_backend": _MockAzureVMBackend(),
            "subscription_id": "test-sub",
            "resource_group": "test-rg",
            "credentials": None,
        }
    }


class TestAvailability:
    def test_available_when_connection_verified(self) -> None:
        assert azure_vm_available_or_backend({"azure_vm": {"connection_verified": True}}) is True

    def test_available_when_backend_injected(self) -> None:
        assert azure_vm_available_or_backend({"azure_vm": {"_backend": object()}}) is True

    def test_unavailable_when_neither(self) -> None:
        assert azure_vm_available_or_backend({"azure_vm": {}}) is False

    def test_unavailable_when_source_missing(self) -> None:
        assert azure_vm_available_or_backend({}) is False


class TestParamExtraction:
    def test_extracts_all_fields(self, vm_sources: dict[str, dict]) -> None:
        params = extract_azure_vm_params(vm_sources)
        assert params["subscription_id"] == "test-sub"
        assert params["resource_group"] == "test-rg"
        assert params["credentials"] is None
        assert isinstance(params["azure_vm_backend"], _MockAzureVMBackend)

    def test_raises_when_source_missing(self) -> None:
        with pytest.raises(ValueError, match="azure_vm"):
            extract_azure_vm_params({})


class TestListAzureVmsTool:
    def test_lists_via_backend(self, vm_sources: dict[str, dict]) -> None:
        result = list_azure_vms_tool(**extract_azure_vm_params(vm_sources))
        assert result["available"] is True
        assert result["total"] == 2
        assert result["vms"][0]["name"] == "d-vm-linux-opensre-poc"

    def test_graceful_error_without_backend_or_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("AZURE_VM_RESOURCE_GROUP", raising=False)
        result = list_azure_vms_tool(subscription_id="", resource_group="", credentials=None)
        assert result["source"] == "azure_vm"
        assert result["available"] is False
        assert "error" in result


class TestGetAzureVmStatusTool:
    def test_status_via_backend(self, vm_sources: dict[str, dict]) -> None:
        params = extract_azure_vm_params(vm_sources)
        result = get_azure_vm_status_tool(vm_name="d-vm-linux-opensre-poc", **params)
        assert result["available"] is True
        assert result["instance_view"]["name"] == "d-vm-linux-opensre-poc"

    def test_missing_vm_name_returns_hint_not_error(self, vm_sources: dict[str, dict]) -> None:
        # Pre-seeding calls this tool with no vm_name — it must not raise or hit the backend.
        params = extract_azure_vm_params(vm_sources)
        result = get_azure_vm_status_tool(vm_name="", **params)
        assert result["available"] is True
        assert result["instance_view"] is None
        assert "note" in result
