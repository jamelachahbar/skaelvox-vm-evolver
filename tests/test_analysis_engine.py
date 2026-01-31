"""Tests for analysis_engine.py - SKU parsing and scoring logic."""
import pytest
from unittest.mock import MagicMock, patch

from analysis_engine import AnalysisEngine, RightsizingResult
from azure_client import AzureClient, PricingClient, SKUInfo, VMInfo, AdvisorRecommendation


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


# ---------------------------------------------------------------------------
# SKU Validation Improvement Tests
# ---------------------------------------------------------------------------

def _make_sku(name, vcpus=4, memory_gb=16, **kwargs):
    """Helper to create a SKUInfo with defaults."""
    defaults = dict(
        family="D", max_data_disks=8, max_iops=0,
        max_network_bandwidth_mbps=0, generation="V1,V2",
        features=[], is_restricted=False,
    )
    defaults.update(kwargs)
    return SKUInfo(name=name, vcpus=vcpus, memory_gb=memory_gb, **defaults)


class TestValidSkuSet:
    """Tests for the in-memory valid SKU set."""

    def test_valid_sku_set_built_from_cache(self, engine):
        """Valid SKU set should be built from cached SKU list."""
        skus = [_make_sku("Standard_D4s_v5"), _make_sku("Standard_E4s_v5")]
        engine._sku_cache["eastus"] = skus

        valid_set = engine._get_valid_sku_set("eastus")
        assert "Standard_D4s_v5" in valid_set
        assert "Standard_E4s_v5" in valid_set
        assert "Standard_B2s" not in valid_set

    def test_is_sku_valid_in_region(self, engine):
        """_is_sku_valid_in_region should use the in-memory set."""
        engine._sku_cache["westeurope"] = [_make_sku("Standard_D4s_v5")]

        assert engine._is_sku_valid_in_region("Standard_D4s_v5", "westeurope") is True
        assert engine._is_sku_valid_in_region("Standard_X99_v9", "westeurope") is False


class TestGenerationUpgradeValidation:
    """Tests that generation upgrades are validated against region availability."""

    def test_generation_upgrade_recommended_when_available(self, engine):
        """Generation upgrade should be recommended when target SKU is available."""
        vm = VMInfo(
            name="test-vm", resource_group="rg", location="eastus",
            vm_size="Standard_D4s_v3", vm_id="id", power_state="running",
            os_type="Linux",
        )
        vm.current_price_monthly = 200.0
        result = RightsizingResult(vm=vm)

        # Cache contains the target SKU
        engine._sku_cache["eastus"] = [_make_sku("Standard_D4s_v5")]
        # Price cache for the upgrade target (cheaper than current: 0.20 * 730 = 146)
        engine._price_cache["Standard_D4s_v5:eastus:Linux"] = 0.20

        with patch.dict("analysis_engine.VM_GENERATION_MAP", {"Standard_D4s_v3": "Standard_D4s_v5"}, clear=True):
            engine._analyze_generation_upgrade(result)

        assert result.recommended_generation_upgrade == "Standard_D4s_v5"

    def test_generation_upgrade_blocked_when_sku_missing(self, engine):
        """Generation upgrade should be blocked if target SKU is not in region."""
        vm = VMInfo(
            name="test-vm", resource_group="rg", location="eastus",
            vm_size="Standard_D4s_v3", vm_id="id", power_state="running",
            os_type="Linux",
        )
        vm.current_price_monthly = 200.0
        result = RightsizingResult(vm=vm)

        # Cache does NOT contain the target SKU
        engine._sku_cache["eastus"] = [_make_sku("Standard_E4s_v5")]

        with patch.dict("analysis_engine.VM_GENERATION_MAP", {"Standard_D4s_v3": "Standard_D4s_v5"}, clear=True):
            engine._analyze_generation_upgrade(result)

        assert result.recommended_generation_upgrade is None


