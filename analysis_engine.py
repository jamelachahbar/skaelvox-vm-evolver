"""
Analysis engine for VM rightsizing.
Combines Azure client, pricing, and AI analysis for comprehensive recommendations.

Performance optimizations:
- Concurrent VM analysis using ThreadPoolExecutor
- Cached SKU and pricing data to reduce API calls
- Parallel metrics fetching
- Batched AI analysis requests
"""
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import threading
import re

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from azure_client import AzureClient, PricingClient, VMInfo, SKUInfo, AdvisorRecommendation
from ai_analyzer import AIAnalyzer, AIRecommendation
from config import VM_GENERATION_MAP, REGION_ALTERNATIVES, SKU_RANKING_WEIGHTS, Settings

# Import constraint validator (optional, graceful fallback)
try:
    from constraint_validator import ConstraintValidator, SKUValidationResult
    CONSTRAINT_VALIDATION_AVAILABLE = True
except ImportError:
    CONSTRAINT_VALIDATION_AVAILABLE = False


console = Console()


@dataclass
class RightsizingResult:
    """Complete rightsizing analysis result for a VM."""
    vm: VMInfo
    
    # Recommendations
    advisor_recommendation: Optional[AdvisorRecommendation] = None
    ai_recommendation: Optional[AIRecommendation] = None
    
    # Generation upgrade
    current_generation: str = ""
    recommended_generation_upgrade: Optional[str] = None
    generation_savings: float = 0.0
    
    # Regional alternatives
    cheaper_regions: List[Tuple[str, float, float]] = field(default_factory=list)  # (region, price, savings)
    
    # SKU rankings
    ranked_alternatives: List[Dict[str, Any]] = field(default_factory=list)
    
    # Constraint validation
    validated_alternatives: List[Dict[str, Any]] = field(default_factory=list)  # SKUs that passed validation
    constraint_issues: List[str] = field(default_factory=list)  # Issues found during validation
    quota_warnings: List[str] = field(default_factory=list)  # Quota-related warnings
    
    # Summary
    total_potential_savings: float = 0.0
    recommendation_type: str = ""  # "rightsize", "shutdown", "generation_upgrade", "region_move"
    priority: str = "Medium"  # High, Medium, Low
    deployment_feasible: bool = True  # Whether recommended SKU can actually be deployed


@dataclass
class AnalysisReport:
    """Complete analysis report."""
    timestamp: datetime
    subscription_id: str
    total_vms: int
    analyzed_vms: int
    
    results: List[RightsizingResult] = field(default_factory=list)
    
    # Summary statistics
    total_current_cost: float = 0.0
    total_potential_savings: float = 0.0
    vms_with_recommendations: int = 0
    
    # Breakdown
    shutdown_candidates: int = 0
    rightsize_candidates: int = 0
    generation_upgrade_candidates: int = 0
    region_move_candidates: int = 0
    
    # AI summary
    executive_summary: str = ""


