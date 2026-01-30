"""
AI-powered analysis module for VM rightsizing recommendations.
Uses Claude API for intelligent analysis and recommendations.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
from rich.console import Console

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

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


class AIAnalyzer:
    """AI-powered analyzer for VM rightsizing."""
    
    ANALYSIS_PROMPT = """You are an Azure FinOps expert analyzing VM rightsizing opportunities. 
Analyze the following VM data and provide actionable recommendations.

Current VM Information:
{vm_data}

Available SKU Options:
{sku_options}

Advisor Recommendations (if any):
{advisor_recs}

Pricing Data:
{pricing_data}

Based on this data, provide a JSON response with the following structure:
{{
    "recommended_sku": "SKU name",
    "confidence": "High/Medium/Low",
    "reasoning": "Detailed explanation",
    "estimated_monthly_savings_usd": number,
    "risk_assessment": "Assessment of risks",
    "migration_complexity": "Low/Medium/High",
    "recommended_actions": ["action1", "action2"],
    "alternative_options": [
        {{"sku": "name", "monthly_cost": number, "pros": ["..."], "cons": ["..."]}}
    ],
    "performance_considerations": "Any performance notes",
    "cost_optimization_tips": ["tip1", "tip2"]
}}

Consider:
1. Performance requirements based on historical metrics
2. Cost savings potential
3. Generation upgrades (newer generations often cheaper and faster)
4. Regional pricing differences
5. Reserved instance potential if usage is consistent
6. Workload patterns (burstable vs consistent)
"""

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

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.client = None
        
        if api_key and ANTHROPIC_AVAILABLE:
            self.client = anthropic.Anthropic(api_key=api_key)
    
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
        
        # Prepare VM data
        vm_data = {
            "name": vm.name,
            "current_sku": vm.vm_size,
            "location": vm.location,
            "os_type": vm.os_type,
            "power_state": vm.power_state,
            "metrics": {
                "avg_cpu_percent": round(vm.avg_cpu, 2) if vm.avg_cpu else "N/A",
                "max_cpu_percent": round(vm.max_cpu, 2) if vm.max_cpu else "N/A",
                "avg_memory_percent": round(vm.avg_memory, 2) if vm.avg_memory else "N/A",
                "max_memory_percent": round(vm.max_memory, 2) if vm.max_memory else "N/A",
            },
            "current_monthly_cost": round(vm.current_price_monthly, 2) if vm.current_price_monthly else "Unknown",
        }
        
        # Prepare SKU options (top 10 by relevance)
        sku_options = []
        for sku in available_skus[:15]:
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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse JSON response
            response_text = response.content[0].text
            
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
                
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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = response.content[0].text
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
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
        
        summary_prompt = f"""Generate a concise executive summary for an Azure VM rightsizing analysis:

Total VMs Analyzed: {len(vms)}
VMs with Recommendations: {len(recommendations)}
Total Estimated Monthly Savings: ${total_savings:,.2f}

Recommendations by confidence:
- High confidence: {sum(1 for r in recommendations if r.confidence == "High")}
- Medium confidence: {sum(1 for r in recommendations if r.confidence == "Medium")}
- Low confidence: {sum(1 for r in recommendations if r.confidence == "Low")}

Top savings opportunities:
{self._format_top_savings(recommendations[:5])}

Provide a 2-3 paragraph executive summary suitable for presenting to management, 
highlighting key findings, quick wins, and recommended next steps.
"""
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": summary_prompt}]
            )
            return response.content[0].text
            
        except Exception:
            return self._generate_basic_summary(vms, recommendations, total_savings)
    
    def _format_top_savings(self, recommendations: List[AIRecommendation]) -> str:
        """Format top savings for the prompt."""
        lines = []
        for rec in recommendations:
            lines.append(
                f"- {rec.vm_name}: {rec.current_sku} → {rec.recommended_sku} "
                f"(${rec.estimated_monthly_savings:,.2f}/month)"
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
