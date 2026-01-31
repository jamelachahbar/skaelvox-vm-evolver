"""Tests for analysis_engine.py - SKU parsing and scoring logic."""
import pytest
from unittest.mock import MagicMock

from analysis_engine import AnalysisEngine
from azure_client import AzureClient, PricingClient, SKUInfo, VMInfo


@pytest.fixture
def engine():
    """Create an AnalysisEngine with mocked dependencies."""
    azure_client = MagicMock(spec=AzureClient)
    pricing_client = MagicMock(spec=PricingClient)
    return AnalysisEngine(
        azure_client=azure_client,
        pricing_client=pricing_client,
        ai_analyzer=None,
        validate_constraints=False,
        max_workers=1,
    )


class TestExtractGeneration:
    """Tests for _extract_generation() SKU name parsing."""

    def test_standard_v5_suffix(self, engine):
        assert engine._extract_generation("Standard_D4s_v5") == "v5"

    def test_standard_v4_suffix(self, engine):
        assert engine._extract_generation("Standard_E8ds_v4") == "v4"

    def test_standard_v3_suffix(self, engine):
        assert engine._extract_generation("Standard_D2s_v3") == "v3"

    def test_gpu_sku_with_accelerator(self, engine):
        assert engine._extract_generation("Standard_NC4as_T4_v3") == "v3"

    def test_m_series_with_memory_notation(self, engine):
        assert engine._extract_generation("Standard_M48ds_1_v3") == "v3"

    def test_inline_version_bsv2(self, engine):
        assert engine._extract_generation("Standard_Bsv2") == "v2"

    def test_inline_version_dpsv5(self, engine):
        assert engine._extract_generation("Standard_Dpsv5") == "v5"

    def test_no_version_b_series(self, engine):
        assert engine._extract_generation("Standard_B2s") == "v1"

    def test_no_version_d_series(self, engine):
        assert engine._extract_generation("Standard_D3") == "v1"

    def test_no_version_a_series(self, engine):
        assert engine._extract_generation("Standard_A1") == "v1"

    def test_no_version_f_series(self, engine):
        assert engine._extract_generation("Standard_F2s") == "v1"

    def test_unknown_sku(self, engine):
        assert engine._extract_generation("SomethingUnknown") == "v1"


class TestExtractFamily:
    """Tests for _extract_family() VM family extraction."""

    def test_d_family(self, engine):
        assert engine._extract_family("Standard_D8s_v5") == "D"

    def test_e_family(self, engine):
        assert engine._extract_family("Standard_E16ds_v4") == "E"

    def test_f_family(self, engine):
        assert engine._extract_family("Standard_F4s_v2") == "F"

    def test_b_family(self, engine):
        assert engine._extract_family("Standard_B2s") == "B"

    def test_m_family(self, engine):
        assert engine._extract_family("Standard_M128s") == "M"

    def test_dc_confidential_family(self, engine):
        assert engine._extract_family("Standard_DC4s_v3") == "DC"

    def test_nc_gpu_family(self, engine):
        assert engine._extract_family("Standard_NC4as_T4_v3") == "NC"

    def test_nv_gpu_family(self, engine):
        assert engine._extract_family("Standard_NV16as_v4") == "NV"

    def test_hb_hpc_family(self, engine):
        # HB is a two-letter family in the known families list
        assert engine._extract_family("Standard_HB120rs_v3") == "HB"

    def test_empty_string(self, engine):
        assert engine._extract_family("") == ""

    def test_no_standard_prefix(self, engine):
        assert engine._extract_family("Custom_VM") == ""


class TestGetSkuVersion:
    """Tests for _get_sku_version()."""

    def test_v5(self, engine):
        assert engine._get_sku_version("Standard_D4s_v5") == 5

    def test_v3(self, engine):
        assert engine._get_sku_version("Standard_D2s_v3") == 3

    def test_v1_no_suffix(self, engine):
        assert engine._get_sku_version("Standard_B2s") == 1

    def test_inline_v2(self, engine):
        assert engine._get_sku_version("Standard_Bsv2") == 2


class TestExtractGenerationNumber:
    """Tests for _extract_generation_number()."""

    def test_generation_string(self, engine):
        assert engine._extract_generation_number("v5") == 5

    def test_hyperv_generations(self, engine):
        # "V1,V2" format from HyperVGenerations capability - should take max
        assert engine._extract_generation_number("V1,V2") == 2

    def test_sku_name(self, engine):
        assert engine._extract_generation_number("Standard_D4s_v5") == 5

    def test_unknown_defaults_to_1(self, engine):
        assert engine._extract_generation_number("unknown") == 1


class TestCalculateSkuScore:
    """Tests for _calculate_sku_score()."""

    def test_cheaper_sku_scores_higher(self, engine):
        current_sku = SKUInfo(
            name="Standard_D4s_v3", family="D", vcpus=4, memory_gb=16,
            max_data_disks=8, max_iops=0, max_network_bandwidth_mbps=0,
            generation="V1,V2", features=[], is_restricted=False,
        )
        cheaper_sku = SKUInfo(
            name="Standard_D4s_v5", family="D", vcpus=4, memory_gb=16,
            max_data_disks=8, max_iops=0, max_network_bandwidth_mbps=0,
            generation="V1,V2", features=["PremiumStorage", "AcceleratedNetworking"],
            is_restricted=False,
        )
        expensive_sku = SKUInfo(
            name="Standard_D8s_v5", family="D", vcpus=8, memory_gb=32,
            max_data_disks=16, max_iops=0, max_network_bandwidth_mbps=0,
            generation="V1,V2", features=["PremiumStorage"], is_restricted=False,
        )
        vm = MagicMock(spec=VMInfo)
        vm.vm_size = "Standard_D4s_v3"

        score_cheap = engine._calculate_sku_score(
            sku=cheaper_sku, current_sku=current_sku,
            monthly_price=100, current_price=200, vm=vm,
        )
        score_expensive = engine._calculate_sku_score(
            sku=expensive_sku, current_sku=current_sku,
            monthly_price=400, current_price=200, vm=vm,
        )
        assert score_cheap > score_expensive

    def test_score_is_non_negative(self, engine):
        sku = SKUInfo(
            name="Standard_D4s_v5", family="D", vcpus=4, memory_gb=16,
            max_data_disks=8, max_iops=0, max_network_bandwidth_mbps=0,
            generation="V1,V2", features=[], is_restricted=False,
        )
        vm = MagicMock(spec=VMInfo)
        vm.vm_size = "Standard_D4s_v3"

        score = engine._calculate_sku_score(
            sku=sku, current_sku=sku,
            monthly_price=100, current_price=100, vm=vm,
        )
        assert score >= 0
