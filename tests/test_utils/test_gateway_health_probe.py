"""Tests for gateway /health URL helpers."""

from replicants.utils.gateway_health_probe import health_url_from_base


def test_health_url_from_base_appends_path() -> None:
    assert health_url_from_base("https://being.example.com") == "https://being.example.com/health"


def test_health_url_from_base_preserves_existing_health() -> None:
    assert health_url_from_base("https://being.example.com/health") == "https://being.example.com/health"
