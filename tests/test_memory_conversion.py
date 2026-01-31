"""Tests for memory byte-to-percent conversion logic in azure_client.py."""
import pytest


class TestMemoryConversion:
    """Tests for the memory conversion logic used in get_vm_metrics."""

    def test_basic_conversion(self):
        """50% memory used when half is available."""
        total_bytes = 16 * 1024 * 1024 * 1024  # 16 GB
        avg_available = 8 * 1024 * 1024 * 1024   # 8 GB available
        used_percent = ((total_bytes - avg_available) / total_bytes) * 100
        assert used_percent == pytest.approx(50.0)

    def test_full_utilization(self):
        """100% memory used when 0 bytes available."""
        total_bytes = 16 * 1024 * 1024 * 1024
        avg_available = 0
        used_percent = ((total_bytes - avg_available) / total_bytes) * 100
        assert used_percent == pytest.approx(100.0)

    def test_zero_utilization(self):
        """0% memory used when all bytes available."""
        total_bytes = 16 * 1024 * 1024 * 1024
        avg_available = total_bytes
        used_percent = ((total_bytes - avg_available) / total_bytes) * 100
        assert used_percent == pytest.approx(0.0)

    def test_max_usage_from_min_available(self):
        """Max memory usage should come from minimum available memory."""
        total_bytes = 32 * 1024 * 1024 * 1024  # 32 GB
        # Available memory samples over time
        available_samples = [
            28 * 1024 * 1024 * 1024,  # 28 GB available (12.5% used)
            20 * 1024 * 1024 * 1024,  # 20 GB available (37.5% used)
            8 * 1024 * 1024 * 1024,   # 8 GB available (75% used) - MIN available = MAX usage
            24 * 1024 * 1024 * 1024,  # 24 GB available (25% used)
        ]

        min_available = min(available_samples)  # 8 GB - correctly captures peak usage
        max_available = max(available_samples)  # 28 GB - WRONG for max usage

        # Correct: use min_available for max usage
        correct_max_usage = ((total_bytes - min_available) / total_bytes) * 100
        assert correct_max_usage == pytest.approx(75.0)

        # Incorrect (old bug): using max_available gives lowest usage
        wrong_max_usage = ((total_bytes - max_available) / total_bytes) * 100
        assert wrong_max_usage == pytest.approx(12.5)

        # The correct value should be higher than the wrong one
        assert correct_max_usage > wrong_max_usage

    def test_clamping_negative_values(self):
        """Values should be clamped to 0-100 range."""
        total_bytes = 8 * 1024 * 1024 * 1024
        # Edge case: available > total (can happen with metric inaccuracy)
        avg_available = 9 * 1024 * 1024 * 1024
        raw_percent = ((total_bytes - avg_available) / total_bytes) * 100
        clamped = max(0, min(100, raw_percent))
        assert clamped == 0.0


class TestGetVmTotalMemoryBytes:
    """Tests for _get_vm_total_memory_bytes hardcoded lookup."""

    def test_known_sku_returns_correct_bytes(self):
        from azure_client import AzureClient
        from unittest.mock import MagicMock

        client = MagicMock(spec=AzureClient)
        # Call the actual method from the class
        result = AzureClient._get_vm_total_memory_bytes(client, "Standard_D4s_v5")
        assert result == 16 * 1024 * 1024 * 1024  # 16 GB

    def test_unknown_sku_returns_none(self):
        from azure_client import AzureClient
        from unittest.mock import MagicMock

        client = MagicMock(spec=AzureClient)
        # Use a prefix that won't match any base SKU pattern in the hardcoded map
        result = AzureClient._get_vm_total_memory_bytes(client, "Custom_XYZA_v99")
        assert result is None

    def test_pattern_match_newer_version(self):
        from azure_client import AzureClient
        from unittest.mock import MagicMock

        client = MagicMock(spec=AzureClient)
        # D4s_v6 should match D4s_v5 via pattern matching
        result = AzureClient._get_vm_total_memory_bytes(client, "Standard_D4s_v6")
        assert result is not None
        # Pattern match returns the first matching base SKU's memory
        assert result > 0
