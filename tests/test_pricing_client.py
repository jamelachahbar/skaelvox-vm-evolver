"""Tests for PricingClient in azure_client.py."""
import pytest
from unittest.mock import MagicMock, patch
import httpx

from azure_client import PricingClient, retry_on_transient


class TestPricingClientCache:
    """Tests for PricingClient caching behavior."""

    def test_cache_prevents_duplicate_requests(self):
        client = PricingClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Items": [{
                "skuName": "Standard_D4s_v5",
                "retailPrice": 0.192,
            }],
            "NextPageLink": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            # First call - should hit the API
            price1 = client.get_price("Standard_D4s_v5", "eastus", "Linux")
            assert price1 == 0.192
            assert mock_get.call_count == 1

            # Second call - should use cache
            price2 = client.get_price("Standard_D4s_v5", "eastus", "Linux")
            assert price2 == 0.192
            assert mock_get.call_count == 1  # No additional call

        client.close()

    def test_different_regions_not_cached(self):
        client = PricingClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Items": [{
                "skuName": "Standard_D4s_v5",
                "retailPrice": 0.192,
            }],
            "NextPageLink": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            client.get_price("Standard_D4s_v5", "eastus", "Linux")
            client.get_price("Standard_D4s_v5", "westeurope", "Linux")
            assert mock_get.call_count == 2  # Separate calls for each region

        client.close()

    def test_skips_spot_prices(self):
        client = PricingClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Items": [
                {"skuName": "Standard_D4s_v5 Spot", "retailPrice": 0.05},
                {"skuName": "Standard_D4s_v5 Low Priority", "retailPrice": 0.04},
                {"skuName": "Standard_D4s_v5", "retailPrice": 0.192},
            ],
            "NextPageLink": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response):
            price = client.get_price("Standard_D4s_v5", "eastus", "Linux")
            assert price == 0.192  # Should get regular price, not Spot

        client.close()

    def test_pagination_follows_next_page_link(self):
        client = PricingClient()

        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "Items": [
                {"skuName": "Standard_D4s_v5 Spot", "retailPrice": 0.05},
            ],
            "NextPageLink": "https://prices.azure.com/api/retail/prices?page=2",
        }
        page1_response.raise_for_status = MagicMock()

        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "Items": [
                {"skuName": "Standard_D4s_v5", "retailPrice": 0.192},
            ],
            "NextPageLink": None,
        }
        page2_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", side_effect=[page1_response, page2_response]) as mock_get:
            price = client.get_price("Standard_D4s_v5", "eastus", "Linux")
            assert price == 0.192
            assert mock_get.call_count == 2  # Two pages fetched

        client.close()


class TestRetryDecorator:
    """Tests for retry_on_transient decorator."""

    def test_succeeds_on_first_try(self):
        call_count = 0

        @retry_on_transient(max_retries=3, base_delay=0.01)
        def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert always_succeeds() == "ok"
        assert call_count == 1

    def test_retries_on_timeout(self):
        call_count = 0

        @retry_on_transient(max_retries=2, base_delay=0.01)
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TimeoutException("timeout")
            return "ok"

        assert fails_then_succeeds() == "ok"
        assert call_count == 3  # 1 initial + 2 retries

    def test_raises_after_max_retries(self):
        @retry_on_transient(max_retries=2, base_delay=0.01)
        def always_fails():
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            always_fails()

    def test_no_retry_on_4xx(self):
        call_count = 0
        mock_response = MagicMock()
        mock_response.status_code = 404

        @retry_on_transient(max_retries=3, base_delay=0.01)
        def not_found():
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            not_found()
        assert call_count == 1  # No retries for 404
