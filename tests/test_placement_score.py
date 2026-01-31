"""
Tests for Azure Spot Placement Score integration.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from azure_client import SpotPlacementScoreClient, PlacementScore


class TestSpotPlacementScoreClient:
    """Test Spot Placement Score API client."""
    
    def test_placement_score_creation(self):
        """Test PlacementScore dataclass creation."""
        score = PlacementScore(
            sku="Standard_D4s_v5",
            location="eastus",
            zone="1",
            score="High",
            is_zonal=True,
        )
        
        assert score.sku == "Standard_D4s_v5"
        assert score.location == "eastus"
        assert score.zone == "1"
        assert score.score == "High"
        assert score.is_zonal is True
    
    def test_placement_score_defaults(self):
        """Test PlacementScore with default values."""
        score = PlacementScore(
            sku="Standard_D4s_v5",
            location="eastus",
        )
        
        assert score.zone is None
        assert score.score == "Unknown"
        assert score.is_zonal is False
    
    @patch('azure_client.httpx.Client')
    @patch('azure_client.DefaultAzureCredential')
    def test_get_placement_scores_success(self, mock_cred, mock_http):
        """Test successful placement score API call."""
        # Mock credential
        mock_token = Mock()
        mock_token.token = "fake_token"
        mock_credential_instance = Mock()
        mock_credential_instance.get_token.return_value = mock_token
        mock_cred.return_value = mock_credential_instance
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "placementScores": [
                {
                    "sku": "Standard_D4s_v5",
                    "location": "eastus",
                    "isZonal": True,
                    "zoneScores": [
                        {"zone": "1", "score": "High"},
                        {"zone": "2", "score": "Medium"},
                        {"zone": "3", "score": "Low"},
                    ]
                }
            ]
        }
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_http.return_value = mock_client_instance
        
        # Create client and call API
        client = SpotPlacementScoreClient(
            subscription_id="test-sub-id",
            credential=mock_credential_instance,
        )
        
        results = client.get_placement_scores(
            location="eastus",
            sku_names=["Standard_D4s_v5"],
            desired_count=1,
            availability_zones=True,
        )
        
        # Verify results
        assert len(results) == 3
        assert results[0].sku == "Standard_D4s_v5"
        assert results[0].zone == "1"
        assert results[0].score == "High"
        assert results[0].is_zonal is True
        
        assert results[1].zone == "2"
        assert results[1].score == "Medium"
        
        assert results[2].zone == "3"
        assert results[2].score == "Low"
    
    @patch('azure_client.httpx.Client')
    @patch('azure_client.DefaultAzureCredential')
    def test_get_placement_scores_regional(self, mock_cred, mock_http):
        """Test placement score for regional (non-zonal) deployment."""
        # Mock credential
        mock_token = Mock()
        mock_token.token = "fake_token"
        mock_credential_instance = Mock()
        mock_credential_instance.get_token.return_value = mock_token
        mock_cred.return_value = mock_credential_instance
        
        # Mock HTTP response for regional score
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "placementScores": [
                {
                    "sku": "Standard_D4s_v5",
                    "location": "eastus",
                    "isZonal": False,
                    "score": "High",
                }
            ]
        }
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_http.return_value = mock_client_instance
        
        # Create client and call API
        client = SpotPlacementScoreClient(
            subscription_id="test-sub-id",
            credential=mock_credential_instance,
        )
        
        results = client.get_placement_scores(
            location="eastus",
            sku_names=["Standard_D4s_v5"],
            desired_count=1,
            availability_zones=False,
        )
        
        # Verify results
        assert len(results) == 1
        assert results[0].sku == "Standard_D4s_v5"
        assert results[0].location == "eastus"
        assert results[0].zone is None
        assert results[0].score == "High"
        assert results[0].is_zonal is False
    
    @patch('azure_client.httpx.Client')
    @patch('azure_client.DefaultAzureCredential')
    def test_get_placement_scores_http_error(self, mock_cred, mock_http):
        """Test handling of HTTP error during API call."""
        # Mock credential
        mock_token = Mock()
        mock_token.token = "fake_token"
        mock_credential_instance = Mock()
        mock_credential_instance.get_token.return_value = mock_token
        mock_cred.return_value = mock_credential_instance
        
        # Mock HTTP error
        mock_response = Mock()
        mock_response.status_code = 404
        from httpx import HTTPStatusError, Request, Response
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = HTTPStatusError(
            "Not found",
            request=Mock(spec=Request),
            response=mock_response,
        )
        mock_http.return_value = mock_client_instance
        
        # Create client and call API
        client = SpotPlacementScoreClient(
            subscription_id="test-sub-id",
            credential=mock_credential_instance,
        )
        
        results = client.get_placement_scores(
            location="eastus",
            sku_names=["Standard_D4s_v5"],
            desired_count=1,
            availability_zones=True,
        )
        
        # Should return Unknown scores on error
        assert len(results) == 1
        assert results[0].sku == "Standard_D4s_v5"
        assert results[0].score == "Unknown"
    
    @patch('azure_client.httpx.Client')
    @patch('azure_client.DefaultAzureCredential')
    def test_get_placement_scores_multiple_skus(self, mock_cred, mock_http):
        """Test placement scores for multiple SKUs."""
        # Mock credential
        mock_token = Mock()
        mock_token.token = "fake_token"
        mock_credential_instance = Mock()
        mock_credential_instance.get_token.return_value = mock_token
        mock_cred.return_value = mock_credential_instance
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "placementScores": [
                {
                    "sku": "Standard_D4s_v5",
                    "location": "eastus",
                    "isZonal": False,
                    "score": "High",
                },
                {
                    "sku": "Standard_D8s_v5",
                    "location": "eastus",
                    "isZonal": False,
                    "score": "Medium",
                }
            ]
        }
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_http.return_value = mock_client_instance
        
        # Create client and call API
        client = SpotPlacementScoreClient(
            subscription_id="test-sub-id",
            credential=mock_credential_instance,
        )
        
        results = client.get_placement_scores(
            location="eastus",
            sku_names=["Standard_D4s_v5", "Standard_D8s_v5"],
            desired_count=1,
            availability_zones=False,
        )
        
        # Verify results
        assert len(results) == 2
        assert results[0].sku == "Standard_D4s_v5"
        assert results[0].score == "High"
        assert results[1].sku == "Standard_D8s_v5"
        assert results[1].score == "Medium"
