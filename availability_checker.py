"""
Azure VM SKU Availability Checker with Zone Awareness.

Features:
- Per-zone SKU availability checking
- Similar SKU suggestions when capacity is constrained
- Azure Monitor (Log Analytics) logging integration
- Capacity constraint detection and alternatives

Based on the VM SKU Capacity Monitor pattern.
"""
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import subprocess
import re

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('sku_availability_checker')

# Handle optional Azure SDK imports
try:
    from azure.identity import DefaultAzureCredential, ClientSecretCredential
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.subscription import SubscriptionClient
    from azure.core.exceptions import HttpResponseError
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False
    DefaultAzureCredential = None
    ClientSecretCredential = None
    ComputeManagementClient = None
    SubscriptionClient = None
    HttpResponseError = Exception

# Log Analytics ingestion
try:
    from azure.monitor.ingestion import LogsIngestionClient
    LOG_ANALYTICS_AVAILABLE = True
except ImportError:
    LOG_ANALYTICS_AVAILABLE = False
    LogsIngestionClient = None

console = Console()


@dataclass
class ZoneAvailability:
    """SKU availability status for a specific zone."""
    zone: str
    is_available: bool
    restriction_reason: Optional[str] = None
    capacity_status: str = "Available"  # Available, Constrained, Unavailable


@dataclass
class SKUSpecifications:
    """Parsed SKU specifications/capabilities."""
    vcpus: int = 0
    memory_gb: float = 0.0
    max_data_disks: int = 0
    premium_io: bool = False
    accelerated_networking: bool = False
    encryption_at_host: bool = False
    ultra_ssd_available: bool = False
    hyper_v_generations: str = ""
    cpu_architecture: str = "x64"
    max_network_interfaces: int = 0
    cached_disk_bytes: int = 0
    uncached_disk_iops: int = 0
    uncached_disk_throughput: int = 0
    
    # Raw capabilities dict
    raw_capabilities: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_capabilities(cls, capabilities: List[Any]) -> 'SKUSpecifications':
        """Parse from Azure SDK capabilities list."""
        specs = cls()
        raw = {}
        
        for cap in capabilities or []:
            name = getattr(cap, 'name', '') or ''
            value = getattr(cap, 'value', '') or ''
            raw[name] = value
            
            if name == 'vCPUs':
                specs.vcpus = int(value) if value else 0
            elif name == 'MemoryGB':
                specs.memory_gb = float(value) if value else 0.0
            elif name == 'MaxDataDiskCount':
                specs.max_data_disks = int(value) if value else 0
            elif name == 'PremiumIO':
                specs.premium_io = value.lower() == 'true'
            elif name == 'AcceleratedNetworkingEnabled':
                specs.accelerated_networking = value.lower() == 'true'
            elif name == 'EncryptionAtHostSupported':
                specs.encryption_at_host = value.lower() == 'true'
            elif name == 'UltraSSDAvailable':
                specs.ultra_ssd_available = value.lower() == 'true'
            elif name == 'HyperVGenerations':
                specs.hyper_v_generations = value
            elif name == 'CpuArchitectureType':
                specs.cpu_architecture = value
            elif name == 'MaxNetworkInterfaces':
                specs.max_network_interfaces = int(value) if value else 0
            elif name == 'CachedDiskBytes':
                specs.cached_disk_bytes = int(value) if value else 0
            elif name == 'UncachedDiskIOPS':
                specs.uncached_disk_iops = int(value) if value else 0
            elif name == 'UncachedDiskBytesPerSecond':
                specs.uncached_disk_throughput = int(value) if value else 0
        
        specs.raw_capabilities = raw
        return specs
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'vCPUs': self.vcpus,
            'MemoryGB': self.memory_gb,
            'MaxDataDiskCount': self.max_data_disks,
            'PremiumIO': self.premium_io,
            'AcceleratedNetworkingEnabled': self.accelerated_networking,
            'EncryptionAtHostSupported': self.encryption_at_host,
            'UltraSSDAvailable': self.ultra_ssd_available,
            'HyperVGenerations': self.hyper_v_generations,
            'CpuArchitectureType': self.cpu_architecture,
        }


