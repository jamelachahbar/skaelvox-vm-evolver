"""
Skælvox VM Evolver MCP Server

An MCP server that exposes Azure VM rightsizing tools for AI assistants.
"""
import asyncio
import json
import sys
import os
from pathlib import Path

# Add parent directory to path to import existing modules
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

from typing import Any, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import existing modules
from config import Settings
from azure_client import AzureClient, PricingClient
from analysis_engine import AnalysisEngine
from availability_checker import AvailabilityChecker
from constraint_validator import ConstraintValidator


# Create MCP server
server = Server("skaelvox-vm-evolver")


def get_settings() -> Settings:
    """Get settings from environment."""
    return Settings()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="analyze_subscription",
            description="Analyze all VMs in an Azure subscription for rightsizing opportunities. Returns cost savings recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure Subscription ID to analyze"
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Optional: Filter to specific resource group"
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include performance metrics in analysis (default: true)",
                        "default": True
                    }
                },
                "required": ["subscription_id"]
            }
        ),
        Tool(
            name="check_sku_availability",
            description="Check if a specific VM SKU is available in a region with zone information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure Subscription ID"
                    },
                    "sku": {
                        "type": "string",
                        "description": "VM SKU name (e.g., Standard_D4s_v5)"
                    },
                    "region": {
                        "type": "string",
                        "description": "Azure region (e.g., westeurope, swedencentral)"
                    }
                },
                "required": ["subscription_id", "sku", "region"]
            }
        ),
        Tool(
            name="get_vm_pricing",
            description="Get pricing information for VM SKUs in specified regions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "skus": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of VM SKU names"
                    },
                    "regions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Azure regions"
                    },
                    "os_type": {
                        "type": "string",
                        "enum": ["Linux", "Windows"],
                        "description": "Operating system type",
                        "default": "Linux"
                    }
                },
                "required": ["skus", "regions"]
            }
        ),
        Tool(
            name="rank_skus",
            description="Rank available VM SKUs by price-performance for given requirements.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure Subscription ID"
                    },
                    "vcpus": {
                        "type": "integer",
                        "description": "Minimum number of vCPUs required"
                    },
                    "memory_gb": {
                        "type": "number",
                        "description": "Minimum memory in GB required"
                    },
                    "region": {
                        "type": "string",
                        "description": "Azure region"
                    },
                    "os_type": {
                        "type": "string",
                        "enum": ["Linux", "Windows"],
                        "default": "Linux"
                    },
                    "top": {
                        "type": "integer",
                        "description": "Number of top results to return",
                        "default": 10
                    }
                },
                "required": ["subscription_id", "vcpus", "memory_gb", "region"]
            }
        ),
        Tool(
            name="check_quota",
            description="Check vCPU quota usage and availability for a VM family in a region.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure Subscription ID"
                    },
                    "region": {
                        "type": "string",
                        "description": "Azure region"
                    },
                    "family": {
                        "type": "string",
                        "description": "Optional: Filter to specific VM family (e.g., 'Dv5', 'Ev5')"
                    }
                },
                "required": ["subscription_id", "region"]
            }
        ),
        Tool(
            name="compare_regions",
            description="Compare VM pricing across different Azure regions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sku": {
                        "type": "string",
                        "description": "VM SKU to compare"
                    },
                    "regions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of regions to compare"
                    },
                    "os_type": {
                        "type": "string",
                        "enum": ["Linux", "Windows"],
                        "default": "Linux"
                    }
                },
                "required": ["sku", "regions"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "analyze_subscription":
            result = await analyze_subscription(
                subscription_id=arguments["subscription_id"],
                resource_group=arguments.get("resource_group"),
                include_metrics=arguments.get("include_metrics", True)
            )
        elif name == "check_sku_availability":
            result = await check_sku_availability(
                subscription_id=arguments["subscription_id"],
                sku=arguments["sku"],
                region=arguments["region"]
            )
        elif name == "get_vm_pricing":
            result = await get_vm_pricing(
                skus=arguments["skus"],
                regions=arguments["regions"],
                os_type=arguments.get("os_type", "Linux")
            )
        elif name == "rank_skus":
            result = await rank_skus(
                subscription_id=arguments["subscription_id"],
                vcpus=arguments["vcpus"],
                memory_gb=arguments["memory_gb"],
                region=arguments["region"],
                os_type=arguments.get("os_type", "Linux"),
                top=arguments.get("top", 10)
            )
        elif name == "check_quota":
            result = await check_quota(
                subscription_id=arguments["subscription_id"],
                region=arguments["region"],
                family=arguments.get("family")
            )
        elif name == "compare_regions":
            result = await compare_regions(
                sku=arguments["sku"],
                regions=arguments["regions"],
                os_type=arguments.get("os_type", "Linux")
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def analyze_subscription(
    subscription_id: str,
    resource_group: Optional[str] = None,
    include_metrics: bool = True
) -> dict:
    """Analyze VMs in a subscription for rightsizing."""
    settings = get_settings()
    settings.skaelvox_enabled = True
    settings.skaelvox_leap = 2
    
    azure_client = AzureClient(subscription_id=subscription_id)
    pricing_client = PricingClient()
    
    try:
        engine = AnalysisEngine(
            azure_client=azure_client,
            pricing_client=pricing_client,
            ai_analyzer=None,  # Skip AI for MCP to keep responses fast
            settings=settings,
            validate_constraints=True,
            check_placement_scores=False,
            max_workers=10
        )
        
        report = engine.analyze_subscription(
            resource_group=resource_group,
            include_metrics=include_metrics,
            include_ai=False
        )
        
        # Convert to serializable dict
        results = []
        for r in report.results[:20]:  # Limit to top 20
            results.append({
                "vm_name": r.vm.name,
                "resource_group": r.vm.resource_group,
                "current_sku": r.vm.vm_size,
                "recommended_sku": r.recommended_sku,
                "current_monthly_cost": round(r.current_monthly_cost, 2),
                "recommended_monthly_cost": round(r.recommended_monthly_cost, 2),
                "monthly_savings": round(r.total_potential_savings, 2),
                "priority": r.priority,
                "recommendation_type": r.recommendation_type,
                "avg_cpu": round(r.vm.avg_cpu, 1) if r.vm.avg_cpu else None,
                "avg_memory": round(r.vm.avg_memory, 1) if r.vm.avg_memory else None,
            })
        
        return {
            "subscription_id": subscription_id,
            "total_vms": report.total_vms,
            "vms_with_recommendations": report.vms_with_recommendations,
            "total_current_cost": round(report.total_current_cost, 2),
            "total_potential_savings": round(report.total_potential_savings, 2),
            "savings_percentage": round((report.total_potential_savings / report.total_current_cost * 100) if report.total_current_cost > 0 else 0, 1),
            "results": results
        }
    finally:
        pricing_client.close()


async def check_sku_availability(
    subscription_id: str,
    sku: str,
    region: str
) -> dict:
    """Check SKU availability in a region."""
    azure_client = AzureClient(subscription_id=subscription_id)
    checker = AvailabilityChecker(azure_client)
    
    result = checker.check_sku_availability(sku, region)
    
    return {
        "sku": sku,
        "region": region,
        "available": result.get("available", False),
        "zones": result.get("zones", []),
        "restrictions": result.get("restrictions", []),
        "reason_code": result.get("reason_code")
    }


async def get_vm_pricing(
    skus: list[str],
    regions: list[str],
    os_type: str = "Linux"
) -> dict:
    """Get pricing for SKUs across regions."""
    pricing_client = PricingClient()
    
    try:
        prices = pricing_client.get_vm_prices(skus, regions, os_type)
        
        result = {}
        for sku in skus:
            result[sku] = {}
            for region in regions:
                hourly = prices.get(f"{sku}_{region}", 0)
                result[sku][region] = {
                    "hourly": round(hourly, 4),
                    "monthly": round(hourly * 730, 2)
                }
        
        return {"prices": result, "os_type": os_type}
    finally:
        pricing_client.close()


async def rank_skus(
    subscription_id: str,
    vcpus: int,
    memory_gb: float,
    region: str,
    os_type: str = "Linux",
    top: int = 10
) -> dict:
    """Rank SKUs by price-performance."""
    azure_client = AzureClient(subscription_id=subscription_id)
    pricing_client = PricingClient()
    
    try:
        # Get available SKUs
        all_skus = azure_client.list_available_skus(region)
        
        # Filter by requirements
        matching = [
            s for s in all_skus
            if s.vcpus >= vcpus and s.memory_gb >= memory_gb
        ]
        
        # Get pricing
        sku_names = [s.name for s in matching[:50]]  # Limit for API
        prices = pricing_client.get_vm_prices(sku_names, [region], os_type)
        
        # Rank by price
        ranked = []
        for sku in matching:
            price = prices.get(f"{sku.name}_{region}", 0)
            if price > 0:
                ranked.append({
                    "sku": sku.name,
                    "vcpus": sku.vcpus,
                    "memory_gb": sku.memory_gb,
                    "hourly_price": round(price, 4),
                    "monthly_price": round(price * 730, 2),
                    "price_per_vcpu": round(price / sku.vcpus, 4) if sku.vcpus > 0 else 0
                })
        
        # Sort by price
        ranked.sort(key=lambda x: x["monthly_price"])
        
        return {
            "region": region,
            "requirements": {"vcpus": vcpus, "memory_gb": memory_gb},
            "ranked_skus": ranked[:top]
        }
    finally:
        pricing_client.close()


async def check_quota(
    subscription_id: str,
    region: str,
    family: Optional[str] = None
) -> dict:
    """Check vCPU quota in a region."""
    azure_client = AzureClient(subscription_id=subscription_id)
    validator = ConstraintValidator(azure_client)
    
    quotas = validator.get_quota_usage(region)
    
    result = []
    for q in quotas:
        if family and family.lower() not in q.get("name", "").lower():
            continue
        result.append({
            "name": q.get("name"),
            "used": q.get("currentValue", 0),
            "limit": q.get("limit", 0),
            "available": q.get("limit", 0) - q.get("currentValue", 0),
            "usage_percent": round(q.get("currentValue", 0) / q.get("limit", 1) * 100, 1) if q.get("limit", 0) > 0 else 0
        })
    
    return {
        "subscription_id": subscription_id,
        "region": region,
        "quotas": result[:20]  # Limit results
    }


async def compare_regions(
    sku: str,
    regions: list[str],
    os_type: str = "Linux"
) -> dict:
    """Compare SKU pricing across regions."""
    pricing_client = PricingClient()
    
    try:
        prices = pricing_client.get_vm_prices([sku], regions, os_type)
        
        comparison = []
        for region in regions:
            hourly = prices.get(f"{sku}_{region}", 0)
            comparison.append({
                "region": region,
                "hourly": round(hourly, 4),
                "monthly": round(hourly * 730, 2)
            })
        
        # Sort by price
        comparison.sort(key=lambda x: x["monthly"])
        
        # Calculate savings vs most expensive
        if comparison:
            max_price = max(c["monthly"] for c in comparison)
            for c in comparison:
                c["savings_vs_max"] = round(max_price - c["monthly"], 2)
        
        return {
            "sku": sku,
            "os_type": os_type,
            "regions": comparison
        }
    finally:
        pricing_client.close()


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
