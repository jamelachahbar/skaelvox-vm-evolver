"""
SKU Constraints and Capacity Validation Module.

Checks for:
- SKU restrictions (region, zone, subscription)
- Quota availability
- Capacity constraints
- Zone availability
- Feature requirements
"""
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


class RestrictionType(Enum):
    """Types of SKU restrictions."""
    LOCATION = "Location"
    ZONE = "Zone"
    SUBSCRIPTION = "Subscription"
    QUOTA = "Quota"
    CAPACITY = "Capacity"
    FEATURE = "Feature"


class RestrictionReason(Enum):
    """Reasons for SKU restrictions."""
    QUOTA_EXCEEDED = "QuotaExceeded"
    NOT_AVAILABLE_FOR_SUBSCRIPTION = "NotAvailableForSubscription"
    ZONE_NOT_SUPPORTED = "ZoneNotSupported"
    CAPACITY_NOT_AVAILABLE = "CapacityNotAvailable"
    FEATURE_NOT_SUPPORTED = "FeatureNotSupported"
    RETIRED = "Retired"


@dataclass
class SKURestriction:
    """Represents a restriction on a SKU."""
    sku_name: str
    restriction_type: RestrictionType
    reason: RestrictionReason
    locations: List[str] = field(default_factory=list)
    zones: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class QuotaInfo:
    """Quota information for a VM family."""
    family: str
    location: str
    current_usage: int
    limit: int
    unit: str = "vCPUs"
    
    @property
    def available(self) -> int:
        return max(0, self.limit - self.current_usage)
    
    @property
    def usage_percent(self) -> float:
        return (self.current_usage / self.limit * 100) if self.limit > 0 else 0


@dataclass
class CapacityInfo:
    """Capacity availability information."""
    sku_name: str
    location: str
    zones: List[str] = field(default_factory=list)
    available: bool = True
    capacity_reservation_supported: bool = False
    spot_available: bool = False
    on_demand_available: bool = True
    message: str = ""


@dataclass
class SKUValidationResult:
    """Complete validation result for a SKU."""
    sku_name: str
    location: str
    is_valid: bool = True
    restrictions: List[SKURestriction] = field(default_factory=list)
    quota_info: Optional[QuotaInfo] = None
    capacity_info: Optional[CapacityInfo] = None
    warnings: List[str] = field(default_factory=list)
    
    def add_restriction(self, restriction: SKURestriction):
        self.restrictions.append(restriction)
        self.is_valid = False
    
    def add_warning(self, warning: str):
        self.warnings.append(warning)