@dataclass
class AlternativeSKU:
    """A suggested alternative SKU when target is constrained."""
    name: str
    family: str
    vcpus: int
    memory_gb: float
    similarity_score: int  # 0-100
    available_zones: List[str] = field(default_factory=list)
    specifications: Optional[SKUSpecifications] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'name': self.name,
            'family': self.family,
            'vcpus': self.vcpus,
            'memory_gb': self.memory_gb,
            'similarity': self.similarity_score,
            'zones': self.available_zones,
        }


@dataclass
class SKUAvailabilityResult:
    """Complete availability check result for a SKU."""
    sku_name: str
    region: str
    is_available: bool
    restriction_reason: Optional[str] = None
    
    # Zone-level availability
    available_zones: List[str] = field(default_factory=list)
    zone_details: Dict[str, ZoneAvailability] = field(default_factory=dict)
    
    # SKU specifications
    specifications: Optional[SKUSpecifications] = None
    
    # Alternative suggestions if constrained
    alternative_skus: List[AlternativeSKU] = field(default_factory=list)
    
    # Spot Placement Score (High, Medium, Low, or Unknown)
    placement_score: str = "Unknown"
    zone_placement_scores: Dict[str, str] = field(default_factory=dict)  # zone -> score
    
    # Metadata
    subscription_id: str = ""
    subscription_name: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'sku_name': self.sku_name,
            'region': self.region,
            'is_available': self.is_available,
            'restriction_reason': self.restriction_reason,
            'available_zones': self.available_zones,
            'zone_count': len(self.available_zones),
            'alternative_count': len(self.alternative_skus),
            'placement_score': self.placement_score,
            'subscription_id': self.subscription_id,
            'subscription_name': self.subscription_name,
            'checked_at': self.checked_at.isoformat(),
            'vcpus': self.specifications.vcpus if self.specifications else 0,
            'memory_gb': self.specifications.memory_gb if self.specifications else 0,
        }


class LogAnalyticsLogger:
    """Azure Monitor Log Analytics logger using Data Collection Rules."""
    
    def __init__(
        self,
        endpoint: str,
        rule_id: str,
        stream_name: str = "Custom-VMSKUCapacity_CL",
        credential: Any = None,
    ):
        """
        Initialize Log Analytics logger.
        
        Args:
            endpoint: Data Collection Endpoint URI
            rule_id: Data Collection Rule ID
            stream_name: Log Analytics stream name
            credential: Azure credential (uses DefaultAzureCredential if None)
        """
        self.endpoint = endpoint
        self.rule_id = rule_id
        self.stream_name = stream_name
        self.credential = credential or DefaultAzureCredential()
        self._client = None
    
    @property
    def client(self) -> Any:
        """Lazy-initialize the ingestion client."""
        if self._client is None:
            if not LOG_ANALYTICS_AVAILABLE:
                raise ImportError("azure-monitor-ingestion package required for Log Analytics logging")
            self._client = LogsIngestionClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._client
    
    def log_availability_check(self, result: SKUAvailabilityResult) -> bool:
        """
        Log SKU availability check result to Log Analytics.
        
        Args:
            result: The availability check result
            
        Returns:
            True if logging succeeded, False otherwise
        """
        try:
            log_entry = {
                "TimeGenerated": datetime.now(timezone.utc).isoformat(),
                "sku_name": result.sku_name,
                "region": result.region,
                "subscription_id": result.subscription_id,
                "subscription_name": result.subscription_name,
                "is_available": result.is_available,
                "restriction_reason": result.restriction_reason or "",
                "available_zones": ",".join(result.available_zones),
                "zone_count": len(result.available_zones),
                "vcpus": result.specifications.vcpus if result.specifications else 0,
                "memory_gb": result.specifications.memory_gb if result.specifications else 0,
                "alternative_skus": ",".join([s.name for s in result.alternative_skus[:5]]),
                "alternative_count": len(result.alternative_skus),
            }
            
            self.client.upload(
                rule_id=self.rule_id,
                stream_name=self.stream_name,
                logs=[log_entry],
            )
            
            logger.info(f"Successfully logged availability check for {result.sku_name} to Log Analytics")
            return True
            
        except Exception as e:
            logger.error(f"Error logging to Log Analytics: {e}")
            return False
    
    def log_batch(self, results: List[SKUAvailabilityResult]) -> Tuple[int, int]:
        """
        Log multiple results in a batch.
        
        Returns:
            Tuple of (success_count, failure_count)
        """
        log_entries = []
        
        for result in results:
            log_entries.append({
                "TimeGenerated": datetime.now(timezone.utc).isoformat(),
                "sku_name": result.sku_name,
                "region": result.region,
                "subscription_id": result.subscription_id,
                "subscription_name": result.subscription_name,
                "is_available": result.is_available,
                "restriction_reason": result.restriction_reason or "",
                "available_zones": ",".join(result.available_zones),
                "zone_count": len(result.available_zones),
                "vcpus": result.specifications.vcpus if result.specifications else 0,
                "memory_gb": result.specifications.memory_gb if result.specifications else 0,
                "alternative_skus": ",".join([s.name for s in result.alternative_skus[:5]]),
                "alternative_count": len(result.alternative_skus),
            })
        
        try:
            self.client.upload(
                rule_id=self.rule_id,
                stream_name=self.stream_name,
                logs=log_entries,
            )
            logger.info(f"Successfully logged {len(log_entries)} entries to Log Analytics")
            return len(log_entries), 0
            
        except Exception as e:
            logger.error(f"Error logging batch to Log Analytics: {e}")
            return 0, len(log_entries)


