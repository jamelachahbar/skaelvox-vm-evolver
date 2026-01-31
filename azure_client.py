"""
Azure client module for VM rightsizing operations.
Handles authentication and interactions with Azure Resource Manager APIs.
"""
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import time
import functools
import logging
import httpx

logger = logging.getLogger(__name__)


def retry_on_transient(max_retries: int = 3, base_delay: float = 1.0):
    """Retry decorator with exponential backoff for transient HTTP errors."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except httpx.TimeoutException as e:
                    last_exception = e
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (429, 500, 502, 503, 504):
                        last_exception = e
                    else:
                        raise
                except httpx.ConnectError as e:
                    last_exception = e

                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.debug(f"Retry {attempt + 1}/{max_retries} after {delay}s: {last_exception}")
                    time.sleep(delay)

            raise last_exception
        return wrapper
    return decorator

# Handle optional Azure SDK imports
try:
    from azure.identity import DefaultAzureCredential, ClientSecretCredential
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.advisor import AdvisorManagementClient
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.resource import ResourceManagementClient
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False
    DefaultAzureCredential = None
    ClientSecretCredential = None
    ComputeManagementClient = None
    AdvisorManagementClient = None
    MonitorManagementClient = None
    ResourceManagementClient = None

from rich.console import Console

console = Console()


@dataclass
class VMInfo:
    """Represents an Azure VM with its properties."""
    name: str
    resource_group: str
    location: str
    vm_size: str
    vm_id: str
    power_state: str
    os_type: str
    tags: Dict[str, str] = field(default_factory=dict)
    
    # Performance metrics
    avg_cpu: Optional[float] = None
    max_cpu: Optional[float] = None
    avg_memory: Optional[float] = None
    max_memory: Optional[float] = None
    avg_disk_iops: Optional[float] = None
    avg_network_in: Optional[float] = None
    avg_network_out: Optional[float] = None
    
    # Current pricing
    current_price_hourly: Optional[float] = None
    current_price_monthly: Optional[float] = None
    
    # Hardware configuration (for constraint checking)
    data_disk_count: int = 0
    nic_count: int = 1


@dataclass
class AdvisorRecommendation:
    """Represents an Azure Advisor recommendation."""
    recommendation_id: str
    vm_name: str
    resource_group: str
    category: str
    impact: str
    problem: str
    solution: str
    current_sku: Optional[str] = None
    recommended_sku: Optional[str] = None
    estimated_savings: Optional[float] = None
    estimated_savings_percent: Optional[float] = None


@dataclass
class SKURestriction:
    """Represents a restriction on a VM SKU."""
    restriction_type: str  # "Location", "Zone"
    reason_code: str  # "QuotaId", "NotAvailableForSubscription"
    restricted_values: List[str] = field(default_factory=list)
    restricted_zones: List[str] = field(default_factory=list)


@dataclass
class SKUInfo:
    """Represents an Azure VM SKU with pricing."""
    name: str
    family: str
    vcpus: int
    memory_gb: float
    max_data_disks: int
    max_iops: int
    max_network_bandwidth_mbps: int
    generation: str
    features: List[str] = field(default_factory=list)
    
    # Constraints and capabilities
    is_restricted: bool = False
    restrictions: List[SKURestriction] = field(default_factory=list)
    available_zones: List[str] = field(default_factory=list)
    
    # Additional capabilities
    low_priority_capable: bool = False
    premium_io: bool = False
    accelerated_networking: bool = False
    encryption_at_host: bool = False
    ultra_ssd_available: bool = False
    nested_virtualization: bool = False
    trusted_launch: bool = False
    confidential_computing: bool = False
    
    # Pricing per region
    prices: Dict[str, float] = field(default_factory=dict)
    
    # Ranking score
    score: Optional[float] = None
    
    def is_available_in_zone(self, zone: str) -> bool:
        """Check if SKU is available in a specific zone."""
        if not self.available_zones:
            return True  # No zone restrictions
        return zone in self.available_zones
    
    def get_restriction_reason(self) -> Optional[str]:
        """Get human-readable restriction reason."""
        if not self.restrictions:
            return None
        reasons = []
        for r in self.restrictions:
            if r.reason_code == "NotAvailableForSubscription":
                reasons.append("Not available for this subscription type")
            elif r.reason_code == "QuotaId":
                reasons.append("Quota restriction")
            elif r.restriction_type == "Zone":
                reasons.append(f"Zone restricted: {', '.join(r.restricted_zones)}")
        return "; ".join(reasons) if reasons else None


class AzureClient:
    """Client for Azure API interactions."""
    
    def __init__(
        self,
        subscription_id: str,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        if not AZURE_SDK_AVAILABLE:
            raise ImportError(
                "Azure SDK not installed. Please install with: "
                "pip install azure-identity azure-mgmt-compute azure-mgmt-advisor "
                "azure-mgmt-monitor azure-mgmt-resource"
            )
        
        self.subscription_id = subscription_id
        
        # Setup credentials
        if client_id and client_secret and tenant_id:
            self.credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )
        else:
            self.credential = DefaultAzureCredential()
        
        # Initialize clients
        self.compute_client = ComputeManagementClient(
            self.credential, subscription_id
        )
        self.advisor_client = AdvisorManagementClient(
            self.credential, subscription_id
        )
        self.monitor_client = MonitorManagementClient(
            self.credential, subscription_id
        )
        self.resource_client = ResourceManagementClient(
            self.credential, subscription_id
        )

        # Dynamic memory cache (populated from SKU API data)
        self._sku_memory_cache: Dict[str, float] = {}

    def list_vms(self, resource_group: Optional[str] = None) -> List[VMInfo]:
        """List all VMs in the subscription or resource group."""
        vms = []
        
        if resource_group:
            vm_list = self.compute_client.virtual_machines.list(resource_group)
        else:
            vm_list = self.compute_client.virtual_machines.list_all()
        
        for vm in vm_list:
            # Parse resource group from ID
            rg = vm.id.split("/")[4]
            
            # Get instance view for power state
            try:
                instance_view = self.compute_client.virtual_machines.instance_view(
                    rg, vm.name
                )
                power_state = "Unknown"
                for status in instance_view.statuses or []:
                    if status.code and status.code.startswith("PowerState/"):
                        power_state = status.code.replace("PowerState/", "")
                        break
            except Exception:
                power_state = "Unknown"
            
            # Determine OS type
            os_type = "Unknown"
            if vm.storage_profile and vm.storage_profile.os_disk:
                os_type = vm.storage_profile.os_disk.os_type or "Unknown"
            
            # Count data disks
            data_disk_count = 0
            if vm.storage_profile and vm.storage_profile.data_disks:
                data_disk_count = len(vm.storage_profile.data_disks)
            
            # Count network interfaces
            nic_count = 1
            if vm.network_profile and vm.network_profile.network_interfaces:
                nic_count = len(vm.network_profile.network_interfaces)
            
            vms.append(VMInfo(
                name=vm.name,
                resource_group=rg,
                location=vm.location,
                vm_size=vm.hardware_profile.vm_size if vm.hardware_profile else "Unknown",
                vm_id=vm.id,
                power_state=power_state,
                os_type=str(os_type),
                tags=dict(vm.tags) if vm.tags else {},
                data_disk_count=data_disk_count,
                nic_count=nic_count,
            ))
        
        return vms
    
    def get_vm_metrics(
        self,
        vm: VMInfo,
        lookback_days: int = 30,
    ) -> VMInfo:
        """Get performance metrics for a VM."""
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=lookback_days)
        timespan = f"{start_time.isoformat()}Z/{end_time.isoformat()}Z"
        
        resource_id = vm.vm_id
        
        metrics_to_fetch = [
            ("Percentage CPU", "avg_cpu", "max_cpu"),
            ("Available Memory Bytes", "avg_memory", "max_memory"),
            ("Disk Read Operations/Sec", "avg_disk_iops", None),
            ("Network In Total", "avg_network_in", None),
            ("Network Out Total", "avg_network_out", None),
        ]
        
        # Track min available memory separately for correct max usage calculation
        _min_available_memory = None

        for metric_name, avg_attr, max_attr in metrics_to_fetch:
            try:
                metrics = self.monitor_client.metrics.list(
                    resource_id,
                    timespan=timespan,
                    interval="PT1H",
                    metricnames=metric_name,
                    aggregation="Average,Maximum",
                )

                for metric in metrics.value:
                    avg_values = []
                    max_values = []

                    for ts in metric.timeseries:
                        for data in ts.data:
                            if data.average is not None:
                                avg_values.append(data.average)
                            if data.maximum is not None:
                                max_values.append(data.maximum)

                    if avg_values:
                        setattr(vm, avg_attr, sum(avg_values) / len(avg_values))
                    if max_attr and max_values:
                        setattr(vm, max_attr, max(max_values))

                    # For "Available Memory Bytes", track min available
                    # (min available = max memory usage)
                    if metric_name == "Available Memory Bytes" and avg_values:
                        _min_available_memory = min(avg_values)

            except Exception as e:
                # Metrics might not be available for all VMs
                pass

        # Convert memory from bytes to percentage
        # Azure reports "Available Memory Bytes" - we convert to "Used Memory %"
        if vm.avg_memory is not None:
            # Get total memory from SKU (need to look it up)
            total_memory_bytes = self._get_vm_total_memory_bytes(vm.vm_size)
            if total_memory_bytes and total_memory_bytes > 0:
                # Calculate used memory percentage: (total - available) / total * 100
                avg_available = vm.avg_memory
                # Min available memory = when most memory was in use = max usage
                min_available = _min_available_memory if _min_available_memory is not None else avg_available

                vm.avg_memory = ((total_memory_bytes - avg_available) / total_memory_bytes) * 100
                # For max memory usage, use min available (when most memory was in use)
                vm.max_memory = ((total_memory_bytes - min_available) / total_memory_bytes) * 100

                # Clamp to valid range
                vm.avg_memory = max(0, min(100, vm.avg_memory))
                vm.max_memory = max(0, min(100, vm.max_memory))
            else:
                # Fallback: estimate based on common SKU sizes
                vm.avg_memory = None
                vm.max_memory = None
        
        return vm
    
    def populate_memory_cache(self, skus: List['SKUInfo']) -> None:
        """Populate the memory cache from fetched SKU data.

        Call this with SKU data from get_available_skus() to enable dynamic
        memory resolution for any SKU, not just the hardcoded ones.
        """
        for sku in skus:
            if sku.name and sku.memory_gb > 0:
                self._sku_memory_cache[sku.name] = sku.memory_gb

    def _get_vm_total_memory_bytes(self, vm_size: str) -> Optional[float]:
        """Get total memory in bytes for a VM SKU.

        Checks the dynamic SKU cache first (populated from Azure API),
        then falls back to hardcoded mappings for offline/cached scenarios.
        """
        # First: check dynamic SKU cache (populated from Azure API)
        if hasattr(self, '_sku_memory_cache') and vm_size in self._sku_memory_cache:
            return self._sku_memory_cache[vm_size] * 1024 * 1024 * 1024

        # Fallback: Common SKU memory mappings (in GB)
        sku_memory_gb = {
            # B-series (burstable)
            "Standard_B1s": 1, "Standard_B1ms": 2, "Standard_B2s": 4, "Standard_B2ms": 8,
            "Standard_B4ms": 16, "Standard_B8ms": 32, "Standard_B12ms": 48,
            # D-series v3
            "Standard_D2s_v3": 8, "Standard_D4s_v3": 16, "Standard_D8s_v3": 32,
            "Standard_D16s_v3": 64, "Standard_D32s_v3": 128,
            # D-series v4
            "Standard_D2s_v4": 8, "Standard_D4s_v4": 16, "Standard_D8s_v4": 32,
            "Standard_D16s_v4": 64, "Standard_D32s_v4": 128,
            # D-series v5
            "Standard_D2s_v5": 8, "Standard_D4s_v5": 16, "Standard_D8s_v5": 32,
            "Standard_D16s_v5": 64, "Standard_D32s_v5": 128,
            "Standard_D2ads_v5": 8, "Standard_D4ads_v5": 16, "Standard_D8ads_v5": 32,
            # E-series (memory optimized)
            "Standard_E2s_v3": 16, "Standard_E4s_v3": 32, "Standard_E8s_v3": 64,
            "Standard_E16s_v3": 128, "Standard_E32s_v3": 256,
            "Standard_E2s_v4": 16, "Standard_E4s_v4": 32, "Standard_E8s_v4": 64,
            "Standard_E2s_v5": 16, "Standard_E4s_v5": 32, "Standard_E8s_v5": 64,
            # F-series (compute optimized)
            "Standard_F2s_v2": 4, "Standard_F4s_v2": 8, "Standard_F8s_v2": 16,
            "Standard_F16s_v2": 32, "Standard_F32s_v2": 64,
        }

        # Look up directly
        if vm_size in sku_memory_gb:
            return sku_memory_gb[vm_size] * 1024 * 1024 * 1024

        # Try pattern matching for similar SKUs
        for sku, memory_gb in sku_memory_gb.items():
            # Match base name (e.g., D8s matches D8s_v3, D8s_v4, D8s_v5)
            base_sku = sku.rsplit('_', 1)[0]  # Remove version suffix
            if vm_size.startswith(base_sku):
                return memory_gb * 1024 * 1024 * 1024

        return None
    
    def get_advisor_recommendations(
        self,
        category: str = "Cost",
    ) -> List[AdvisorRecommendation]:
        """Get Azure Advisor recommendations for VMs."""
        recommendations = []
        
        try:
            # List all recommendations
            advisor_recs = self.advisor_client.recommendations.list(
                filter=f"Category eq '{category}'"
            )
            
            for rec in advisor_recs:
                # Filter for VM-related recommendations
                if rec.impacted_field and "virtualmachines" in rec.impacted_field.lower():
                    # Parse resource info
                    resource_id = rec.resource_metadata.resource_id if rec.resource_metadata else ""
                    parts = resource_id.split("/") if resource_id else []
                    
                    vm_name = parts[-1] if len(parts) > 1 else "Unknown"
                    resource_group = parts[4] if len(parts) > 4 else "Unknown"
                    
                    # Extract SKU recommendations from extended properties
                    current_sku = None
                    recommended_sku = None
                    savings = None
                    savings_percent = None

                    if rec.extended_properties:
                        current_sku = rec.extended_properties.get("currentSku")
                        recommended_sku = rec.extended_properties.get("targetSku")
                        savings = rec.extended_properties.get("savingsAmount")
                        savings_percent = rec.extended_properties.get("savingsPercentage")

                        if savings:
                            try:
                                savings = float(savings)
                            except (ValueError, TypeError):
                                savings = None

                        if savings_percent:
                            try:
                                savings_percent = float(savings_percent)
                            except (ValueError, TypeError):
                                savings_percent = None

                    recommendations.append(AdvisorRecommendation(
                        recommendation_id=rec.id or "",
                        vm_name=vm_name,
                        resource_group=resource_group,
                        category=rec.category or "Cost",
                        impact=rec.impact or "Medium",
                        problem=rec.short_description.problem if rec.short_description else "",
                        solution=rec.short_description.solution if rec.short_description else "",
                        current_sku=current_sku,
                        recommended_sku=recommended_sku,
                        estimated_savings=savings,
                        estimated_savings_percent=savings_percent,
                    ))
                    
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch Advisor recommendations: {e}[/yellow]")
        
        return recommendations
    
    def get_available_skus(
        self,
        location: str,
        include_restricted: bool = False,
    ) -> List[SKUInfo]:
        """Get available VM SKUs for a location with full constraint checking."""
        skus = []
        
        try:
            resource_skus = self.compute_client.resource_skus.list(
                filter=f"location eq '{location}'"
            )
            
            for sku in resource_skus:
                if sku.resource_type != "virtualMachines":
                    continue
                
                # Parse capabilities
                vcpus = 0
                memory_gb = 0.0
                max_data_disks = 0
                max_iops = 0
                max_network = 0
                generation = "Unknown"
                features = []
                available_zones = []
                
                # Capability flags
                low_priority_capable = False
                premium_io = False
                accelerated_networking = False
                encryption_at_host = False
                ultra_ssd_available = False
                nested_virtualization = False
                trusted_launch = False
                confidential_computing = False
                
                for cap in sku.capabilities or []:
                    cap_name = cap.name or ""
                    cap_value = cap.value or ""
                    
                    # Core specs
                    if cap_name == "vCPUs":
                        vcpus = int(cap_value) if cap_value else 0
                    elif cap_name == "MemoryGB":
                        memory_gb = float(cap_value) if cap_value else 0
                    elif cap_name == "MaxDataDiskCount":
                        max_data_disks = int(cap_value) if cap_value else 0
                    elif cap_name == "UncachedDiskIOPS":
                        max_iops = int(cap_value) if cap_value else 0
                    elif cap_name == "UncachedDiskBytesPerSecond":
                        max_network = int(cap_value) // (1024 * 1024) if cap_value else 0
                    elif cap_name == "HyperVGenerations":
                        generation = cap_value
                    
                    # Feature capabilities
                    elif cap_name == "AcceleratedNetworkingEnabled":
                        accelerated_networking = cap_value.lower() == "true"
                        if accelerated_networking:
                            features.append("AcceleratedNetworking")
                    elif cap_name == "PremiumIO":
                        premium_io = cap_value.lower() == "true"
                        if premium_io:
                            features.append("PremiumStorage")
                    elif cap_name == "EphemeralOSDiskSupported":
                        if cap_value.lower() == "true":
                            features.append("EphemeralOSDisk")
                    elif cap_name == "LowPriorityCapable":
                        low_priority_capable = cap_value.lower() == "true"
                        if low_priority_capable:
                            features.append("SpotCapable")
                    elif cap_name == "EncryptionAtHostSupported":
                        encryption_at_host = cap_value.lower() == "true"
                        if encryption_at_host:
                            features.append("EncryptionAtHost")
                    elif cap_name == "UltraSSDAvailable":
                        ultra_ssd_available = cap_value.lower() == "true"
                        if ultra_ssd_available:
                            features.append("UltraSSD")
                    elif cap_name == "HyperVGenerations" and "V2" in cap_value:
                        features.append("Gen2")
                    elif cap_name == "CpuArchitectureType":
                        if cap_value:
                            features.append(f"Arch:{cap_value}")
                    elif cap_name == "NestingSupported":
                        nested_virtualization = cap_value.lower() == "true"
                        if nested_virtualization:
                            features.append("NestedVirtualization")
                    elif cap_name == "TrustedLaunchDisabled":
                        trusted_launch = cap_value.lower() != "true"
                    elif cap_name == "ConfidentialComputingType":
                        if cap_value:
                            confidential_computing = True
                            features.append(f"Confidential:{cap_value}")
                
                # Parse location info for zones
                for loc_info in sku.location_info or []:
                    if loc_info.location and loc_info.location.lower() == location.lower():
                        available_zones = list(loc_info.zones or [])
                        break
                
                # Parse restrictions
                sku_restrictions = []
                is_restricted = False
                
                for restriction in sku.restrictions or []:
                    restriction_type = restriction.type or ""
                    reason_code = restriction.reason_code or ""
                    restricted_values = []
                    restricted_zones = []
                    
                    # Check if this restriction applies to our location
                    applies_to_location = False
                    
                    if restriction.restriction_info:
                        # Get restricted locations
                        if restriction.restriction_info.locations:
                            restricted_values = list(restriction.restriction_info.locations)
                            if location.lower() in [l.lower() for l in restricted_values]:
                                applies_to_location = True
                        
                        # Get restricted zones
                        if restriction.restriction_info.zones:
                            restricted_zones = list(restriction.restriction_info.zones)
                    
                    # Also check values field (older API format)
                    if restriction.values:
                        if restriction_type == "Location":
                            restricted_values.extend(restriction.values)
                            if location.lower() in [v.lower() for v in restriction.values]:
                                applies_to_location = True
                        elif restriction_type == "Zone":
                            restricted_zones.extend(restriction.values)
                            applies_to_location = True
                    
                    if applies_to_location or restriction_type == "Zone":
                        sku_restriction = SKURestriction(
                            restriction_type=restriction_type,
                            reason_code=reason_code,
                            restricted_values=restricted_values,
                            restricted_zones=restricted_zones,
                        )
                        sku_restrictions.append(sku_restriction)
                        
                        # Mark as restricted if it's a location restriction that applies
                        if restriction_type == "Location" and applies_to_location:
                            is_restricted = True
                        # Or if it's NotAvailableForSubscription
                        if reason_code == "NotAvailableForSubscription":
                            is_restricted = True
                
                # Skip restricted SKUs unless explicitly requested
                if is_restricted and not include_restricted:
                    continue
                
                skus.append(SKUInfo(
                    name=sku.name or "",
                    family=sku.family or "",
                    vcpus=vcpus,
                    memory_gb=memory_gb,
                    max_data_disks=max_data_disks,
                    max_iops=max_iops,
                    max_network_bandwidth_mbps=max_network,
                    generation=generation,
                    features=features,
                    is_restricted=is_restricted,
                    restrictions=sku_restrictions,
                    available_zones=available_zones,
                    low_priority_capable=low_priority_capable,
                    premium_io=premium_io,
                    accelerated_networking=accelerated_networking,
                    encryption_at_host=encryption_at_host,
                    ultra_ssd_available=ultra_ssd_available,
                    nested_virtualization=nested_virtualization,
                    trusted_launch=trusted_launch,
                    confidential_computing=confidential_computing,
                ))
                    
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch SKUs for {location}: {e}[/yellow]")
        
        return skus


class PricingClient:
    """Client for Azure Retail Prices API."""
    
    BASE_URL = "https://prices.azure.com/api/retail/prices"
    
    def __init__(self):
        self.client = httpx.Client(timeout=30.0)
        self._price_cache: Dict[str, Dict[str, float]] = {}
    
    def get_vm_prices(
        self,
        sku_name: str,
        regions: List[str],
        os_type: str = "Linux",
    ) -> Dict[str, float]:
        """Get VM prices for multiple regions."""
        cache_key = f"{sku_name}_{os_type}"
        
        # Initialize cache for this key if needed
        if cache_key not in self._price_cache:
            self._price_cache[cache_key] = {}
        
        prices = {}
        regions_to_fetch = []
        
        # Check cache for each region
        for region in regions:
            arm_region = region.replace(" ", "").lower()
            if arm_region in self._price_cache[cache_key]:
                prices[arm_region] = self._price_cache[cache_key][arm_region]
            else:
                regions_to_fetch.append(arm_region)
        
        # Fetch only uncached regions
        for arm_region in regions_to_fetch:
            filter_query = (
                f"serviceName eq 'Virtual Machines' and "
                f"armSkuName eq '{sku_name}' and "
                f"armRegionName eq '{arm_region}' and "
                f"priceType eq 'Consumption' and "
                f"contains(productName, '{os_type}')"
            )

            try:
                items = self._fetch_pricing_items(filter_query)

                # Get the regular (non-Spot, non-Low Priority) price
                for item in items:
                    sku_name_item = item.get("skuName", "")
                    # Skip Spot and Low Priority
                    if "Spot" in sku_name_item or "Low Priority" in sku_name_item:
                        continue

                    price = item.get("retailPrice", 0)
                    if price > 0:
                        prices[arm_region] = price
                        self._price_cache[cache_key][arm_region] = price
                        break  # Got the regular price, stop

            except Exception as e:
                # Price not available for this region
                pass

        return prices

    @retry_on_transient(max_retries=3, base_delay=1.0)
    def _fetch_page(self, url: str, params: Optional[dict] = None) -> dict:
        """Fetch a single page from the pricing API with retry logic."""
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _fetch_pricing_items(self, filter_query: str) -> List[dict]:
        """Fetch all pricing items, handling pagination via NextPageLink."""
        all_items = []
        data = self._fetch_page(self.BASE_URL, params={"$filter": filter_query})
        all_items.extend(data.get("Items", []))

        # Follow NextPageLink for paginated results
        next_page = data.get("NextPageLink")
        while next_page:
            data = self._fetch_page(next_page)
            all_items.extend(data.get("Items", []))
            next_page = data.get("NextPageLink")

        return all_items
    
    def get_price(
        self,
        sku_name: str,
        region: str,
        os_type: str = "Linux",
    ) -> Optional[float]:
        """Get VM price for a single region."""
        prices = self.get_vm_prices(sku_name, [region], os_type)
        return prices.get(region.replace(" ", "").lower())
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        """Support context manager protocol."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the HTTP client on context exit."""
        self.close()
        return False