class AnalysisEngine:
    """Main engine for VM rightsizing analysis with concurrent processing."""
    
    # Default concurrency settings
    DEFAULT_MAX_WORKERS = 10
    DEFAULT_AI_BATCH_SIZE = 5
    
    def __init__(
        self,
        azure_client: AzureClient,
        pricing_client: PricingClient,
        ai_analyzer: Optional[AIAnalyzer] = None,
        settings: Optional[Settings] = None,
        validate_constraints: bool = True,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ):
        self.azure_client = azure_client
        self.pricing_client = pricing_client
        self.ai_analyzer = ai_analyzer
        self.settings = settings or Settings()
        self.validate_constraints = validate_constraints
        self.max_workers = max_workers
        
        # Thread-safe caches
        self._sku_cache: Dict[str, List[SKUInfo]] = {}
        self._sku_cache_lock = threading.Lock()
        self._price_cache: Dict[str, float] = {}
        self._price_cache_lock = threading.Lock()
        
        # Initialize constraint validator if available and enabled
        self.constraint_validator = None
        if validate_constraints and CONSTRAINT_VALIDATION_AVAILABLE:
            self.constraint_validator = ConstraintValidator(azure_client)
            console.print("[green]✓ Constraint validation enabled[/green]")
        
        console.print(f"[green]✓ Concurrent analysis enabled (max {max_workers} workers)[/green]")
    
    def _get_cached_skus(self, location: str) -> List[SKUInfo]:
        """Get SKUs with thread-safe caching. Also populates the AzureClient memory cache."""
        with self._sku_cache_lock:
            if location not in self._sku_cache:
                skus = self.azure_client.get_available_skus(
                    location, include_restricted=False
                )
                self._sku_cache[location] = skus
                # Populate the AzureClient's memory cache for dynamic memory resolution
                self.azure_client.populate_memory_cache(skus)
            return self._sku_cache[location]
    
    def _get_cached_price(self, sku_name: str, location: str, os_type: str) -> Optional[float]:
        """Get price with thread-safe caching."""
        cache_key = f"{sku_name}:{location}:{os_type}"
        with self._price_cache_lock:
            if cache_key not in self._price_cache:
                price = self.pricing_client.get_price(sku_name, location, os_type)
                if price is not None:
                    self._price_cache[cache_key] = price
            return self._price_cache.get(cache_key)
    
    def _prefetch_pricing_data(self, vms: List[VMInfo], progress) -> None:
        """Pre-fetch pricing data for all VMs in parallel."""
        task = progress.add_task("[cyan]Pre-fetching pricing data...", total=len(vms))
        
        def fetch_price(vm: VMInfo):
            self._get_cached_price(vm.vm_size, vm.location, vm.os_type)
            return vm.name
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(fetch_price, vm): vm for vm in vms}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass
                progress.update(task, advance=1)
    
    def _prefetch_sku_data(self, locations: List[str], progress) -> None:
        """Pre-fetch SKU data for all locations in parallel."""
        unique_locations = list(set(locations))
        task = progress.add_task("[cyan]Pre-fetching SKU data...", total=len(unique_locations))
        
        def fetch_skus(location: str):
            self._get_cached_skus(location)
            return location
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(fetch_skus, loc): loc for loc in unique_locations}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass
                progress.update(task, advance=1)

    def analyze_subscription(
        self,
        resource_group: Optional[str] = None,
        include_metrics: bool = True,
        include_ai: bool = True,
    ) -> AnalysisReport:
        """Run complete analysis on subscription or resource group with concurrent processing."""
        report = AnalysisReport(
            timestamp=datetime.now(timezone.utc),
            subscription_id=self.azure_client.subscription_id,
            total_vms=0,
            analyzed_vms=0,
        )
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            
            # Step 1: List VMs
            task1 = progress.add_task("[cyan]Discovering VMs...", total=None)
            vms = self.azure_client.list_vms(resource_group)
            report.total_vms = len(vms)
            progress.update(task1, completed=True, total=1)
            
            if not vms:
                console.print("[yellow]No VMs found in the specified scope.[/yellow]")
                return report
            
            console.print(f"[green]Found {len(vms)} VMs[/green]")
            
            # Step 2: Get Advisor recommendations
            task2 = progress.add_task("[cyan]Fetching Advisor recommendations...", total=None)
            advisor_recs = self.azure_client.get_advisor_recommendations()
            progress.update(task2, completed=True, total=1)
            console.print(f"[green]Found {len(advisor_recs)} Advisor recommendations[/green]")
            
            # Step 3: Pre-fetch data in parallel (optimization)
            locations = [vm.location for vm in vms]
            self._prefetch_sku_data(locations, progress)
            self._prefetch_pricing_data(vms, progress)
            
            # Step 4: Analyze VMs concurrently using ThreadPoolExecutor
            task3 = progress.add_task("[cyan]Analyzing VMs...", total=len(vms))
            
            results_lock = threading.Lock()
            
            def analyze_vm_wrapper(vm: VMInfo) -> RightsizingResult:
                return self._analyze_vm(
                    vm=vm,
                    advisor_recs=advisor_recs,
                    include_metrics=include_metrics,
                    include_ai=include_ai,
                )
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_vm = {executor.submit(analyze_vm_wrapper, vm): vm for vm in vms}
                
                for future in as_completed(future_to_vm, timeout=300):  # 5 minute timeout per batch
                    vm = future_to_vm[future]
                    try:
                        result = future.result(timeout=60)  # 60 second timeout per VM
                        
                        with results_lock:
                            report.results.append(result)
                            
                            # Update costs
                            if vm.current_price_monthly:
                                report.total_current_cost += vm.current_price_monthly
                            
                            if result.total_potential_savings > 0:
                                report.total_potential_savings += result.total_potential_savings
                                report.vms_with_recommendations += 1
                                
                                # Categorize
                                if result.recommendation_type == "shutdown":
                                    report.shutdown_candidates += 1
                                elif result.recommendation_type == "rightsize":
                                    report.rightsize_candidates += 1
                                elif result.recommendation_type == "generation_upgrade":
                                    report.generation_upgrade_candidates += 1
                                elif result.recommendation_type == "region_move":
                                    report.region_move_candidates += 1
                            
                            report.analyzed_vms += 1
                    except TimeoutError:
                        console.print(f"[yellow]Warning: Timeout analyzing VM {vm.name}[/yellow]")
                    except Exception as e:
                        console.print(f"[yellow]Warning: Failed to analyze VM {vm.name}: {e}[/yellow]")
                    
                    progress.update(task3, advance=1)
            
            # Step 5: Generate AI summary
            if include_ai and self.ai_analyzer and self.ai_analyzer.is_available():
                task4 = progress.add_task("[cyan]Generating AI summary...", total=None)
                ai_recommendations = [r.ai_recommendation for r in report.results if r.ai_recommendation]
                report.executive_summary = self.ai_analyzer.generate_summary_report(
                    vms=vms,
                    recommendations=ai_recommendations,
                    total_savings=report.total_potential_savings,
                )
                progress.update(task4, completed=True, total=1)
        
        # Sort results by potential savings (highest first)
        report.results.sort(key=lambda r: r.total_potential_savings, reverse=True)
        
        return report
    
    def _analyze_vm(
        self,
        vm: VMInfo,
        advisor_recs: List[AdvisorRecommendation],
        include_metrics: bool = True,
        include_ai: bool = True,
    ) -> RightsizingResult:
        """Analyze a single VM (thread-safe, uses cached data)."""
        result = RightsizingResult(vm=vm)
        
        # Get current pricing (use cached version)
        current_price = self._get_cached_price(vm.vm_size, vm.location, vm.os_type)
        if current_price:
            vm.current_price_hourly = current_price
            vm.current_price_monthly = current_price * 730  # Average hours per month
        
        # Get performance metrics
        if include_metrics:
            self.azure_client.get_vm_metrics(vm, self.settings.lookback_days)
        
        # Check Advisor recommendations
        for rec in advisor_recs:
            if rec.vm_name.lower() == vm.name.lower():
                result.advisor_recommendation = rec
                break
        
        # Analyze generation upgrade potential
        self._analyze_generation_upgrade(result)
        
        # Analyze regional alternatives
        self._analyze_regional_alternatives(result)
        
        # Get available SKUs (use cached version) and rank them
        available_skus = self._get_cached_skus(vm.location)
        self._rank_sku_alternatives(result, available_skus)
        
        # AI analysis
        if include_ai and self.ai_analyzer and self.ai_analyzer.is_available():
            pricing_data = self._get_sku_pricing_cached(available_skus[:20], vm.location, vm.os_type)
            result.ai_recommendation = self.ai_analyzer.analyze_vm(
                vm=vm,
                available_skus=available_skus[:20],
                advisor_recs=advisor_recs,
                pricing_data=pricing_data,
            )
        
        # Determine recommendation type and priority
        self._determine_recommendation(result)
        
        return result
    
    def _get_sku_pricing_cached(
        self,
        skus: List[SKUInfo],
        location: str,
        os_type: str,
    ) -> Dict[str, float]:
        """Get pricing for multiple SKUs using cache."""
        pricing = {}
        for sku in skus:
            price = self._get_cached_price(sku.name, location, os_type)
            if price:
                pricing[sku.name] = price
        return pricing

    def _analyze_generation_upgrade(self, result: RightsizingResult):
        """Check for generation upgrade opportunities."""
        vm = result.vm
        current_sku = vm.vm_size
        
        # Determine current generation from SKU name
        result.current_generation = self._extract_generation(current_sku)
        
        # Check if there's a newer generation available
        for old_pattern, new_sku in VM_GENERATION_MAP.items():
            if current_sku.startswith(old_pattern) or current_sku == old_pattern:
                # Found a potential upgrade
                new_price = self._get_cached_price(new_sku, vm.location, vm.os_type)
                current_price = vm.current_price_monthly or 0
                
                if new_price:
                    new_monthly = new_price * 730
                    if new_monthly < current_price:
                        result.recommended_generation_upgrade = new_sku
                        result.generation_savings = current_price - new_monthly
                break
    
    def _extract_generation(self, sku_name: str) -> str:
        """Extract generation from SKU name.
        
        Azure VM naming convention: [Family]+[Subfamily]+[#vCPUs]+[Features]+[AcceleratorType]+[Version]
        Examples:
          - Standard_D4s_v5 -> v5
          - Standard_E8ds_v4 -> v4
          - Standard_B2s -> v1 (no version = first gen)
          - Standard_NC4as_T4_v3 -> v3 (GPU with accelerator type)
          - Standard_M48ds_1_v3 -> v3 (M-series with memory notation)
          - Standard_Bsv2 -> v2 (inline version for B-series)
          - Standard_Dpsv5 -> v5 (inline version for D-series ARM)
        """
        # Pattern 1: Standard_XX_v5, Standard_XXs_v4, etc. (most common)
        match = re.search(r'_v(\d+)$', sku_name)
        if match:
            return f"v{match.group(1)}"
        
        # Pattern 2: _v2, _v3 in the middle (e.g., NC4as_T4_v3, M48ds_1_v3)
        match = re.search(r'_v(\d+)_', sku_name)
        if match:
            return f"v{match.group(1)}"
        
        # Pattern 3: Inline version at end of SKU name (no underscore before version)
        # Examples: Standard_Bsv2, Standard_B2psv2, Standard_Dpsv5, Standard_Epsv5
        match = re.search(r'[a-z]v(\d+)$', sku_name, re.IGNORECASE)
        if match:
            return f"v{match.group(1)}"
        
        # Pattern 4: First generation (no version suffix)
        # Old D-series (DS, D1-D14), A-series, B-series without version, F-series without version
        if re.match(r'Standard_(DS|D[1-9]|A\d|B\d+[ms]*|F\d+s?)$', sku_name, re.IGNORECASE):
            return "v1"
        
        # Pattern 5: Check if there's any 'v' + digit pattern we might have missed
        match = re.search(r'v(\d+)', sku_name, re.IGNORECASE)
        if match:
            return f"v{match.group(1)}"
        
        # Default: treat as v1 for legacy SKUs without version
        return "v1"
    
    def _extract_generation_number(self, generation_or_sku: str) -> int:
        """Extract generation number from generation string or SKU name.
        
        Args:
            generation_or_sku: Either a generation string ('v5', 'V1,V2') or full SKU name
            
        Returns:
            Generation number (1-6), or 1 for unknown/legacy
        """
        # If it looks like a SKU name, extract generation from it
        if generation_or_sku.startswith("Standard_"):
            gen_str = self._extract_generation(generation_or_sku)
            match = re.search(r'v(\d+)', gen_str, re.IGNORECASE)
            if match:
                return int(match.group(1))
            return 1
        
        # Otherwise parse as generation string (v5, V1,V2, etc.)
        # For 'V1,V2' format (HyperVGenerations), take the highest
        matches = re.findall(r'v(\d+)', generation_or_sku, re.IGNORECASE)
        if matches:
            return max(int(m) for m in matches)
        
        return 1  # Default to v1 for unknown
    
    def _get_sku_version(self, sku_name: str) -> int:
        """Get the VM series version number from SKU name.
        
        This extracts the version from the SKU naming convention (v2, v3, v4, v5, v6).
        This is different from HyperV generation (V1, V2) which indicates boot type.
        """
        gen = self._extract_generation(sku_name)
        match = re.search(r'v(\d+)', gen, re.IGNORECASE)
        return int(match.group(1)) if match else 1
    
    def _extract_family(self, sku_name: str) -> str:
        """Extract VM family from SKU name.
        
        Azure VM families from the naming convention:
          - Single letter: D, E, F, M, L, N, H, A, B
          - Two letters for subfamilies: DC, EC, NC, ND, NV, HB, HC, HX
          
        Examples:
          - Standard_D8s_v5 -> D
          - Standard_E16ds_v4 -> E  
          - Standard_DC4s_v3 -> DC (confidential)
          - Standard_NC4as_T4_v3 -> NC (GPU compute)
          - Standard_NV16as_v4 -> NV (GPU visualization)
          - Standard_B2s -> B
        """
        # Pattern: Standard_<Family><optional-subfamily><size><features>
        match = re.match(r'Standard_([A-Z]+)', sku_name)
        if match:
            family_part = match.group(1)
            
            # Known two-letter families/subfamilies
            two_letter_families = {'DC', 'EC', 'NC', 'ND', 'NV', 'HB', 'HC', 'HX', 'FX', 'EB'}
            
            if len(family_part) >= 2 and family_part[:2] in two_letter_families:
                return family_part[:2]
            
            # Single letter family (most common)
            return family_part[0]
        
        return ""

    def _analyze_regional_alternatives(self, result: RightsizingResult):
        """Find cheaper regional alternatives."""
        vm = result.vm
        current_region = vm.location.lower().replace(" ", "")
        
        # Get alternative regions
        alt_regions = REGION_ALTERNATIVES.get(current_region, [])
        if not alt_regions:
            return
        
        current_price = vm.current_price_monthly or 0
        if current_price == 0:
            return
        
        # Get prices for alternative regions
        prices = self.pricing_client.get_vm_prices(vm.vm_size, alt_regions, vm.os_type)
        
        for region, hourly_price in prices.items():
            monthly_price = hourly_price * 730
            savings = current_price - monthly_price
            
            if savings > 0:
                result.cheaper_regions.append((region, monthly_price, savings))
        
        # Sort by savings (highest first)
        result.cheaper_regions.sort(key=lambda x: x[2], reverse=True)
    
    def _rank_sku_alternatives(
        self,
        result: RightsizingResult,
        available_skus: List[SKUInfo],
    ):
        """Rank alternative SKUs based on multiple factors."""
        vm = result.vm
        current_price = vm.current_price_monthly or 0
        
        # Filter to similar SKUs (within reasonable vCPU/memory range)
        current_sku_info = None
        for sku in available_skus:
            if sku.name == vm.vm_size:
                current_sku_info = sku
                break
        
        if not current_sku_info:
            return
        
        # Define acceptable ranges based on utilization
        cpu_factor = 1.0
        mem_factor = 1.0
        
        if vm.avg_cpu and vm.avg_cpu < self.settings.cpu_threshold_low:
            cpu_factor = 0.5  # Can reduce vCPUs
        elif vm.max_cpu and vm.max_cpu > self.settings.cpu_threshold_high:
            cpu_factor = 1.5  # May need more vCPUs
        
        min_vcpus = max(1, int(current_sku_info.vcpus * cpu_factor * 0.5))
        max_vcpus = int(current_sku_info.vcpus * cpu_factor * 1.5)
        min_memory = max(1, current_sku_info.memory_gb * mem_factor * 0.5)
        max_memory = current_sku_info.memory_gb * mem_factor * 1.5
        
        # Get required features from current SKU
        required_features = current_sku_info.features if current_sku_info.features else []
        
        # Filter and score SKUs
        candidates = []
        skipped_disk = 0
        skipped_network = 0
        skipped_family = 0
        skipped_generation = 0
        skipped_burstable = 0
        
        for sku in available_skus:
            if sku.name == vm.vm_size:
                continue
            
            # Check vCPU range
            if not (min_vcpus <= sku.vcpus <= max_vcpus):
                continue
            
            # Check memory range
            if not (min_memory <= sku.memory_gb <= max_memory):
                continue
            
            # Check disk requirements (default: enabled)
            if self.settings.check_disk_requirements:
                if sku.max_data_disks < vm.data_disk_count:
                    skipped_disk += 1
                    continue
            
            # Check network/NIC requirements (default: enabled)
            # Note: Most SKUs support multiple NICs, but we check max_network_bandwidth
            if self.settings.check_network_requirements:
                # Ensure SKU has reasonable network bandwidth (at least 1 Gbps for production)
                if sku.max_network_bandwidth_mbps > 0 and sku.max_network_bandwidth_mbps < 1000:
                    # Allow if current SKU also has low bandwidth
                    if current_sku_info.max_network_bandwidth_mbps >= 1000:
                        skipped_network += 1
                        continue
            
            # Check same family preference (optional)
            if self.settings.prefer_same_family:
                current_family = self._extract_family(vm.vm_size)
                sku_family = self._extract_family(sku.name)
                if current_family and sku_family and current_family != sku_family:
                    skipped_family += 1
                    continue
            
            # 🦎✨ Skælvox Mode - Adaptive Generation Evolution
            # The cosmic chameleon that seeks newer generations while gracefully adapting
            if self.settings.skaelvox_enabled:
                current_version = self._get_sku_version(vm.vm_size)
                sku_version = self._get_sku_version(sku.name)
                target_version = current_version + self.settings.skaelvox_leap
                
                # Calculate how close this SKU is to our target (used for scoring later)
                # For now, filter out SKUs that are older than current
                if sku_version < current_version:
                    skipped_generation += 1
                    continue
                
                # If fallback is disabled, strictly require the target version or higher
                if not self.settings.skaelvox_fallback:
                    if sku_version < target_version:
                        skipped_generation += 1
                        continue
            
            # Check burstable SKUs (B-series)
            if not self.settings.allow_burstable:
                if sku.name.startswith("Standard_B"):
                    skipped_burstable += 1
                    continue
            
            # Get price (use cached version)
            price = self._get_cached_price(sku.name, vm.location, vm.os_type)
            if not price:
                continue
            
            monthly_price = price * 730
            
            # Skip per-SKU constraint validation during ranking (too slow)
            # We validate only the top recommendations later
            is_valid = True
            validation_issues = []
            
            # Calculate score
            score = self._calculate_sku_score(
                sku=sku,
                current_sku=current_sku_info,
                monthly_price=monthly_price,
                current_price=current_price,
                vm=vm,
            )
            
            candidate = {
                "sku": sku.name,
                "vcpus": sku.vcpus,
                "memory_gb": sku.memory_gb,
                "generation": sku.generation,
                "features": sku.features,
                "monthly_price": round(monthly_price, 2),
                "savings": round(current_price - monthly_price, 2),
                "savings_percent": round((current_price - monthly_price) / current_price * 100, 1) if current_price > 0 else 0,
                "score": round(score, 2),
                "is_valid": is_valid,
                "validation_issues": validation_issues,
            }
            
            candidates.append(candidate)
        
        # Sort by score (highest first)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        # Store all ranked alternatives (top 10)
        result.ranked_alternatives = candidates[:10]
        
        # Validate only the top recommendation (if constraint validator enabled)
        if self.constraint_validator and result.ranked_alternatives:
            top_sku = result.ranked_alternatives[0]["sku"]
            try:
                validation = self.constraint_validator.validate_sku(
                    sku_name=top_sku,
                    location=vm.location,
                    required_vcpus=result.ranked_alternatives[0]["vcpus"],
                    required_features=required_features if required_features else None,
                )
                result.ranked_alternatives[0]["is_valid"] = validation.is_valid
                if not validation.is_valid:
                    for restriction in validation.restrictions:
                        result.ranked_alternatives[0]["validation_issues"].append(restriction.message)
                    result.constraint_issues.extend(result.ranked_alternatives[0]["validation_issues"])
                if validation.quota_info and validation.quota_info.usage_percent > 80:
                    warning = f"Quota warning for {top_sku}: {validation.quota_info.usage_percent:.1f}% used"
                    result.quota_warnings.append(warning)
            except Exception:
                pass  # Skip validation on error
        
        # Store only validated alternatives
        result.validated_alternatives = [c for c in candidates if c["is_valid"]][:10]
        
        # Check if top recommendation is valid
        if result.ranked_alternatives:
            top_choice = result.ranked_alternatives[0]
            result.deployment_feasible = top_choice.get("is_valid", True)
    
    def _calculate_sku_score(
        self,
        sku: SKUInfo,
        current_sku: SKUInfo,
        monthly_price: float,
        current_price: float,
        vm: VMInfo,
    ) -> float:
        """Calculate a weighted score for SKU ranking."""
        score = 0.0
        
        # Price score (0-100, lower price = higher score)
        if current_price > 0:
            price_ratio = monthly_price / current_price
            price_score = max(0, (2 - price_ratio) * 50)  # Score 0-100
            score += price_score * SKU_RANKING_WEIGHTS["price"]
        
        # Performance score (0-100, based on vCPU/memory fit)
        vcpu_ratio = sku.vcpus / current_sku.vcpus if current_sku.vcpus > 0 else 1
        mem_ratio = sku.memory_gb / current_sku.memory_gb if current_sku.memory_gb > 0 else 1
        
        # Penalize both over and under provisioning
        vcpu_score = max(0, 100 - abs(1 - vcpu_ratio) * 100)
        mem_score = max(0, 100 - abs(1 - mem_ratio) * 100)
        perf_score = (vcpu_score + mem_score) / 2
        score += perf_score * SKU_RANKING_WEIGHTS["performance"]
        
        # Generation score - enhanced for Skælvox Mode 🦎✨
        sku_version = self._get_sku_version(sku.name)
        
        if self.settings.skaelvox_enabled:
            # Skælvox scoring: prefer SKUs closest to target generation
            current_version = self._get_sku_version(vm.vm_size)
            target_version = current_version + self.settings.skaelvox_leap
            
            # Perfect match with target = 100, each step away = -15 points
            version_diff = abs(sku_version - target_version)
            gen_score = max(0, 100 - (version_diff * 15))
            
            # Bonus for being at or above target
            if sku_version >= target_version:
                gen_score = min(100, gen_score + 10)
        else:
            # Standard scoring based on absolute version
            gen_score = min(100, sku_version * 20)  # v5=100, v4=80, v3=60, v2=40, v1=20
        
        score += gen_score * SKU_RANKING_WEIGHTS["generation"]
        
        # Feature score (0-100)
        feature_score = 0
        if "PremiumStorage" in sku.features:
            feature_score += 30
        if "AcceleratedNetworking" in sku.features:
            feature_score += 30
        if "EphemeralOSDisk" in sku.features:
            feature_score += 20
        feature_score = min(100, feature_score)
        score += feature_score * SKU_RANKING_WEIGHTS["features"]
        
        return score
    
    def _get_sku_pricing(
        self,
        skus: List[SKUInfo],
        location: str,
        os_type: str,
    ) -> Dict[str, float]:
        """Get pricing for multiple SKUs."""
        pricing = {}
        for sku in skus:
            price = self.pricing_client.get_price(sku.name, location, os_type)
            if price:
                pricing[sku.name] = price
        return pricing
    
    def _determine_recommendation(self, result: RightsizingResult):
        """Determine the primary recommendation type and priority."""
        vm = result.vm
        
        # Check for shutdown candidate (very low utilization)
        if vm.avg_cpu is not None and vm.avg_cpu < 5 and vm.max_cpu is not None and vm.max_cpu < 10:
            result.recommendation_type = "shutdown"
            result.priority = "High"
            result.total_potential_savings = vm.current_price_monthly or 0
            return
        
        # Check for generation upgrade
        if result.generation_savings > 0:
            result.recommendation_type = "generation_upgrade"
            result.total_potential_savings = max(result.total_potential_savings, result.generation_savings)
        
        # Check Advisor recommendation
        if result.advisor_recommendation and result.advisor_recommendation.estimated_savings:
            if result.advisor_recommendation.estimated_savings > result.total_potential_savings:
                result.recommendation_type = "rightsize"
                result.total_potential_savings = result.advisor_recommendation.estimated_savings
        
        # Check AI recommendation
        if result.ai_recommendation:
            if result.ai_recommendation.estimated_monthly_savings > result.total_potential_savings:
                result.recommendation_type = "rightsize"
                result.total_potential_savings = result.ai_recommendation.estimated_monthly_savings
        
        # Check regional alternatives
        if result.cheaper_regions:
            best_region_savings = result.cheaper_regions[0][2]
            if best_region_savings > result.total_potential_savings:
                result.recommendation_type = "region_move"
                result.total_potential_savings = best_region_savings
        
        # Check ranked alternatives
        if result.ranked_alternatives:
            best_alt_savings = result.ranked_alternatives[0].get("savings", 0)
            if best_alt_savings > result.total_potential_savings:
                result.recommendation_type = "rightsize"
                result.total_potential_savings = best_alt_savings
        
        # Determine priority based on savings
        if result.total_potential_savings > 500:
            result.priority = "High"
        elif result.total_potential_savings > 100:
            result.priority = "Medium"
        else:
            result.priority = "Low"