class SKUAvailabilityChecker:
    """
    Azure VM SKU Availability Checker with zone awareness.
    
    Checks SKU availability per-zone and suggests alternatives when constrained.
    """
    
    # Key specifications for similarity calculation
    SIMILARITY_KEYS = [
        'vCPUs', 'MemoryGB', 'MaxDataDiskCount', 
        'PremiumIO', 'AcceleratedNetworkingEnabled'
    ]
    
    def __init__(
        self,
        subscription_id: Optional[str] = None,
        credential: Any = None,
        check_placement_scores: bool = False,
    ):
        """
        Initialize the availability checker.
        
        Args:
            subscription_id: Azure subscription ID (auto-detected if None)
            credential: Azure credential (uses DefaultAzureCredential if None)
            check_placement_scores: Whether to check Spot Placement Scores (default: False)
        """
        if not AZURE_SDK_AVAILABLE:
            raise ImportError("Azure SDK packages required. Install with: pip install azure-identity azure-mgmt-compute")
        
        self.credential = credential or DefaultAzureCredential()
        self.subscription_id = subscription_id or self._auto_detect_subscription()
        self.check_placement_scores = check_placement_scores
        
        self._compute_client = None
        self._subscription_client = None
        self._subscription_name: Optional[str] = None
        self._sku_cache: Dict[str, List[Any]] = {}
        self._placement_score_client = None
    
    def _auto_detect_subscription(self) -> str:
        """Auto-detect subscription ID from CLI or SDK."""
        # Try Azure CLI first
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            sub_id = result.stdout.strip()
            if sub_id:
                logger.info(f"Using subscription from Azure CLI: {sub_id}")
                return sub_id
        except Exception:
            logger.debug("Could not get subscription from Azure CLI")
        
        # Fallback to SDK - get first enabled subscription
        try:
            sub_client = SubscriptionClient(self.credential)
            for sub in sub_client.subscriptions.list():
                if hasattr(sub, 'state') and str(sub.state).lower() == 'enabled':
                    logger.info(f"Using first enabled subscription: {sub.subscription_id}")
                    return sub.subscription_id
        except Exception as e:
            logger.debug(f"Could not list subscriptions: {e}")
        
        raise RuntimeError(
            "Unable to auto-detect subscription ID. "
            "Please provide --subscription-id or set AZURE_SUBSCRIPTION_ID"
        )
    
    @property
    def compute_client(self) -> ComputeManagementClient:
        """Lazy-initialize compute client."""
        if self._compute_client is None:
            self._compute_client = ComputeManagementClient(
                self.credential,
                self.subscription_id,
            )
        return self._compute_client
    
    @property
    def placement_score_client(self):
        """Lazy-initialize placement score client."""
        if self._placement_score_client is None and self.check_placement_scores:
            # Import here to avoid circular dependency
            from azure_client import SpotPlacementScoreClient
            self._placement_score_client = SpotPlacementScoreClient(
                self.subscription_id,
                self.credential,
            )
        return self._placement_score_client
    
    @property
    def subscription_name(self) -> str:
        """Get subscription display name."""
        if self._subscription_name is None:
            try:
                sub_client = SubscriptionClient(self.credential)
                sub = sub_client.subscriptions.get(self.subscription_id)
                self._subscription_name = sub.display_name or self.subscription_id
            except Exception:
                self._subscription_name = self.subscription_id
        return self._subscription_name
    
    def _get_all_skus(self, region: Optional[str] = None) -> List[Any]:
        """Get all VM SKUs, with caching."""
        cache_key = region or "all"
        
        if cache_key not in self._sku_cache:
            if region:
                skus = list(self.compute_client.resource_skus.list(
                    filter=f"location eq '{region}'"
                ))
            else:
                skus = list(self.compute_client.resource_skus.list())
            
            # Filter to VMs only
            self._sku_cache[cache_key] = [
                s for s in skus 
                if s.resource_type == 'virtualMachines'
            ]
        
        return self._sku_cache[cache_key]
    
    def check_sku_availability(
        self,
        sku_name: str,
        region: str,
        check_zones: bool = True,
        find_alternatives: bool = True,
        max_alternatives: int = 5,
    ) -> SKUAvailabilityResult:
        """
        Check availability of a specific VM SKU in a region.
        
        Args:
            sku_name: The VM SKU name (e.g., 'Standard_D16ds_v5')
            region: Azure region (e.g., 'eastus2')
            check_zones: Whether to check per-zone availability
            find_alternatives: Whether to find similar SKUs if constrained
            max_alternatives: Maximum number of alternatives to return
            
        Returns:
            SKUAvailabilityResult with availability details and alternatives
        """
        result = SKUAvailabilityResult(
            sku_name=sku_name,
            region=region,
            is_available=False,
            subscription_id=self.subscription_id,
            subscription_name=self.subscription_name,
            checked_at=datetime.now(timezone.utc),
        )
        
        # Get all SKUs for the region
        all_skus = self._get_all_skus(region)
        
        # Find target SKU
        target_sku = None
        for sku in all_skus:
            if sku.name and sku.name.lower() == sku_name.lower():
                # Verify it's in the requested region
                sku_locations = [loc.lower() for loc in (sku.locations or [])]
                if region.lower() in sku_locations:
                    target_sku = sku
                    break
        
        if not target_sku:
            logger.warning(f"SKU {sku_name} not found in region {region}")
            result.restriction_reason = "SKU not found in region"
            return result
        
        # Parse specifications
        result.specifications = SKUSpecifications.from_capabilities(
            getattr(target_sku, 'capabilities', [])
        )
        
        # Check region-level restrictions
        restrictions = getattr(target_sku, 'restrictions', []) or []
        region_restricted = False
        restriction_reason = None
        
        for restriction in restrictions:
            restriction_info = getattr(restriction, 'restriction_info', None)
            if restriction_info:
                restricted_locations = [
                    loc.lower() for loc in (restriction_info.locations or [])
                ]
                if region.lower() in restricted_locations:
                    region_restricted = True
                    restriction_reason = getattr(restriction, 'reason_code', 'Unknown')
                    break
        
        result.is_available = not region_restricted
        result.restriction_reason = restriction_reason
        
        # Check zone availability
        if check_zones:
            location_info_list = getattr(target_sku, 'location_info', []) or []
            for location_info in location_info_list:
                if hasattr(location_info, 'location'):
                    if location_info.location.lower() == region.lower():
                        result.available_zones = list(location_info.zones or [])
                        
                        # Create zone details
                        for zone in result.available_zones:
                            result.zone_details[zone] = ZoneAvailability(
                                zone=zone,
                                is_available=True,
                                capacity_status="Available",
                            )
                        
                        # Check for zone-specific restrictions
                        zone_restrictions = getattr(location_info, 'zone_details', []) or []
                        for zr in zone_restrictions:
                            zone_name = getattr(zr, 'name', None)
                            if zone_name and zone_name in result.zone_details:
                                capabilities = getattr(zr, 'capabilities', []) or []
                                for cap in capabilities:
                                    if getattr(cap, 'name', '') == 'CapacityRestriction':
                                        status = getattr(cap, 'value', 'Available')
                                        result.zone_details[zone_name].capacity_status = status
                                        if status != 'Available':
                                            result.zone_details[zone_name].is_available = False
                        break
        
        # Check Spot Placement Scores if enabled
        if self.check_placement_scores and self.placement_score_client:
            try:
                placement_scores = self.placement_score_client.get_placement_scores(
                    location=region,
                    sku_names=[sku_name],
                    desired_count=1,
                    availability_zones=check_zones and len(result.available_zones) > 0,
                )
                
                for score in placement_scores:
                    if score.is_zonal and score.zone:
                        # Zone-level score
                        result.zone_placement_scores[score.zone] = score.score
                    else:
                        # Regional score
                        result.placement_score = score.score
                        
            except Exception as e:
                logger.debug(f"Could not get placement scores: {e}")
                # Continue without placement scores
        
        # Find alternative SKUs if constrained
        if find_alternatives and not result.is_available:
            result.alternative_skus = self._find_similar_skus(
                target_sku=target_sku,
                target_specs=result.specifications,
                region=region,
                all_skus=all_skus,
                max_results=max_alternatives,
            )
        
        return result
    
    def _find_similar_skus(
        self,
        target_sku: Any,
        target_specs: SKUSpecifications,
        region: str,
        all_skus: List[Any],
        max_results: int = 5,
    ) -> List[AlternativeSKU]:
        """Find similar available SKUs when target is constrained."""
        alternatives = []
        target_caps = target_specs.raw_capabilities
        
        for sku in all_skus:
            # Skip the target SKU itself
            if sku.name == target_sku.name:
                continue
            
            # Check if available in region
            sku_locations = [loc.lower() for loc in (sku.locations or [])]
            if region.lower() not in sku_locations:
                continue
            
            # Check for restrictions
            is_restricted = False
            for restriction in (sku.restrictions or []):
                restriction_info = getattr(restriction, 'restriction_info', None)
                if restriction_info:
                    restricted_locs = [
                        loc.lower() for loc in (restriction_info.locations or [])
                    ]
                    if region.lower() in restricted_locs:
                        is_restricted = True
                        break
            
            if is_restricted:
                continue
            
            # Parse specifications
            alt_specs = SKUSpecifications.from_capabilities(
                getattr(sku, 'capabilities', [])
            )
            
            # Calculate similarity
            similarity = self._calculate_similarity(target_caps, alt_specs.raw_capabilities)
            
            # Only include if reasonably similar (>= 60%)
            if similarity >= 60:
                # Get available zones
                zones = []
                for loc_info in (getattr(sku, 'location_info', []) or []):
                    if hasattr(loc_info, 'location'):
                        if loc_info.location.lower() == region.lower():
                            zones = list(loc_info.zones or [])
                            break
                
                alternatives.append(AlternativeSKU(
                    name=sku.name,
                    family=sku.family or "",
                    vcpus=alt_specs.vcpus,
                    memory_gb=alt_specs.memory_gb,
                    similarity_score=similarity,
                    available_zones=zones,
                    specifications=alt_specs,
                ))
        
        # Sort by similarity (descending) and return top N
        alternatives.sort(key=lambda x: x.similarity_score, reverse=True)
        return alternatives[:max_results]
    
    def _calculate_similarity(
        self,
        specs1: Dict[str, str],
        specs2: Dict[str, str],
    ) -> int:
        """
        Calculate similarity percentage between two SKU specifications.
        
        Uses key specifications like vCPUs, memory, premium IO support.
        """
        matches = 0
        total = 0
        
        for key in self.SIMILARITY_KEYS:
            if key in specs1 and key in specs2:
                total += 1
                if specs1[key] == specs2[key]:
                    matches += 1
        
        if total == 0:
            return 0
        
        return int((matches / total) * 100)
    
    def check_multiple_skus(
        self,
        sku_names: List[str],
        region: str,
        check_zones: bool = True,
        find_alternatives: bool = True,
    ) -> List[SKUAvailabilityResult]:
        """
        Check availability of multiple SKUs in a region.
        
        Args:
            sku_names: List of SKU names to check
            region: Azure region
            check_zones: Whether to check per-zone availability
            find_alternatives: Whether to find alternatives for constrained SKUs
            
        Returns:
            List of availability results
        """
        results = []
        
        for sku_name in sku_names:
            result = self.check_sku_availability(
                sku_name=sku_name,
                region=region,
                check_zones=check_zones,
                find_alternatives=find_alternatives,
            )
            results.append(result)
        
        return results
    
    def check_sku_across_regions(
        self,
        sku_name: str,
        regions: List[str],
        check_zones: bool = True,
    ) -> Dict[str, SKUAvailabilityResult]:
        """
        Check a SKU's availability across multiple regions.
        
        Args:
            sku_name: The SKU to check
            regions: List of regions to check
            check_zones: Whether to check per-zone availability
            
        Returns:
            Dictionary mapping region to availability result
        """
        results = {}
        
        for region in regions:
            result = self.check_sku_availability(
                sku_name=sku_name,
                region=region,
                check_zones=check_zones,
                find_alternatives=False,  # Don't find alternatives for multi-region check
            )
            results[region] = result
        
        return results