@dataclass
class PlacementScore:
    """Represents an Azure Spot Placement Score result."""
    sku: str
    location: str
    zone: Optional[str] = None
    score: str = "Unknown"  # High, Medium, Low, or Unknown
    is_zonal: bool = False


class SpotPlacementScoreClient:
    """Client for Azure Spot Placement Score API."""
    
    API_VERSION = "2025-06-05"
    
    def __init__(
        self,
        subscription_id: str,
        credential: Optional[Any] = None,
    ):
        """
        Initialize the Spot Placement Score client.
        
        Args:
            subscription_id: Azure subscription ID
            credential: Azure credential (DefaultAzureCredential or similar)
        """
        self.subscription_id = subscription_id
        self.credential = credential or (DefaultAzureCredential() if AZURE_SDK_AVAILABLE else None)
        self.client = httpx.Client(timeout=30.0)
        
    def _get_access_token(self) -> str:
        """Get Azure access token for ARM API."""
        if not self.credential:
            raise ValueError("No credential provided for authentication")
        token = self.credential.get_token("https://management.azure.com/.default")
        return token.token
    
    @retry_on_transient(max_retries=3, base_delay=1.0)
    def get_placement_scores(
        self,
        location: str,
        sku_names: List[str],
        desired_count: int = 1,
        availability_zones: bool = True,
    ) -> List[PlacementScore]:
        """
        Get Spot Placement Scores for VM SKUs in a location.
        
        Args:
            location: Azure region (e.g., "eastus", "westeurope")
            sku_names: List of VM SKU names (e.g., ["Standard_D4s_v5"])
            desired_count: Number of VMs to deploy (default: 1)
            availability_zones: Whether to check zone-level scores (default: True)
            
        Returns:
            List of PlacementScore objects with deployment probability
        """
        url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/providers/Microsoft.Compute/locations/{location}"
            f"/placementScores/spot/generate"
            f"?api-version={self.API_VERSION}"
        )
        
        # Build request body
        body = {
            "availabilityZones": availability_zones,
            "desiredCount": desired_count,
            "desiredLocations": [location],
            "desiredSizes": [{"sku": sku} for sku in sku_names],
        }
        
        try:
            # Get access token
            token = self._get_access_token()
            
            # Make API request
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            
            response = self.client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Parse response
            results = []
            placement_scores = data.get("placementScores", [])
            
            for score_data in placement_scores:
                sku = score_data.get("sku", "")
                score_location = score_data.get("location", location)
                is_zonal = score_data.get("isZonal", False)
                
                if is_zonal:
                    # Zone-level scores
                    zone_scores = score_data.get("zoneScores", [])
                    for zone_score in zone_scores:
                        zone = zone_score.get("zone", "")
                        score = zone_score.get("score", "Unknown")
                        results.append(PlacementScore(
                            sku=sku,
                            location=score_location,
                            zone=zone,
                            score=score,
                            is_zonal=True,
                        ))
                else:
                    # Regional score
                    score = score_data.get("score", "Unknown")
                    results.append(PlacementScore(
                        sku=sku,
                        location=score_location,
                        zone=None,
                        score=score,
                        is_zonal=False,
                    ))
            
            return results
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to get placement scores: HTTP {e.response.status_code}")
            # Return unknown scores on failure
            return [
                PlacementScore(sku=sku, location=location, score="Unknown")
                for sku in sku_names
            ]
        except Exception as e:
            logger.warning(f"Failed to get placement scores: {e}")
            return [
                PlacementScore(sku=sku, location=location, score="Unknown")
                for sku in sku_names
            ]
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def __enter__(self):
        """Support context manager protocol."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the HTTP client on context exit."""
        self.close()
        return False
