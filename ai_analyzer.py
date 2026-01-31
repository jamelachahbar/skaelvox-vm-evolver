"""
AI-powered analysis module for VM rightsizing recommendations.
Uses Claude API for intelligent analysis and recommendations.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
import re
import time
import threading
from rich.console import Console

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from openai import AzureOpenAI
    AZURE_OPENAI_AVAILABLE = True
except ImportError:
    AZURE_OPENAI_AVAILABLE = False

try:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    AZURE_IDENTITY_AVAILABLE = True
except ImportError:
    AZURE_IDENTITY_AVAILABLE = False

from azure_client import VMInfo, AdvisorRecommendation, SKUInfo


console = Console()


@dataclass
class AIRecommendation:
    """AI-generated recommendation for a VM."""
    vm_name: str
    current_sku: str
    recommended_sku: str
    confidence: str  # High, Medium, Low
    reasoning: str
    estimated_monthly_savings: float
    risk_assessment: str
    migration_complexity: str  # Low, Medium, High
    recommended_actions: List[str]
    # Enhanced decision support
    decision_summary: str = ""  # Clear "do this because..." statement
    options: List[Dict[str, Any]] = None  # Ranked alternatives with trade-offs
    workload_insight: str = ""  # What the AI inferred about the workload
    quick_win: bool = False  # True if low risk + high savings
    requires_validation: List[str] = None  # Things to verify before implementing
    
    def __post_init__(self):
        if self.options is None:
            self.options = []
        if self.requires_validation is None:
            self.requires_validation = []


class AIAnalyzer:
    """AI-powered analyzer for VM rightsizing."""

    SYSTEM_PROMPT = (
        "You are an Azure FinOps expert. Always respond with valid JSON only—no markdown, "
        "no commentary outside the JSON object. Ensure every response is a single JSON object."
    )

    ANALYSIS_PROMPT = """You are an Azure FinOps expert helping a customer make the BEST decision about VM rightsizing.
Your job is not just to recommend—it's to help them understand trade-offs and confidently choose.

## Current VM Information
{vm_data}

## Available SKU Options  
{sku_options}

## Azure Advisor Recommendations
{advisor_recs}

## Pricing Data
{pricing_data}