def display_availability_result(
    result: SKUAvailabilityResult,
    show_specs: bool = True,
    show_alternatives: bool = True,
) -> None:
    """Display availability result with rich formatting."""
    # Header
    status_color = "green" if result.is_available else "red"
    status_text = "AVAILABLE" if result.is_available else "NOT AVAILABLE"
    
    header = f"""[bold]SKU Availability Check[/bold]
    
[bold]SKU:[/bold] {result.sku_name}
[bold]Region:[/bold] {result.region}
[bold]Status:[/bold] [{status_color}]{status_text}[/{status_color}]
[bold]Subscription:[/bold] {result.subscription_name} ({result.subscription_id})
[bold]Checked:[/bold] {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"""
    
    if result.restriction_reason:
        header += f"\n[bold]Restriction:[/bold] [red]{result.restriction_reason}[/red]"
    
    console.print(Panel(header, title="🔍 SKU Availability", border_style="blue"))
    
    # Zone availability
    if result.available_zones or result.zone_details:
        console.print("\n[bold cyan]📍 Zone Availability[/bold cyan]")
        
        zone_table = Table(box=box.ROUNDED)
        zone_table.add_column("Zone", style="cyan")
        zone_table.add_column("Available", justify="center")
        zone_table.add_column("Capacity Status")
        
        # Add placement score column if we have scores
        if result.zone_placement_scores:
            zone_table.add_column("Placement Score", justify="center")
        
        if result.zone_details:
            for zone, details in sorted(result.zone_details.items()):
                avail_icon = "✅" if details.is_available else "❌"
                status_color = "green" if details.capacity_status == "Available" else "yellow"
                
                row_data = [
                    zone,
                    avail_icon,
                    f"[{status_color}]{details.capacity_status}[/{status_color}]",
                ]
                
                # Add placement score if available
                if result.zone_placement_scores:
                    score = result.zone_placement_scores.get(zone, "Unknown")
                    score_color = "green" if score == "High" else "yellow" if score == "Medium" else "red" if score == "Low" else "dim"
                    row_data.append(f"[{score_color}]{score}[/{score_color}]")
                
                zone_table.add_row(*row_data)
        elif result.available_zones:
            for zone in sorted(result.available_zones):
                row_data = [zone, "✅", "[green]Available[/green]"]
                if result.zone_placement_scores:
                    score = result.zone_placement_scores.get(zone, "Unknown")
                    score_color = "green" if score == "High" else "yellow" if score == "Medium" else "red" if score == "Low" else "dim"
                    row_data.append(f"[{score_color}]{score}[/{score_color}]")
                zone_table.add_row(*row_data)
        
        if not result.available_zones and not result.zone_details:
            console.print("  [dim]No zone information available[/dim]")
        else:
            console.print(zone_table)
    
    # Regional Placement Score (if not zonal)
    if result.placement_score != "Unknown" and not result.zone_placement_scores:
        score_color = "green" if result.placement_score == "High" else "yellow" if result.placement_score == "Medium" else "red" if result.placement_score == "Low" else "dim"
        console.print(f"\n[bold]🎯 Spot Placement Score:[/bold] [{score_color}]{result.placement_score}[/{score_color}]")
    
    # Specifications
    if show_specs and result.specifications:
        console.print("\n[bold cyan]📋 SKU Specifications[/bold cyan]")
        
        specs = result.specifications
        specs_table = Table(box=box.ROUNDED, show_header=False)
        specs_table.add_column("Property", style="dim")
        specs_table.add_column("Value")
        
        specs_table.add_row("vCPUs", str(specs.vcpus))
        specs_table.add_row("Memory", f"{specs.memory_gb} GB")
        specs_table.add_row("Max Data Disks", str(specs.max_data_disks))
        specs_table.add_row("Premium Storage", "✅" if specs.premium_io else "❌")
        specs_table.add_row("Accelerated Networking", "✅" if specs.accelerated_networking else "❌")
        specs_table.add_row("Encryption at Host", "✅" if specs.encryption_at_host else "❌")
        specs_table.add_row("Ultra SSD", "✅" if specs.ultra_ssd_available else "❌")
        specs_table.add_row("Hyper-V Generations", specs.hyper_v_generations or "N/A")
        specs_table.add_row("CPU Architecture", specs.cpu_architecture)
        
        console.print(specs_table)
    
    # Alternative SKUs
    if show_alternatives and result.alternative_skus:
        console.print("\n[bold cyan]🔄 Alternative SKUs (Available)[/bold cyan]")
        
        alt_table = Table(box=box.ROUNDED)
        alt_table.add_column("SKU Name", style="green")
        alt_table.add_column("vCPUs", justify="center")
        alt_table.add_column("Memory", justify="center")
        alt_table.add_column("Family")
        alt_table.add_column("Similarity", justify="center")
        alt_table.add_column("Zones")
        
        for alt in result.alternative_skus:
            similarity_color = "green" if alt.similarity_score >= 80 else "yellow"
            alt_table.add_row(
                alt.name,
                str(alt.vcpus),
                f"{alt.memory_gb} GB",
                alt.family,
                f"[{similarity_color}]{alt.similarity_score}%[/{similarity_color}]",
                ", ".join(alt.available_zones) if alt.available_zones else "All",
            )
        
        console.print(alt_table)
        console.print("\n[dim]💡 Alternatives sorted by specification similarity[/dim]")


def display_multi_region_results(
    sku_name: str,
    results: Dict[str, SKUAvailabilityResult],
) -> None:
    """Display availability results across multiple regions."""
    console.print(Panel(
        f"[bold]SKU:[/bold] {sku_name}\n[bold]Regions Checked:[/bold] {len(results)}",
        title="🌍 Multi-Region Availability",
        border_style="blue",
    ))
    
    table = Table(box=box.ROUNDED)
    table.add_column("Region", style="cyan")
    table.add_column("Available", justify="center")
    table.add_column("Zones", justify="center")
    table.add_column("Restriction")
    
    for region, result in sorted(results.items()):
        avail_icon = "✅" if result.is_available else "❌"
        zones = ", ".join(result.available_zones) if result.available_zones else "-"
        restriction = result.restriction_reason or "-"
        
        table.add_row(
            region,
            avail_icon,
            zones,
            f"[red]{restriction}[/red]" if restriction != "-" else restriction,
        )
    
    console.print(table)
    
    # Summary
    available_count = sum(1 for r in results.values() if r.is_available)
    console.print(f"\n[bold]Summary:[/bold] {available_count}/{len(results)} regions available")
