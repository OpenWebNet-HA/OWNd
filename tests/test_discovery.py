"""Tests for direct and multicast gateway discovery."""

from unittest.mock import AsyncMock, patch

import pytest

from OWNd.discovery import get_gateway


@pytest.mark.asyncio
async def test_get_gateway_prefers_direct_descriptor_lookup() -> None:
    details = {
        "modelName": "F454",
        "serialNumber": "00:03:50:00:12:34",
        "port": 20000,
    }

    with (
        patch("OWNd.discovery._get_scpd_details", new=AsyncMock(return_value=details)),
        patch("OWNd.discovery.find_gateways", new=AsyncMock()) as find_gateways,
    ):
        gateway = await get_gateway("192.168.1.12")

    assert gateway is not None
    assert gateway["address"] == "192.168.1.12"
    assert gateway["ssdp_location"] == (
        "http://192.168.1.12:49153/description.xml"
    )
    assert gateway["ssdp_st"] is None
    find_gateways.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_gateway_falls_back_to_ssdp() -> None:
    discovered = [
        {"address": "192.168.1.10", "modelName": "F454"},
        {"address": "192.168.1.12", "modelName": "MH201"},
    ]

    with (
        patch(
            "OWNd.discovery._get_scpd_details",
            new=AsyncMock(side_effect=OSError("descriptor unavailable")),
        ),
        patch(
            "OWNd.discovery.find_gateways", new=AsyncMock(return_value=discovered)
        ) as find_gateways,
    ):
        gateway = await get_gateway("192.168.1.12")

    assert gateway == discovered[1]
    find_gateways.assert_awaited_once_with(session=None)


@pytest.mark.asyncio
async def test_get_gateway_returns_none_when_not_found() -> None:
    with (
        patch(
            "OWNd.discovery._get_scpd_details",
            new=AsyncMock(side_effect=TimeoutError),
        ),
        patch("OWNd.discovery.find_gateways", new=AsyncMock(return_value=[])),
    ):
        assert await get_gateway("192.0.2.1") is None