class ConstraintValidator:
    """Validates SKU constraints and capacity."""
    
    def __init__(self, azure_client):
        """
        Initialize with an AzureClient instance.
        
        Args:
            azure_client: AzureClient instance for API calls
        """
        self.azure_client = azure_client
        self._sku_cache: Dict[str, Dict] = {}
        self._quota_cache: Dict[str, List[QuotaInfo]] = {}
        self._restriction_cache: Dict[str, List[SKURestriction]] = {}
    
    def validate_sku(
        self,
        sku_name: str,
        location: str,
        required_vcpus: int = 0,
        required_zones: Optional[List[str]] = None,
        required_features: Optional[List[str]] = None,
    ) -> SKUValidationResult:
        """
        Validate if a SKU can be deployed in a location.
        
        Args:
            sku_name: The VM SKU to validate
            location: Azure region
            required_vcpus: Number of vCPUs needed (for quota check)
            required_zones: Specific zones required
            required_features: Required features (PremiumStorage, AcceleratedNetworking, etc.)
        
        Returns:
            SKUValidationResult with all validation details
        """
        result = SKUValidationResult(sku_name=sku_name, location=location)
        
        # Check SKU restrictions
        restrictions = self._get_sku_restrictions(sku_name, location)
        for restriction in restrictions:
            result.add_restriction(restriction)
        
        # Check quota
        if required_vcpus > 0:
            quota = self._check_quota(sku_name, location, required_vcpus)
            result.quota_info = quota
            if quota and quota.available < required_vcpus:
                result.add_restriction(SKURestriction(
                    sku_name=sku_name,
                    restriction_type=RestrictionType.QUOTA,
                    reason=RestrictionReason.QUOTA_EXCEEDED,
                    locations=[location],
                    message=f"Insufficient quota: need {required_vcpus} vCPUs, only {quota.available} available"
                ))
        
        # Check zone availability
        if required_zones:
            zone_result = self._check_zone_availability(sku_name, location, required_zones)
            if not zone_result[0]:
                result.add_restriction(SKURestriction(
                    sku_name=sku_name,
                    restriction_type=RestrictionType.ZONE,
                    reason=RestrictionReason.ZONE_NOT_SUPPORTED,
                    locations=[location],
                    zones=zone_result[1],
                    message=f"SKU not available in zones: {', '.join(zone_result[1])}"
                ))
        
        # Check feature support
        if required_features:
            missing = self._check_features(sku_name, location, required_features)
            if missing:
                result.add_restriction(SKURestriction(
                    sku_name=sku_name,
                    restriction_type=RestrictionType.FEATURE,
                    reason=RestrictionReason.FEATURE_NOT_SUPPORTED,
                    locations=[location],
                    message=f"Missing required features: {', '.join(missing)}"
                ))
        
        # Check capacity
        capacity = self._check_capacity(sku_name, location)
        result.capacity_info = capacity
        if capacity and not capacity.on_demand_available:
            result.add_warning(f"On-demand capacity may be limited for {sku_name} in {location}")
        
        return result
    
    def get_available_skus(
        self,
        location: str,
        min_vcpus: int = 0,
        max_vcpus: int = 1000,
        min_memory_gb: float = 0,
        max_memory_gb: float = 10000,
        required_features: Optional[List[str]] = None,
        exclude_restricted: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all available SKUs matching criteria with constraint info.
        
        Args:
            location: Azure region
            min_vcpus: Minimum vCPUs
            max_vcpus: Maximum vCPUs
            min_memory_gb: Minimum memory in GB
            max_memory_gb: Maximum memory in GB
            required_features: Required features
            exclude_restricted: Whether to exclude restricted SKUs
        
        Returns:
            List of SKU info dicts with constraint details
        """
        available_skus = []
        
        try:
            # Get all SKUs for location
            resource_skus = self.azure_client.compute_client.resource_skus.list(
                filter=f"location eq '{location}'"
            )
            
            for sku in resource_skus:
                if sku.resource_type != "virtualMachines":
                    continue
                
                # Parse capabilities
                sku_info = self._parse_sku_capabilities(sku)
                
                # Apply filters
                if sku_info["vcpus"] < min_vcpus or sku_info["vcpus"] > max_vcpus:
                    continue
                if sku_info["memory_gb"] < min_memory_gb or sku_info["memory_gb"] > max_memory_gb:
                    continue
                
                # Check required features
                if required_features:
                    if not all(f in sku_info["features"] for f in required_features):
                        continue
                
                # Check restrictions
                restrictions = self._parse_restrictions(sku, location)
                sku_info["restrictions"] = restrictions
                sku_info["is_restricted"] = len(restrictions) > 0
                
                if exclude_restricted and sku_info["is_restricted"]:
                    continue
                
                # Add zone info
                sku_info["available_zones"] = self._get_available_zones(sku, location)
                
                available_skus.append(sku_info)
            
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch SKUs: {e}[/yellow]")
        
        return available_skus
    
    def get_quota_usage(self, location: str) -> List[QuotaInfo]:
        """
        Get quota usage for all VM families in a location.
        
        Args:
            location: Azure region
        
        Returns:
            List of QuotaInfo for each VM family
        """
        cache_key = location.lower().replace(" ", "")
        
        if cache_key in self._quota_cache:
            return self._quota_cache[cache_key]
        
        quotas = []
        
        try:
            usages = self.azure_client.compute_client.usage.list(location)
            
            for usage in usages:
                if "virtualMachines" in (usage.name.value or "").lower() or \
                   "cores" in (usage.name.value or "").lower() or \
                   "vcpu" in (usage.name.localized_value or "").lower():
                    quotas.append(QuotaInfo(
                        family=usage.name.localized_value or usage.name.value or "Unknown",
                        location=location,
                        current_usage=usage.current_value or 0,
                        limit=usage.limit or 0,
                        unit=usage.unit or "Count",
                    ))
            
            self._quota_cache[cache_key] = quotas
            
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch quota: {e}[/yellow]")
        
        return quotas
    
    def check_deployment_feasibility(
        self,
        sku_name: str,
        location: str,
        count: int = 1,
        zones: Optional[List[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Check if a deployment is feasible.
        
        Args:
            sku_name: Target SKU
            location: Target region
            count: Number of VMs to deploy
            zones: Target availability zones
        
        Returns:
            Tuple of (is_feasible, list of issues)
        """
        issues = []
        
        # Get SKU info
        sku_info = self._get_sku_info(sku_name, location)
        if not sku_info:
            issues.append(f"SKU {sku_name} not found in {location}")
            return False, issues
        
        # Check restrictions
        if sku_info.get("is_restricted"):
            for restriction in sku_info.get("restrictions", []):
                issues.append(f"Restriction: {restriction.message}")
        
        # Check quota
        vcpus_needed = sku_info.get("vcpus", 0) * count
        if vcpus_needed > 0:
            family = self._get_sku_family(sku_name)
            quotas = self.get_quota_usage(location)
            
            # Find matching quota
            family_quota = None
            total_quota = None
            
            for quota in quotas:
                if family.lower() in quota.family.lower():
                    family_quota = quota
                if "total" in quota.family.lower() and "vcpu" in quota.family.lower():
                    total_quota = quota
            
            if family_quota and family_quota.available < vcpus_needed:
                issues.append(
                    f"Insufficient {family} quota: need {vcpus_needed} vCPUs, "
                    f"only {family_quota.available} available (limit: {family_quota.limit})"
                )
            
            if total_quota and total_quota.available < vcpus_needed:
                issues.append(
                    f"Insufficient total vCPU quota: need {vcpus_needed}, "
                    f"only {total_quota.available} available"
                )
        
        # Check zone availability
        if zones:
            available_zones = sku_info.get("available_zones", [])
            missing_zones = [z for z in zones if z not in available_zones]
            if missing_zones:
                issues.append(f"SKU not available in zones: {', '.join(missing_zones)}")
        
        return len(issues) == 0, issues
    
    def _get_sku_restrictions(self, sku_name: str, location: str) -> List[SKURestriction]:
        """Get restrictions for a specific SKU."""
        cache_key = f"{sku_name}_{location}"
        
        if cache_key in self._restriction_cache:
            return self._restriction_cache[cache_key]
        
        restrictions = []
        
        try:
            resource_skus = self.azure_client.compute_client.resource_skus.list(
                filter=f"location eq '{location}'"
            )
            
            for sku in resource_skus:
                if sku.name == sku_name and sku.resource_type == "virtualMachines":
                    restrictions = self._parse_restrictions(sku, location)
                    break
            
            self._restriction_cache[cache_key] = restrictions
            
        except Exception as e:
            pass
        
        return restrictions
    
    def _parse_restrictions(self, sku, location: str) -> List[SKURestriction]:
        """Parse restrictions from a SKU resource."""
        restrictions = []
        
        for restriction in sku.restrictions or []:
            # Check if restriction applies to this location
            applies_to_location = False
            restricted_zones = []
            
            if restriction.type == "Location":
                if location.lower().replace(" ", "") in [
                    v.lower().replace(" ", "") for v in (restriction.values or [])
                ]:
                    applies_to_location = True
            
            elif restriction.type == "Zone":
                if restriction.restriction_info:
                    restricted_zones = restriction.restriction_info.zones or []
                    if restricted_zones:
                        applies_to_location = True
            
            if applies_to_location:
                reason_code = (restriction.reason_code or "").replace(" ", "")
                try:
                    reason = RestrictionReason(reason_code)
                except ValueError:
                    reason = RestrictionReason.NOT_AVAILABLE_FOR_SUBSCRIPTION
                
                restrictions.append(SKURestriction(
                    sku_name=sku.name or "",
                    restriction_type=RestrictionType(restriction.type or "Location"),
                    reason=reason,
                    locations=[location] if restriction.type == "Location" else [],
                    zones=restricted_zones,
                    message=f"{restriction.type}: {reason_code}"
                ))
        
        return restrictions
    
    def _parse_sku_capabilities(self, sku) -> Dict[str, Any]:
        """Parse capabilities from a SKU resource."""
        info = {
            "name": sku.name or "",
            "family": sku.family or "",
            "vcpus": 0,
            "memory_gb": 0.0,
            "max_data_disks": 0,
            "max_iops": 0,
            "max_network_interfaces": 0,
            "generation": "Unknown",
            "features": [],
            "tier": sku.tier or "Standard",
        }
        
        for cap in sku.capabilities or []:
            name = cap.name or ""
            value = cap.value or ""
            
            if name == "vCPUs":
                info["vcpus"] = int(value) if value else 0
            elif name == "MemoryGB":
                info["memory_gb"] = float(value) if value else 0.0
            elif name == "MaxDataDiskCount":
                info["max_data_disks"] = int(value) if value else 0
            elif name == "UncachedDiskIOPS":
                info["max_iops"] = int(value) if value else 0
            elif name == "MaxNetworkInterfaces":
                info["max_network_interfaces"] = int(value) if value else 0
            elif name == "HyperVGenerations":
                info["generation"] = value
            elif name == "AcceleratedNetworkingEnabled" and value == "True":
                info["features"].append("AcceleratedNetworking")
            elif name == "PremiumIO" and value == "True":
                info["features"].append("PremiumStorage")
            elif name == "EphemeralOSDiskSupported" and value == "True":
                info["features"].append("EphemeralOSDisk")
            elif name == "EncryptionAtHostSupported" and value == "True":
                info["features"].append("EncryptionAtHost")
            elif name == "UltraSSDAvailable" and value == "True":
                info["features"].append("UltraSSD")
            elif name == "CpuArchitectureType":
                info["cpu_architecture"] = value
            elif name == "LowPriorityCapable" and value == "True":
                info["features"].append("SpotCapable")
            elif name == "HibernationSupported" and value == "True":
                info["features"].append("Hibernation")
        
        return info
    
    def _get_available_zones(self, sku, location: str) -> List[str]:
        """Get available zones for a SKU in a location."""
        zones = set()
        
        # Get zones from location info
        for loc_info in sku.location_info or []:
            if loc_info.location and loc_info.location.lower().replace(" ", "") == location.lower().replace(" ", ""):
                zones.update(loc_info.zones or [])
        
        # Remove restricted zones
        for restriction in sku.restrictions or []:
            if restriction.type == "Zone" and restriction.restriction_info:
                restricted = set(restriction.restriction_info.zones or [])
                zones -= restricted
        
        return sorted(list(zones))
    
    def _check_quota(self, sku_name: str, location: str, required_vcpus: int) -> Optional[QuotaInfo]:
        """Check if quota is available for a SKU."""
        family = self._get_sku_family(sku_name)
        quotas = self.get_quota_usage(location)
        
        for quota in quotas:
            if family.lower() in quota.family.lower():
                return quota
        
        # Return total vCPU quota if family-specific not found
        for quota in quotas:
            if "total" in quota.family.lower() and "vcpu" in quota.family.lower():
                return quota
        
        return None
    
    def _check_zone_availability(
        self,
        sku_name: str,
        location: str,
        required_zones: List[str],
    ) -> Tuple[bool, List[str]]:
        """Check if SKU is available in required zones."""
        sku_info = self._get_sku_info(sku_name, location)
        if not sku_info:
            return False, required_zones
        
        available_zones = sku_info.get("available_zones", [])
        missing = [z for z in required_zones if z not in available_zones]
        
        return len(missing) == 0, missing
    
    def _check_features(
        self,
        sku_name: str,
        location: str,
        required_features: List[str],
    ) -> List[str]:
        """Check if SKU supports required features."""
        sku_info = self._get_sku_info(sku_name, location)
        if not sku_info:
            return required_features
        
        sku_features = sku_info.get("features", [])
        missing = [f for f in required_features if f not in sku_features]
        
        return missing
    
    def _check_capacity(self, sku_name: str, location: str) -> CapacityInfo:
        """Check capacity availability for a SKU."""
        # Note: Azure doesn't have a direct API for real-time capacity
        # This is based on SKU restrictions and availability signals
        
        capacity = CapacityInfo(
            sku_name=sku_name,
            location=location,
        )
        
        sku_info = self._get_sku_info(sku_name, location)
        if sku_info:
            capacity.zones = sku_info.get("available_zones", [])
            capacity.spot_available = "SpotCapable" in sku_info.get("features", [])
            
            # If there are restrictions, capacity may be limited
            if sku_info.get("is_restricted"):
                capacity.on_demand_available = False
                capacity.message = "SKU has restrictions in this region"
        
        return capacity
    
    def _get_sku_info(self, sku_name: str, location: str) -> Optional[Dict[str, Any]]:
        """Get cached or fresh SKU info."""
        cache_key = f"{sku_name}_{location}"
        
        if cache_key in self._sku_cache:
            return self._sku_cache[cache_key]
        
        try:
            resource_skus = self.azure_client.compute_client.resource_skus.list(
                filter=f"location eq '{location}'"
            )
            
            for sku in resource_skus:
                if sku.name == sku_name and sku.resource_type == "virtualMachines":
                    info = self._parse_sku_capabilities(sku)
                    info["restrictions"] = self._parse_restrictions(sku, location)
                    info["is_restricted"] = len(info["restrictions"]) > 0
                    info["available_zones"] = self._get_available_zones(sku, location)
                    
                    self._sku_cache[cache_key] = info
                    return info
                    
        except Exception:
            pass
        
        return None
    
    def _get_sku_family(self, sku_name: str) -> str:
        """Extract VM family from SKU name."""
        # Standard_D4s_v5 -> D
        # Standard_E8s_v3 -> E
        # Standard_F16s_v2 -> F
        
        parts = sku_name.replace("Standard_", "").split("_")
        if parts:
            # Extract letter prefix
            family = ""
            for char in parts[0]:
                if char.isalpha():
                    family += char
                else:
                    break
            return family or "Standard"
        return "Standard"


def create_quota_table(quotas: List[QuotaInfo]) -> Table:
    """Create a rich table showing quota usage."""
    table = Table(
        title="📊 VM Quota Usage",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    
    table.add_column("VM Family", style="white")
    table.add_column("Current", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("Available", justify="right", style="green")
    table.add_column("Usage", justify="right")
    table.add_column("Status", justify="center")
    
    for quota in sorted(quotas, key=lambda q: q.usage_percent, reverse=True):
        # Color code usage
        if quota.usage_percent >= 90:
            usage_color = "red"
            status = "🔴 Critical"
        elif quota.usage_percent >= 70:
            usage_color = "yellow"
            status = "🟡 Warning"
        else:
            usage_color = "green"
            status = "🟢 OK"
        
        table.add_row(
            quota.family[:40] + "..." if len(quota.family) > 40 else quota.family,
            str(quota.current_usage),
            str(quota.limit),
            str(quota.available),
            f"[{usage_color}]{quota.usage_percent:.1f}%[/{usage_color}]",
            status,
        )
    
    return table


def create_validation_table(results: List[SKUValidationResult]) -> Table:
    """Create a rich table showing SKU validation results."""
    table = Table(
        title="✅ SKU Validation Results",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    
    table.add_column("SKU", style="white")
    table.add_column("Location", style="dim")
    table.add_column("Valid", justify="center")
    table.add_column("Restrictions", style="yellow")
    table.add_column("Quota", justify="center")
    table.add_column("Zones", justify="center")
    
    for result in results:
        valid_icon = "✅" if result.is_valid else "❌"
        
        # Restrictions summary
        restrictions = []
        for r in result.restrictions:
            restrictions.append(f"{r.restriction_type.value}: {r.reason.value}")
        restriction_text = "\n".join(restrictions) if restrictions else "-"
        
        # Quota status
        quota_text = "-"
        if result.quota_info:
            q = result.quota_info
            quota_text = f"{q.available}/{q.limit}"
        
        # Zones
        zones_text = "-"
        if result.capacity_info and result.capacity_info.zones:
            zones_text = ", ".join(result.capacity_info.zones)
        
        table.add_row(
            result.sku_name,
            result.location,
            valid_icon,
            restriction_text,
            quota_text,
            zones_text,
        )
    
    return table