## Your Task
Analyze this data and provide a DECISION-FOCUSED recommendation. Help the user understand:
1. What should they do and WHY (not just what's cheapest)
2. What are the trade-offs between options
3. What could go wrong and how to mitigate it
4. Is this a "quick win" (low risk, easy, good savings) or does it need careful planning?

Provide a JSON response:
{{
    "decision_summary": "One clear sentence: 'You should [ACTION] because [REASON]'",
    "recommended_sku": "SKU name",
    "confidence": "High/Medium/Low",
    "workload_insight": "What you inferred about this workload from the metrics (e.g., 'This appears to be a lightly-used dev/test VM based on low CPU and memory utilization')",
    "quick_win": true/false,
    "reasoning": "Detailed explanation of why this is the best choice",
    "estimated_monthly_savings_usd": number,
    "options": [
        {{
            "rank": 1,
            "sku": "SKU name",
            "monthly_cost": number,
            "savings_vs_current": number,
            "best_for": "When to choose this option",
            "trade_offs": "What you give up",
            "risk_level": "Low/Medium/High"
        }},
        {{
            "rank": 2,
            "sku": "Alternative SKU",
            "monthly_cost": number,
            "savings_vs_current": number,
            "best_for": "When this is better",
            "trade_offs": "What you give up",
            "risk_level": "Low/Medium/High"
        }}
    ],
    "risk_assessment": "What could go wrong and likelihood",
    "requires_validation": ["List of things to verify before implementing, e.g., 'Confirm application can handle 2 vCPUs during peak'"],
    "migration_complexity": "Low/Medium/High",
    "migration_steps": ["Step 1", "Step 2"],
    "recommended_actions": ["Immediate action 1", "Follow-up action 2"],
    "reserved_instance_advice": "Should they consider RIs? 1-year or 3-year?",
    "dont_do_this_if": "Scenarios where this recommendation would be wrong"
}}

## Consider
- Disk IOPS requirements: if the VM has high avg_disk_iops, ensure the target SKU supports the necessary throughput.
- Network throughput: factor in avg_network_in and avg_network_out when the workload is network-intensive.
- Data disk count: the target SKU must support at least as many data disks as currently attached.
- Resource tags: use environment/team/application tags to infer criticality and risk tolerance.

## Decision Framework
- **Quick Win**: Low risk + Low complexity + >20% savings = recommend immediately
- **Needs Review**: Medium risk OR production workload = validate with app owner first
- **Proceed with Caution**: High risk OR critical system = pilot test, have rollback plan
- **Consider Alternatives**: If savings <10%, maybe not worth the effort

Be opinionated! Give a clear recommendation, not just options."""

    RANKING_PROMPT = """You are an Azure FinOps expert. Rank the following VM SKU options for the workload described.

Workload Profile:
{workload_profile}

SKU Options with Pricing:
{sku_list}

Provide a JSON response ranking SKUs:
{{
    "rankings": [
        {{
            "rank": 1,
            "sku": "SKU name",
            "score": 85,
            "monthly_cost_usd": number,
            "strengths": ["..."],
            "weaknesses": ["..."],
            "best_for": "Use case description"
        }}
    ],
    "recommendation_summary": "Overall recommendation text",
    "considerations": ["Important factors to consider"]
}}

Ranking criteria (weighted):
- Price/performance ratio (35%)
- Generation (newer = better) (20%)
- Feature alignment (20%)
- Right-sizing fit (25%)
"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        provider: str = "anthropic",
        azure_endpoint: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        azure_api_version: str = "2024-02-15-preview",
    ):
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.client = None
        self.azure_deployment = azure_deployment
        self._semaphore = threading.Semaphore(5)
        
        if provider == "azure_openai" and azure_endpoint and azure_deployment:
            if AZURE_OPENAI_AVAILABLE and AZURE_IDENTITY_AVAILABLE:
                # Use DefaultAzureCredential for Azure OpenAI
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                )
                self.client = AzureOpenAI(
                    azure_endpoint=azure_endpoint,
                    azure_ad_token_provider=token_provider,
                    api_version=azure_api_version,
                )
                self.provider = "azure_openai"
        elif api_key and ANTHROPIC_AVAILABLE:
            self.client = anthropic.Anthropic(api_key=api_key)
            self.provider = "anthropic"
    
    def is_available(self) -> bool:
        """Check if AI analysis is available."""
        return self.client is not None
    
    def analyze_vm(
        self,
        vm: VMInfo,
        available_skus: List[SKUInfo],
        advisor_recs: List[AdvisorRecommendation],
        pricing_data: Dict[str, float],
    ) -> Optional[AIRecommendation]:
        """Analyze a single VM and provide AI-powered recommendations."""
        if not self.is_available():
            return None
        
        # Prepare VM data with rich context for better decision making
        vm_data = {
            "name": vm.name,
            "resource_group": vm.resource_group,
            "current_sku": vm.vm_size,
            "location": vm.location,
            "os_type": vm.os_type,
            "power_state": vm.power_state,
            "tags": vm.tags if vm.tags else {},
            "data_disk_count": getattr(vm, "data_disk_count", 0),
            "metrics": {
                "avg_cpu_percent": round(vm.avg_cpu, 2) if vm.avg_cpu else "N/A",
                "max_cpu_percent": round(vm.max_cpu, 2) if vm.max_cpu else "N/A",
                "avg_memory_percent": round(vm.avg_memory, 2) if vm.avg_memory else "N/A",
                "max_memory_percent": round(vm.max_memory, 2) if vm.max_memory else "N/A",
                "avg_disk_iops": round(vm.avg_disk_iops, 2) if getattr(vm, "avg_disk_iops", None) else "N/A",
                "avg_network_in": round(vm.avg_network_in, 2) if getattr(vm, "avg_network_in", None) else "N/A",
                "avg_network_out": round(vm.avg_network_out, 2) if getattr(vm, "avg_network_out", None) else "N/A",
                "data_points_available": "Yes" if vm.avg_cpu else "No - VM may be new or stopped",
            },
            "current_monthly_cost": round(vm.current_price_monthly, 2) if vm.current_price_monthly else "Unknown",
            # Inferred context clues for AI
            "context_hints": {
                "likely_environment": self._infer_environment(vm),
                "naming_pattern": self._analyze_name(vm.name),
            }
        }
        
        # Prepare SKU options (top 10 by relevance)
        sku_options = []
        for sku in available_skus[:20]:
            sku_price = pricing_data.get(sku.name, 0)
            sku_options.append({
                "name": sku.name,
                "vcpus": sku.vcpus,
                "memory_gb": sku.memory_gb,
                "generation": sku.generation,
                "features": sku.features,
                "hourly_price": round(sku_price, 4) if sku_price else "Unknown",
                "monthly_price": round(sku_price * 730, 2) if sku_price else "Unknown",
            })
        
        # Prepare advisor recommendations
        relevant_recs = [r for r in advisor_recs if r.vm_name == vm.name]
        advisor_data = []
        for rec in relevant_recs:
            advisor_data.append({
                "problem": rec.problem,
                "solution": rec.solution,
                "recommended_sku": rec.recommended_sku,
                "estimated_savings": rec.estimated_savings,
            })
        
        # Prepare pricing data summary
        pricing_summary = {
            "current_region": vm.location,
            "current_sku_price": pricing_data.get(vm.vm_size, "Unknown"),
            "alternative_prices": {k: v for k, v in list(pricing_data.items())[:10]},
        }
        
        prompt = self.ANALYSIS_PROMPT.format(
            vm_data=json.dumps(vm_data, indent=2),
            sku_options=json.dumps(sku_options, indent=2),
            advisor_recs=json.dumps(advisor_data, indent=2) if advisor_data else "No Advisor recommendations available",
            pricing_data=json.dumps(pricing_summary, indent=2),
        )
        
        try:
            response_text = self._call_ai(prompt, max_tokens=2500)

            result = self._extract_json(response_text)
            if result is not None:
                result = self._validate_recommendation(result, vm.vm_size)

                return AIRecommendation(
                    vm_name=vm.name,
                    current_sku=vm.vm_size,
                    recommended_sku=result.get("recommended_sku", vm.vm_size),
                    confidence=result.get("confidence", "Medium"),
                    reasoning=result.get("reasoning", ""),
                    estimated_monthly_savings=result.get("estimated_monthly_savings_usd", 0),
                    risk_assessment=result.get("risk_assessment", ""),
                    migration_complexity=result.get("migration_complexity", "Medium"),
                    recommended_actions=result.get("recommended_actions", []),
                    # Enhanced decision support fields
                    decision_summary=result.get("decision_summary", ""),
                    options=result.get("options", []),
                    workload_insight=result.get("workload_insight", ""),
                    quick_win=result.get("quick_win", False),
                    requires_validation=result.get("requires_validation", []),
                )

        except Exception as e:
            console.print(f"[yellow]AI analysis failed for {vm.name}: {e}[/yellow]")

        return None
    
    def rank_skus(
        self,
        workload_profile: Dict[str, Any],
        sku_options: List[SKUInfo],
        pricing_data: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Rank SKUs for a given workload profile."""
        if not self.is_available():
            return []
        
        # Prepare SKU list with pricing
        sku_list = []
        for sku in sku_options:
            price = pricing_data.get(sku.name, 0)
            sku_list.append({
                "name": sku.name,
                "vcpus": sku.vcpus,
                "memory_gb": sku.memory_gb,
                "max_iops": sku.max_iops,
                "generation": sku.generation,
                "features": sku.features,
                "hourly_price": round(price, 4) if price else "Unknown",
                "monthly_price": round(price * 730, 2) if price else "Unknown",
            })
        
        prompt = self.RANKING_PROMPT.format(
            workload_profile=json.dumps(workload_profile, indent=2),
            sku_list=json.dumps(sku_list, indent=2),
        )
        
        try:
            response_text = self._call_ai(prompt, max_tokens=2000)
            result = self._extract_json(response_text)
            if result is not None:
                return result.get("rankings", [])

        except Exception as e:
            console.print(f"[yellow]AI ranking failed: {e}[/yellow]")

        return []
    
    def generate_summary_report(
        self,
        vms: List[VMInfo],
        recommendations: List[AIRecommendation],
        total_savings: float,
    ) -> str:
        """Generate an executive summary using AI."""
        if not self.is_available():
            return self._generate_basic_summary(vms, recommendations, total_savings)
        
        annual_savings = total_savings * 12
        complexity_low = sum(1 for r in recommendations if r.migration_complexity == "Low")
        complexity_med = sum(1 for r in recommendations if r.migration_complexity == "Medium")
        complexity_high = sum(1 for r in recommendations if r.migration_complexity == "High")

        summary_prompt = f"""Generate a concise executive summary for an Azure VM rightsizing analysis:

Total VMs Analyzed: {len(vms)}
VMs with Recommendations: {len(recommendations)}
Total Estimated Monthly Savings: ${total_savings:,.2f}
Total Estimated Annual Savings: ${annual_savings:,.2f}

Recommendations by confidence:
- High confidence: {sum(1 for r in recommendations if r.confidence == "High")}
- Medium confidence: {sum(1 for r in recommendations if r.confidence == "Medium")}
- Low confidence: {sum(1 for r in recommendations if r.confidence == "Low")}

Migration complexity breakdown:
- Low complexity: {complexity_low}
- Medium complexity: {complexity_med}
- High complexity: {complexity_high}

Top savings opportunities:
{self._format_top_savings(recommendations[:5])}

Provide a 2-3 paragraph executive summary suitable for presenting to management,
highlighting key findings, quick wins, annual savings potential, and recommended next steps.
"""
        
        try:
            return self._call_ai(summary_prompt, max_tokens=1000)
            
        except Exception:
            return self._generate_basic_summary(vms, recommendations, total_savings)
    
    # Patterns that indicate a transient/retryable error
    _TRANSIENT_PATTERNS = ("rate_limit", "overloaded", "timeout", "429", "500", "502", "503")

    def _call_ai(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call the AI provider with retry logic and concurrency limiting."""
        max_retries = 2
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                with self._semaphore:
                    return self._call_ai_inner(prompt, max_tokens)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_transient = any(p in error_str for p in self._TRANSIENT_PATTERNS)
                if not is_transient or attempt >= max_retries:
                    raise
                wait = 2 ** attempt  # 1s, 2s
                time.sleep(wait)

        # Should not reach here, but satisfy type checkers
        raise last_error  # type: ignore[misc]

    def _call_ai_inner(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call the configured AI provider and return the response text."""
        if self.provider == "azure_openai":
            response = self.client.chat.completions.create(
                model=self.azure_deployment,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        else:
            # Anthropic
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from AI response text.

        Tries three strategies:
        1. Direct ``json.loads`` on the full text.
        2. Regex extraction of a markdown code fence (```json ... ```).
        3. Brace-depth matching to locate the outermost ``{ ... }``.
        """
        # Strategy 1: direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Strategy 2: markdown code fence
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 3: brace-depth matching
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None

        return None

    @staticmethod
    def _validate_recommendation(result: Dict[str, Any], fallback_sku: str = "") -> Dict[str, Any]:
        """Normalize and validate fields in an AI recommendation result."""
        # Confidence
        confidence = str(result.get("confidence", "Medium")).capitalize()
        if confidence not in ("High", "Medium", "Low"):
            confidence = "Medium"
        result["confidence"] = confidence

        # Savings >= 0
        savings = result.get("estimated_monthly_savings_usd", 0)
        try:
            savings = float(savings)
        except (TypeError, ValueError):
            savings = 0.0
        result["estimated_monthly_savings_usd"] = max(savings, 0.0)

        # Migration complexity
        complexity = str(result.get("migration_complexity", "Medium")).capitalize()
        if complexity not in ("Low", "Medium", "High"):
            complexity = "Medium"
        result["migration_complexity"] = complexity

        # Recommended SKU non-empty
        if not result.get("recommended_sku"):
            result["recommended_sku"] = fallback_sku

        # Coerce recommended_actions to list
        actions = result.get("recommended_actions", [])
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            actions = []
        result["recommended_actions"] = actions

        return result

    def _format_top_savings(self, recommendations: List[AIRecommendation]) -> str:
        """Format top savings for the prompt."""
        lines = []
        for rec in recommendations:
            lines.append(
                f"- {rec.vm_name}: {rec.current_sku} -> {rec.recommended_sku} "
                f"(${rec.estimated_monthly_savings:,.2f}/month, "
                f"confidence={rec.confidence}, complexity={rec.migration_complexity})"
            )
        return "\n".join(lines) if lines else "No recommendations"
    
    def _generate_basic_summary(
        self,
        vms: List[VMInfo],
        recommendations: List[AIRecommendation],
        total_savings: float,
    ) -> str:
        """Generate a basic summary without AI."""
        return f"""
Azure VM Rightsizing Analysis Summary
=====================================

Total VMs Analyzed: {len(vms)}
VMs with Optimization Opportunities: {len(recommendations)}
Estimated Monthly Savings: ${total_savings:,.2f}
Estimated Annual Savings: ${total_savings * 12:,.2f}

Quick Wins (High Confidence): {sum(1 for r in recommendations if r.confidence == "High")}
Further Analysis Needed: {sum(1 for r in recommendations if r.confidence in ["Medium", "Low"])}

Recommended Next Steps:
1. Review high-confidence recommendations for immediate implementation
2. Validate medium-confidence recommendations with application owners
3. Consider reserved instances for consistently utilized VMs
4. Implement monitoring for newly rightsized VMs
"""

    def _infer_environment(self, vm: VMInfo) -> str:
        """Infer the likely environment (prod/dev/test) from VM metadata."""
        name_lower = vm.name.lower()
        rg_lower = vm.resource_group.lower()
        tags = {k.lower(): v.lower() for k, v in (vm.tags or {}).items()}
        
        # Check tags first (most reliable)
        env_tags = ['environment', 'env', 'stage', 'tier']
        for tag in env_tags:
            if tag in tags:
                val = tags[tag]
                if any(p in val for p in ['prod', 'production', 'prd']):
                    return "production"
                elif any(d in val for d in ['dev', 'development']):
                    return "development"
                elif any(t in val for t in ['test', 'qa', 'uat', 'staging']):
                    return "test/staging"
        
        # Check naming patterns
        combined = f"{name_lower} {rg_lower}"
        if any(p in combined for p in ['prod', 'prd', '-p-', '-prod-']):
            return "likely production (from name)"
        elif any(d in combined for d in ['dev', '-d-', '-dev-']):
            return "likely development (from name)"
        elif any(t in combined for t in ['test', 'qa', 'uat', 'stg', 'staging']):
            return "likely test/staging (from name)"
        
        return "unknown - treat as production for safety"
    
    def _analyze_name(self, name: str) -> str:
        """Extract insights from VM naming convention."""
        insights = []
        name_lower = name.lower()
        
        # Common patterns
        if any(x in name_lower for x in ['sql', 'db', 'database', 'mysql', 'postgres']):
            insights.append("database server")
        if any(x in name_lower for x in ['web', 'www', 'iis', 'nginx', 'apache']):
            insights.append("web server")
        if any(x in name_lower for x in ['app', 'api', 'svc', 'service']):
            insights.append("application server")
        if any(x in name_lower for x in ['jump', 'bastion', 'rdp', 'ssh']):
            insights.append("jump box/bastion")
        if any(x in name_lower for x in ['dc', 'domain', 'ad-', 'adds']):
            insights.append("domain controller")
        if any(x in name_lower for x in ['build', 'agent', 'runner', 'ci', 'cd']):
            insights.append("CI/CD agent")
        if any(x in name_lower for x in ['monitor', 'log', 'splunk', 'elk']):
            insights.append("monitoring/logging")
        
        return ", ".join(insights) if insights else "general purpose"