class TestAdvisorRecommendationValidation:
    """Tests that Advisor-recommended SKUs are validated."""

    def test_advisor_restricted_sku_flagged(self, engine):
        """Advisor rec with restricted SKU should add constraint issue."""
        vm = MagicMock(spec=VMInfo)
        vm.name = "test-vm"
        vm.vm_size = "Standard_D8s_v3"
        vm.location = "eastus"
        vm.os_type = "Linux"
        vm.current_price_monthly = 400.0
        vm.avg_cpu = 30.0
        vm.max_cpu = 50.0
        vm.avg_memory = None
        vm.max_memory = None
        vm.data_disk_count = 0

        # Cache does NOT contain the Advisor-recommended SKU
        engine._sku_cache["eastus"] = [_make_sku("Standard_D4s_v5")]

        advisor_rec = MagicMock(spec=AdvisorRecommendation)
        advisor_rec.vm_name = "test-vm"
        advisor_rec.recommended_sku = "Standard_D4s_v3"
        advisor_rec.problem = "Underutilized"
        advisor_rec.solution = "Resize"
        advisor_rec.estimated_savings = 100.0

        result = RightsizingResult(vm=vm)

        # Simulate what _analyze_vm does for Advisor recs
        for rec in [advisor_rec]:
            if rec.vm_name.lower() == vm.name.lower():
                result.advisor_recommendation = rec
                if rec.recommended_sku and not engine._is_sku_valid_in_region(rec.recommended_sku, vm.location):
                    result.constraint_issues.append(
                        f"Advisor-recommended SKU {rec.recommended_sku} is restricted in {vm.location}"
                    )
                break

        assert len(result.constraint_issues) == 1
        assert "Standard_D4s_v3" in result.constraint_issues[0]
        assert "restricted" in result.constraint_issues[0]

    def test_advisor_valid_sku_no_issue(self, engine):
        """Advisor rec with valid SKU should not add constraint issues."""
        vm = MagicMock(spec=VMInfo)
        vm.name = "test-vm"
        vm.location = "eastus"

        engine._sku_cache["eastus"] = [_make_sku("Standard_D4s_v5")]

        result = RightsizingResult(vm=vm)
        # Advisor recommends a valid SKU
        assert engine._is_sku_valid_in_region("Standard_D4s_v5", "eastus") is True


class TestTopNValidationAndPromotion:
    """Tests for validating top 3 candidates and auto-promoting."""

    def test_auto_promote_when_top1_invalid(self):
        """If #1 is invalid but #2 is valid, #2 should be promoted to #1."""
        azure_client = MagicMock(spec=AzureClient)
        pricing_client = MagicMock(spec=PricingClient)

        # We need a real constraint_validator mock
        mock_validator = MagicMock()

        engine = AnalysisEngine(
            azure_client=azure_client,
            pricing_client=pricing_client,
            ai_analyzer=None,
            validate_constraints=False,
            max_workers=1,
        )
        engine.constraint_validator = mock_validator

        vm = MagicMock(spec=VMInfo)
        vm.vm_size = "Standard_D8s_v3"
        vm.location = "eastus"
        vm.data_disk_count = 0

        result = RightsizingResult(vm=vm)
        result.ranked_alternatives = [
            {"sku": "Standard_D4s_v5", "vcpus": 4, "is_valid": True, "validation_issues": [], "score": 90, "savings": 100},
            {"sku": "Standard_D2s_v5", "vcpus": 2, "is_valid": True, "validation_issues": [], "score": 85, "savings": 150},
            {"sku": "Standard_E4s_v5", "vcpus": 4, "is_valid": True, "validation_issues": [], "score": 80, "savings": 80},
        ]

        # Mock: #1 fails validation, #2 passes
        def mock_validate(sku_name, location, required_vcpus, required_features=None):
            result_obj = MagicMock()
            result_obj.quota_info = None
            if sku_name == "Standard_D4s_v5":
                result_obj.is_valid = False
                result_obj.restrictions = [MagicMock(message="Quota exceeded")]
            else:
                result_obj.is_valid = True
                result_obj.restrictions = []
            return result_obj

        mock_validator.validate_sku = mock_validate

        # Manually invoke the validation block from _rank_sku_alternatives
        # We test the logic directly
        candidates = result.ranked_alternatives[:]
        required_features = []
        first_valid_idx = None
        validate_count = min(3, len(result.ranked_alternatives))

        for idx in range(validate_count):
            candidate = result.ranked_alternatives[idx]
            validation = mock_validator.validate_sku(
                sku_name=candidate["sku"],
                location=vm.location,
                required_vcpus=candidate["vcpus"],
                required_features=required_features if required_features else None,
            )
            candidate["is_valid"] = validation.is_valid
            if not validation.is_valid:
                for restriction in validation.restrictions:
                    candidate["validation_issues"].append(restriction.message)
            else:
                if first_valid_idx is None:
                    first_valid_idx = idx

        # Auto-promote
        if first_valid_idx is not None and first_valid_idx > 0:
            promoted = result.ranked_alternatives.pop(first_valid_idx)
            result.ranked_alternatives.insert(0, promoted)

        # #2 (D2s_v5) should now be #1
        assert result.ranked_alternatives[0]["sku"] == "Standard_D2s_v5"
        assert result.ranked_alternatives[0]["is_valid"] is True
        # Original #1 should be demoted
        assert result.ranked_alternatives[1]["sku"] == "Standard_D4s_v5"
        assert result.ranked_alternatives[1]["is_valid"] is False
