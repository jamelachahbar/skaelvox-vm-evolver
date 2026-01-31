#!/usr/bin/env python3
"""
Azure VM Rightsizer CLI - Rich CLI tool for VM analysis and cost optimization.

Features:
- VM inventory and performance analysis
- Azure Advisor recommendations integration
- Generation upgrade recommendations (v3 → v5)
- Regional price comparison
- AI-powered analysis and recommendations
- SKU ranking and scoring
- Cost savings estimation

Usage:
    python main.py analyze --subscription <sub-id>
    python main.py compare-regions --vm <vm-name> --resource-group <rg>
    python main.py rank-skus --vcpus 4 --memory 16 --region westeurope
"""
import os
import sys
from typing import Optional
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.tree import Tree
from rich.columns import Columns
from rich.prompt import Prompt, IntPrompt, Confirm
from rich import box
from dotenv import load_dotenv

from config import Settings, VM_GENERATION_MAP, REGION_ALTERNATIVES
from azure_client import AzureClient, PricingClient, VMInfo, SKUInfo
from ai_analyzer import AIAnalyzer
from analysis_engine import AnalysisEngine, AnalysisReport, RightsizingResult

# Import constraint validator (optional)
try:
    from constraint_validator import (
        ConstraintValidator,
        create_quota_table,
        create_validation_table,
    )
    CONSTRAINT_VALIDATION_AVAILABLE = True
except ImportError:
    CONSTRAINT_VALIDATION_AVAILABLE = False


# Load environment variables
load_dotenv()

# Initialize
app = typer.Typer(
    name="azure-vm-rightsizer",
    help="🔧 Azure VM Rightsizing CLI - Analyze and optimize your Azure VM costs",
    add_completion=False,
)
console = Console()


def create_header():
    """Create a beautiful header for the CLI."""
    header = """
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                      ║
║  🦎  ███████╗██╗  ██╗ █████╗ ███████╗██╗    ██╗   ██╗ ██████╗ ██╗  ██╗  🦎          ║
║  ✨  ██╔════╝██║ ██╔╝██╔══██╗██╔════╝██║    ██║   ██║██╔═══██╗╚██╗██╔╝  ✨          ║
║  🌟  ███████╗█████╔╝ ███████║█████╗  ██║    ██║   ██║██║   ██║ ╚███╔╝   🌟          ║
║  💫  ╚════██║██╔═██╗ ██╔══██║██╔══╝  ██║    ╚██╗ ██╔╝██║   ██║ ██╔██╗   💫          ║
║  🦎  ███████║██║  ██╗██║  ██║███████╗███████╗╚████╔╝ ╚██████╔╝██╔╝ ██╗  🦎          ║
║  ✨  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝ ╚═══╝   ╚═════╝ ╚═╝  ╚═╝  ✨          ║
║                                                                                      ║
║           🚀  S K Æ L V O X   V M   E V O L V E R   C L I  🚀                       ║
║                                                                                      ║
║     🦎 Cosmic Chameleon • 💸 Cost Optimization • 🧬 Generation Evolution • 🧠 AI   ║
║                                                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
"""
    console.print(header, style="bold cyan")


def format_currency(value: float) -> str:
    """Format value as currency."""
    return f"${value:,.2f}"


def format_percent(value: float) -> str:
    """Format value as percentage."""
    return f"{value:.1f}%"


def get_priority_color(priority: str) -> str:
    """Get color for priority level."""
    colors = {
        "High": "red",
        "Medium": "yellow",
        "Low": "green",
    }
    return colors.get(priority, "white")


def get_confidence_color(confidence: str) -> str:
    """Get color for confidence level."""
    colors = {
        "High": "green",
        "Medium": "yellow",
        "Low": "red",
    }
    return colors.get(confidence, "white")


def create_summary_panel(report: AnalysisReport) -> Panel:
    """Create a summary panel for the analysis report."""
    savings_color = "green" if report.total_potential_savings > 0 else "white"
    
    content = f"""
[bold]Analysis Timestamp:[/bold] {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
[bold]Subscription ID:[/bold] {report.subscription_id}

[bold cyan]📊 VM Statistics[/bold cyan]
  • Total VMs Discovered: {report.total_vms}
  • VMs Analyzed: {report.analyzed_vms}
  • VMs with Recommendations: {report.vms_with_recommendations}

[bold cyan]💰 Cost Summary[/bold cyan]
  • Current Monthly Cost: {format_currency(report.total_current_cost)}
  • Potential Monthly Savings: [{savings_color}]{format_currency(report.total_potential_savings)}[/{savings_color}]
  • Potential Annual Savings: [{savings_color}]{format_currency(report.total_potential_savings * 12)}[/{savings_color}]
  • Savings Percentage: [{savings_color}]{format_percent(report.total_potential_savings / report.total_current_cost * 100) if report.total_current_cost > 0 else '0%'}[/{savings_color}]

[bold cyan]📋 Recommendation Breakdown[/bold cyan]
  • 🔴 Shutdown Candidates: {report.shutdown_candidates}
  • 📐 Rightsize Candidates: {report.rightsize_candidates}
  • ⬆️  Generation Upgrades: {report.generation_upgrade_candidates}
  • 🌍 Region Move Candidates: {report.region_move_candidates}
"""
    
    return Panel(
        content,
        title="[bold white]📈 Analysis Summary[/bold white]",
        border_style="blue",
        box=box.DOUBLE,
    )


def create_vm_table(results: list[RightsizingResult], limit: int = 20) -> Table:
    """Create a table showing VM analysis results."""
    table = Table(
        title="🖥️  VM Rightsizing Recommendations",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    
    table.add_column("VM Name", style="white", max_width=25)
    table.add_column("Resource Group", style="dim", max_width=20)
    table.add_column("Current SKU", style="yellow")
    table.add_column("Recommended", style="green")
    table.add_column("Type", style="cyan")
    table.add_column("Monthly Savings", justify="right", style="green")
    table.add_column("Priority", justify="center")
    table.add_column("Valid", justify="center")
    
    for result in results[:limit]:
        # Determine recommended SKU
        recommended = "-"
        if result.ai_recommendation:
            recommended = result.ai_recommendation.recommended_sku
        elif result.advisor_recommendation and result.advisor_recommendation.recommended_sku:
            recommended = result.advisor_recommendation.recommended_sku
        elif result.recommended_generation_upgrade:
            recommended = result.recommended_generation_upgrade
        elif result.ranked_alternatives:
            recommended = result.ranked_alternatives[0]["sku"]
        
        # Priority with color
        priority_color = get_priority_color(result.priority)
        priority_text = f"[{priority_color}]●[/{priority_color}] {result.priority}"
        
        # Savings
        savings_text = format_currency(result.total_potential_savings) if result.total_potential_savings > 0 else "-"
        
        # Validation status
        if result.deployment_feasible:
            valid_text = "[green]✅[/green]"
        elif result.constraint_issues:
            valid_text = "[red]⚠️[/red]"
        else:
            valid_text = "[dim]-[/dim]"
        
        table.add_row(
            result.vm.name,
            result.vm.resource_group[:18] + "..." if len(result.vm.resource_group) > 20 else result.vm.resource_group,
            result.vm.vm_size,
            recommended if recommended != result.vm.vm_size else "[dim]No change[/dim]",
            result.recommendation_type or "-",
            savings_text,
            priority_text,
            valid_text,
        )
    
    if len(results) > limit:
        table.add_row(
            f"[dim]... and {len(results) - limit} more VMs[/dim]",
            "", "", "", "", "", "", ""
        )
    
    return table


def create_detailed_result_panel(result: RightsizingResult) -> Panel:
    """Create a detailed panel for a single VM result."""
    vm = result.vm
    
    # Build content sections
    sections = []
    
    # VM Info
    vm_info = f"""[bold cyan]VM Information[/bold cyan]
  • Name: {vm.name}
  • Resource Group: {vm.resource_group}
  • Location: {vm.location}
  • Current SKU: {vm.vm_size}
  • OS Type: {vm.os_type}
  • Power State: {vm.power_state}
  • Current Monthly Cost: {format_currency(vm.current_price_monthly or 0)}
"""
    sections.append(vm_info)
    
    # Performance Metrics
    if vm.avg_cpu is not None or vm.avg_memory is not None:
        metrics = f"""[bold cyan]Performance Metrics (30-day avg)[/bold cyan]
  • Avg CPU: {format_percent(vm.avg_cpu) if vm.avg_cpu else 'N/A'}
  • Max CPU: {format_percent(vm.max_cpu) if vm.max_cpu else 'N/A'}
  • Avg Memory: {format_percent(vm.avg_memory) if vm.avg_memory else 'N/A'}
  • Max Memory: {format_percent(vm.max_memory) if vm.max_memory else 'N/A'}
"""
        sections.append(metrics)
    
    # Advisor Recommendation
    if result.advisor_recommendation:
        rec = result.advisor_recommendation
        advisor = f"""[bold cyan]Azure Advisor Recommendation[/bold cyan]
  • Problem: {rec.problem}
  • Solution: {rec.solution}
  • Recommended SKU: {rec.recommended_sku or 'N/A'}
  • Impact: {rec.impact}
"""
        sections.append(advisor)
    
    # AI Recommendation
    if result.ai_recommendation:
        ai_rec = result.ai_recommendation
        confidence_color = get_confidence_color(ai_rec.confidence)
        actions_text = ""
        if ai_rec.recommended_actions:
            actions_lines = "\n".join(f"    • {a}" for a in ai_rec.recommended_actions)
            actions_text = f"\n  [bold]Recommended Actions:[/bold]\n{actions_lines}\n"

        ai = f"""[bold cyan]🤖 AI-Powered Recommendation[/bold cyan]
  • Recommended SKU: [green]{ai_rec.recommended_sku}[/green]
  • Confidence: [{confidence_color}]{ai_rec.confidence}[/{confidence_color}]
  • Est. Monthly Savings: [green]{format_currency(ai_rec.estimated_monthly_savings)}[/green]
  • Migration Complexity: {ai_rec.migration_complexity}

  [bold]Reasoning:[/bold]
  {ai_rec.reasoning}

  [bold]Risk Assessment:[/bold]
  {ai_rec.risk_assessment}
{actions_text}"""
        sections.append(ai)
    
    # Generation Upgrade
    if result.recommended_generation_upgrade:
        gen = f"""[bold cyan]⬆️ Generation Upgrade Available[/bold cyan]
  • Current Generation: {result.current_generation}
  • Recommended SKU: [green]{result.recommended_generation_upgrade}[/green]
  • Monthly Savings: [green]{format_currency(result.generation_savings)}[/green]
"""
        sections.append(gen)
    
    # Regional Alternatives
    if result.cheaper_regions:
        regions = "[bold cyan]🌍 Cheaper Regions Available[/bold cyan]\n"
        for region, price, savings in result.cheaper_regions[:3]:
            regions += f"  • {region}: {format_currency(price)}/mo (save {format_currency(savings)})\n"
        sections.append(regions)
    
    # Top SKU Alternatives
    if result.ranked_alternatives:
        alts = "[bold cyan]📊 Top Alternative SKUs (by score)[/bold cyan]\n"
        for i, alt in enumerate(result.ranked_alternatives[:5], 1):
            valid_icon = "✅" if alt.get("is_valid", True) else "⚠️"
            alts += f"  {i}. {valid_icon} {alt['sku']} - Score: {alt['score']}, {format_currency(alt['monthly_price'])}/mo"
            if alt['savings'] > 0:
                alts += f" [green](save {format_currency(alt['savings'])})[/green]"
            alts += f"\n     {alt['vcpus']} vCPUs, {alt['memory_gb']}GB RAM, {alt['generation']}"
            if not alt.get("is_valid", True):
                issues = alt.get("validation_issues", [])
                if issues:
                    alts += f"\n     [red]⚠️ {issues[0]}[/red]"
            alts += "\n"
        sections.append(alts)
    
    # Constraint validation results
    if result.constraint_issues or result.quota_warnings:
        constraints = "[bold cyan]⚠️ Constraint Validation[/bold cyan]\n"
        
        if result.quota_warnings:
            constraints += "  [yellow]Quota Warnings:[/yellow]\n"
            for warning in result.quota_warnings[:3]:
                constraints += f"    • {warning}\n"
        
        if result.constraint_issues:
            constraints += "  [red]Constraint Issues:[/red]\n"
            for issue in result.constraint_issues[:3]:
                constraints += f"    • {issue}\n"
        
        if not result.deployment_feasible:
            constraints += "\n  [red bold]⚠️ Top recommendation may not be deployable![/red bold]\n"
            constraints += "  [dim]Consider using validated alternatives or request quota increase[/dim]\n"
        
        sections.append(constraints)
    
    content = "\n".join(sections)
    
    priority_color = get_priority_color(result.priority)
    title = f"[{priority_color}]●[/{priority_color}] {vm.name} - {result.recommendation_type.upper() if result.recommendation_type else 'ANALYSIS'}"
    
    return Panel(
        content,
        title=title,
        border_style=priority_color,
        box=box.ROUNDED,
    )


@app.command()
def analyze(
    subscription: Optional[str] = typer.Option(
        None, "--subscription", "-s",
        help="Azure Subscription ID (or set AZURE_SUBSCRIPTION_ID env var)",
    ),
    resource_group: Optional[str] = typer.Option(
        None, "--resource-group", "-g",
        help="Filter to specific resource group",
    ),
    no_metrics: bool = typer.Option(
        False, "--no-metrics",
        help="Skip performance metrics collection (faster)",
    ),
    no_ai: bool = typer.Option(
        False, "--no-ai",
        help="Skip AI-powered analysis",
    ),
    no_validation: bool = typer.Option(
        False, "--no-validation",
        help="Skip SKU constraint validation",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output file path (JSON format)",
    ),
    detailed: bool = typer.Option(
        False, "--detailed", "-d",
        help="Show detailed analysis for each VM",
    ),
    top: int = typer.Option(
        20, "--top", "-t",
        help="Number of top recommendations to show",
    ),
    workers: int = typer.Option(
        10, "--workers", "-w",
        help="Number of concurrent workers for parallel processing (default: 10)",
    ),
    # SKU Filtering Options
    skip_disk_check: bool = typer.Option(
        False, "--skip-disk-check",
        help="Skip checking if SKU supports current disk count",
    ),
    skip_network_check: bool = typer.Option(
        False, "--skip-network-check",
        help="Skip checking network bandwidth requirements",
    ),
    same_family: bool = typer.Option(
        False, "--same-family",
        help="Only recommend SKUs from the same family (e.g., D→D, E→E)",
    ),
    no_burstable: bool = typer.Option(
        False, "--no-burstable",
        help="Exclude burstable B-series SKUs from recommendations",
    ),
    # 🦎✨ Skælvox Mode - Adaptive Generation Evolution (enabled by default)
    no_evolve: bool = typer.Option(
        False, "--no-evolve", "--no-skaelvox",
        help="🦎 Disable Skælvox Mode: Skip automatic generation evolution",
    ),
    skaelvox_leap: int = typer.Option(
        2, "--skaelvox-leap", "--leap",
        help="🦎 Skælvox leap distance: How many generations to evolve forward (1-3)",
    ),
    no_fallback: bool = typer.Option(
        False, "--no-fallback",
        help="🦎 Skælvox strict mode: Don't fall back to older generations if target unavailable",
    ),
):
    """
    🔍 Analyze VMs for rightsizing opportunities.
    
    Performs comprehensive analysis including:
    - Performance metrics analysis
    - Azure Advisor recommendations
    - Generation upgrade opportunities (🦎 Skælvox Mode)
    - Regional price comparisons
    - AI-powered recommendations
    - SKU constraint validation (quota, zones, restrictions)
    
    🦎✨ SKÆLVOX MODE:
    Enable with --skaelvox to activate the cosmic chameleon that evolves your VMs
    to newer generations. It automatically detects each VM's current generation
    and seeks upgrades (default: 2 generations forward), gracefully falling back
    if the ideal generation isn't available.
    
    Example: A v3 VM with --skaelvox --leap 2 will prefer v5 SKUs, but accept v4 if v5 unavailable.
    """
    create_header()
    
    # Load settings
    settings = Settings()
    
    # Apply CLI overrides for SKU filtering
    settings.check_disk_requirements = not skip_disk_check
    settings.check_network_requirements = not skip_network_check
    settings.prefer_same_family = same_family
    settings.allow_burstable = not no_burstable
    
    # 🦎 Skælvox Mode configuration (enabled by default - the cosmic chameleon evolves your VMs!)
    settings.skaelvox_enabled = not no_evolve
    settings.skaelvox_leap = max(1, min(3, skaelvox_leap))  # Clamp to 1-3
    settings.skaelvox_fallback = not no_fallback
    
    # Get subscription ID
    sub_id = subscription or settings.azure_subscription_id
    if not sub_id:
        console.print("[red]Error: Subscription ID required. Use --subscription or set AZURE_SUBSCRIPTION_ID[/red]")
        raise typer.Exit(1)
    
    console.print(f"\n[bold]Starting analysis for subscription:[/bold] {sub_id}\n")
    
    try:
        # Initialize clients
        azure_client = AzureClient(
            subscription_id=sub_id,
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        pricing_client = PricingClient()
        
        # Initialize AI analyzer if enabled
        ai_analyzer = None
        if not no_ai:
            # Check which AI provider to use
            if settings.ai_provider == "azure_openai" and settings.azure_openai_endpoint:
                ai_analyzer = AIAnalyzer(
                    provider="azure_openai",
                    azure_endpoint=settings.azure_openai_endpoint,
                    azure_deployment=settings.azure_openai_deployment,
                    azure_api_version=settings.azure_openai_api_version,
                )
            elif settings.anthropic_api_key:
                ai_analyzer = AIAnalyzer(
                    api_key=settings.anthropic_api_key,
                    model=settings.ai_model,
                    provider="anthropic",
                )
            
            if ai_analyzer and ai_analyzer.is_available():
                provider_name = "Azure OpenAI" if settings.ai_provider == "azure_openai" else "Anthropic"
                console.print(f"[green]✓ AI analysis enabled ({provider_name})[/green]")
            elif ai_analyzer:
                console.print("[yellow]⚠ AI analysis not available (check credentials)[/yellow]")
                ai_analyzer = None
            else:
                console.print("[yellow]⚠ AI analysis disabled (configure AI_PROVIDER and credentials)[/yellow]")
        
        # 🦎✨ Skælvox Mode status
        if settings.skaelvox_enabled:
            fallback_text = "with fallback" if settings.skaelvox_fallback else "strict mode"
            console.print(f"[bold magenta]🦎✨ Skælvox Mode ACTIVE[/bold magenta] - Evolving VMs +{settings.skaelvox_leap} generations ({fallback_text})")
        
        # Create analysis engine with concurrent processing
        engine = AnalysisEngine(
            azure_client=azure_client,
            pricing_client=pricing_client,
            ai_analyzer=ai_analyzer,
            settings=settings,
            validate_constraints=not no_validation,
            max_workers=workers,
        )
        
        # Run analysis
        console.print()
        report = engine.analyze_subscription(
            resource_group=resource_group,
            include_metrics=not no_metrics,
            include_ai=not no_ai and ai_analyzer is not None,
        )
        
        # Display results
        console.print()
        console.print(create_summary_panel(report))
        console.print()
        
        if report.results:
            console.print(create_vm_table(report.results, limit=top))
            console.print()
            
            # Show detailed results if requested
            if detailed:
                console.print("\n[bold cyan]═══ Detailed Analysis ═══[/bold cyan]\n")
                for result in report.results[:top]:
                    if result.total_potential_savings > 0:
                        console.print(create_detailed_result_panel(result))
                        console.print()
        
        # Show executive summary if available
        if report.executive_summary:
            console.print(Panel(
                Markdown(report.executive_summary),
                title="[bold]🤖 AI Executive Summary[/bold]",
                border_style="magenta",
                box=box.DOUBLE,
            ))
        
        # Save to file if requested
        if output:
            import json
            
            output_data = {
                "timestamp": report.timestamp.isoformat(),
                "subscription_id": report.subscription_id,
                "summary": {
                    "total_vms": report.total_vms,
                    "analyzed_vms": report.analyzed_vms,
                    "vms_with_recommendations": report.vms_with_recommendations,
                    "total_current_cost": report.total_current_cost,
                    "total_potential_savings": report.total_potential_savings,
                },
                "results": [
                    {
                        "vm_name": r.vm.name,
                        "resource_group": r.vm.resource_group,
                        "current_sku": r.vm.vm_size,
                        "recommendation_type": r.recommendation_type,
                        "potential_savings": r.total_potential_savings,
                        "priority": r.priority,
                        "ranked_alternatives": r.ranked_alternatives[:5],
                    }
                    for r in report.results
                ],
            }
            
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2)
            
            console.print(f"\n[green]✓ Results saved to {output}[/green]")
        
        # Cleanup
        pricing_client.close()
        
    except Exception as e:
        console.print(f"\n[red]Error during analysis: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def compare_regions(
    vm_name: str = typer.Option(..., "--vm", "-v", help="VM name to analyze"),
    resource_group: str = typer.Option(..., "--resource-group", "-g", help="Resource group name"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
):
    """
    🌍 Compare VM pricing across different Azure regions.
    
    Shows potential savings by moving a VM to alternative regions.
    """
    create_header()
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        pricing_client = PricingClient()
        
        # Get VM info
        vms = azure_client.list_vms(resource_group)
        vm = next((v for v in vms if v.name.lower() == vm_name.lower()), None)
        
        if not vm:
            console.print(f"[red]VM '{vm_name}' not found in resource group '{resource_group}'[/red]")
            raise typer.Exit(1)
        
        # Get current price
        current_price = pricing_client.get_price(vm.vm_size, vm.location, vm.os_type)
        current_monthly = current_price * 730 if current_price else 0
        
        # Get alternative regions
        alt_regions = REGION_ALTERNATIVES.get(vm.location.lower().replace(" ", ""), [])
        
        if not alt_regions:
            console.print(f"[yellow]No alternative regions configured for {vm.location}[/yellow]")
            raise typer.Exit(0)
        
        # Get prices for all regions
        all_regions = [vm.location] + alt_regions
        prices = pricing_client.get_vm_prices(vm.vm_size, all_regions, vm.os_type)
        
        # Create comparison table
        table = Table(
            title=f"🌍 Regional Price Comparison for {vm_name} ({vm.vm_size})",
            box=box.ROUNDED,
        )
        
        table.add_column("Region", style="cyan")
        table.add_column("Hourly Price", justify="right")
        table.add_column("Monthly Price", justify="right")
        table.add_column("Monthly Savings", justify="right", style="green")
        table.add_column("Savings %", justify="right", style="green")
        
        # Sort by price
        sorted_regions = sorted(
            [(r, prices.get(r.lower().replace(" ", ""), 0)) for r in all_regions],
            key=lambda x: x[1] if x[1] > 0 else float('inf')
        )
        
        regions_with_price = 0
        regions_no_price = []
        
        for region, hourly in sorted_regions:
            if hourly == 0:
                regions_no_price.append(region)
                continue
            
            regions_with_price += 1
            monthly = hourly * 730
            savings = current_monthly - monthly
            savings_pct = (savings / current_monthly * 100) if current_monthly > 0 else 0
            
            is_current = region.lower().replace(" ", "") == vm.location.lower().replace(" ", "")
            
            # Highlight cheaper regions
            if savings > 0 and not is_current:
                region_display = f"[green]{region}[/green]"
                savings_display = f"[bold green]{format_currency(savings)}[/bold green]"
                pct_display = f"[bold green]{format_percent(savings_pct)}[/bold green]"
            elif is_current:
                region_display = f"[bold cyan]{region}[/bold cyan] ◄ current"
                savings_display = "-"
                pct_display = "-"
            else:
                region_display = region
                savings_display = f"[red]+{format_currency(-savings)}[/red]"
                pct_display = f"[red]+{format_percent(-savings_pct)}[/red]"
            
            table.add_row(
                region_display,
                format_currency(hourly),
                format_currency(monthly),
                savings_display,
                pct_display,
            )
        
        console.print()
        console.print(table)
        
        # Show regions without pricing
        if regions_no_price:
            console.print(f"\n[dim]⚠️  No pricing found for: {', '.join(regions_no_price)}[/dim]")
            console.print("[dim]   (SKU may not be available in those regions)[/dim]")
        
        # Show recommendation
        if regions_with_price > 1:
            cheapest = sorted_regions[0]
            if cheapest[1] > 0 and cheapest[0].lower() != vm.location.lower():
                monthly_savings = current_monthly - (cheapest[1] * 730)
                annual_savings = monthly_savings * 12
                console.print(f"\n[bold green]💡 Recommendation:[/bold green] Move to [cyan]{cheapest[0]}[/cyan] to save [bold green]{format_currency(monthly_savings)}/month[/bold green] ({format_currency(annual_savings)}/year)")
        
        pricing_client.close()
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def rank_skus(
    vcpus: int = typer.Option(..., "--vcpus", "-c", help="Required vCPUs"),
    memory: float = typer.Option(..., "--memory", "-m", help="Required memory in GB"),
    region: str = typer.Option("westeurope", "--region", "-r", help="Azure region"),
    os_type: str = typer.Option("Linux", "--os", help="OS type (Linux/Windows)"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    top: int = typer.Option(15, "--top", "-t", help="Number of SKUs to show"),
):
    """
    📊 Rank and compare VM SKUs for given requirements.
    
    Find the best SKU options based on vCPU, memory, and cost.
    """
    create_header()
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        pricing_client = PricingClient()
        
        console.print(f"\n[bold]Finding best SKUs for:[/bold] {vcpus} vCPUs, {memory}GB RAM in {region}\n")
        
        # Get available SKUs
        with console.status("[bold cyan]Fetching available SKUs..."):
            skus = azure_client.get_available_skus(region)
        
        # Filter SKUs matching requirements
        matching_skus = []
        for sku in skus:
            # Allow some flexibility in matching
            if sku.vcpus >= vcpus * 0.8 and sku.vcpus <= vcpus * 1.5:
                if sku.memory_gb >= memory * 0.8 and sku.memory_gb <= memory * 1.5:
                    price = pricing_client.get_price(sku.name, region, os_type)
                    if price:
                        matching_skus.append((sku, price))
        
        if not matching_skus:
            console.print("[yellow]No matching SKUs found. Try adjusting requirements.[/yellow]")
            raise typer.Exit(0)
        
        # Sort by price
        matching_skus.sort(key=lambda x: x[1])
        
        # Create table
        table = Table(
            title=f"📊 Top {top} SKUs for {vcpus} vCPUs / {memory}GB RAM",
            box=box.ROUNDED,
        )
        
        table.add_column("Rank", style="bold", justify="center")
        table.add_column("SKU Name", style="cyan")
        table.add_column("vCPUs", justify="center")
        table.add_column("Memory (GB)", justify="center")
        table.add_column("Generation")
        table.add_column("Features")
        table.add_column("Hourly", justify="right")
        table.add_column("Monthly", justify="right", style="green")
        
        for i, (sku, price) in enumerate(matching_skus[:top], 1):
            monthly = price * 730
            features = ", ".join(sku.features[:2]) if sku.features else "-"
            
            table.add_row(
                str(i),
                sku.name,
                str(sku.vcpus),
                str(sku.memory_gb),
                sku.generation,
                features,
                format_currency(price),
                format_currency(monthly),
            )
        
        console.print(table)
        
        # Show summary
        if matching_skus:
            cheapest = matching_skus[0]
            most_expensive = matching_skus[min(top-1, len(matching_skus)-1)]
            
            console.print(f"\n[bold cyan]💡 Summary:[/bold cyan]")
            console.print(f"  • Cheapest option: [green]{cheapest[0].name}[/green] at {format_currency(cheapest[1] * 730)}/month")
            console.print(f"  • Total options found: {len(matching_skus)}")
            
            # Recommend newest generation
            newest = [s for s in matching_skus if "v5" in s[0].generation]
            if newest:
                console.print(f"  • Recommended (newest gen): [green]{newest[0][0].name}[/green] at {format_currency(newest[0][1] * 730)}/month")
        
        pricing_client.close()
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def show_generations():
    """
    📜 Show VM generation upgrade paths.
    
    Display recommended upgrade paths from older to newer VM generations.
    """
    create_header()
    
    table = Table(
        title="⬆️  VM Generation Upgrade Paths",
        box=box.ROUNDED,
    )
    
    table.add_column("Old SKU Pattern", style="yellow")
    table.add_column("→", style="dim", justify="center")
    table.add_column("Recommended Upgrade", style="green")
    
    # Group by series
    d_series = [(k, v) for k, v in VM_GENERATION_MAP.items() if k.startswith("Standard_D")]
    e_series = [(k, v) for k, v in VM_GENERATION_MAP.items() if k.startswith("Standard_E")]
    f_series = [(k, v) for k, v in VM_GENERATION_MAP.items() if k.startswith("Standard_F")]
    b_series = [(k, v) for k, v in VM_GENERATION_MAP.items() if k.startswith("Standard_B")]
    a_series = [(k, v) for k, v in VM_GENERATION_MAP.items() if k.startswith("Standard_A")]
    
    console.print("\n[bold cyan]D-Series (General Purpose)[/bold cyan]")
    for old, new in d_series[:10]:
        table.add_row(old, "→", new)
    
    table.add_row("", "", "")
    
    console.print("[bold cyan]E-Series (Memory Optimized)[/bold cyan]")
    for old, new in e_series[:5]:
        table.add_row(old, "→", new)
    
    table.add_row("", "", "")
    
    console.print("[bold cyan]F-Series (Compute Optimized)[/bold cyan]")
    for old, new in f_series[:5]:
        table.add_row(old, "→", new)
    
    console.print(table)
    
    console.print("\n[dim]Note: Newer generations (v5) typically offer better price/performance ratio[/dim]")


@app.command()
def show_constraints(
    region: str = typer.Option(..., "--region", "-r", help="Azure region to check"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    show_restricted: bool = typer.Option(False, "--show-restricted", help="Include restricted SKUs"),
    family: Optional[str] = typer.Option(None, "--family", "-f", help="Filter by SKU family (e.g., 'D', 'E', 'F')"),
):
    """
    🔒 Show VM SKU constraints and availability for a region.
    
    Display which SKUs are available, restricted, and their capabilities.
    Helps identify quota issues and subscription limitations.
    """
    create_header()
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        
        console.print(f"\n[bold]Checking SKU constraints for region:[/bold] {region}\n")
        
        with console.status("[bold cyan]Fetching SKU information..."):
            skus = azure_client.get_available_skus(region, include_restricted=True)
        
        # Filter by family if specified
        if family:
            family_upper = family.upper()
            skus = [s for s in skus if family_upper in s.family.upper() or f"Standard_{family_upper}" in s.name]
        
        # Separate available and restricted
        available_skus = [s for s in skus if not s.is_restricted]
        restricted_skus = [s for s in skus if s.is_restricted]
        
        # Summary
        console.print(Panel(
            f"""[bold cyan]📊 SKU Availability Summary[/bold cyan]
            
  • Region: {region}
  • Total SKUs Found: {len(skus)}
  • Available SKUs: [green]{len(available_skus)}[/green]
  • Restricted SKUs: [red]{len(restricted_skus)}[/red]
  
[bold cyan]Restriction Types:[/bold cyan]
  • NotAvailableForSubscription: SKU not enabled for your subscription type
  • QuotaId: Regional quota limits apply
  • Zone: SKU not available in specific zones
""",
            title="[bold]🔍 Constraint Analysis[/bold]",
            border_style="blue",
        ))
        
        # Available SKUs table
        table = Table(
            title=f"✅ Available SKUs in {region}" + (f" (Family: {family})" if family else ""),
            box=box.ROUNDED,
        )
        
        table.add_column("SKU Name", style="cyan")
        table.add_column("vCPUs", justify="center")
        table.add_column("Memory", justify="center")
        table.add_column("Generation")
        table.add_column("Zones", justify="center")
        table.add_column("Key Features")
        
        for sku in sorted(available_skus, key=lambda x: (x.vcpus, x.memory_gb))[:30]:
            zones = ", ".join(sku.available_zones) if sku.available_zones else "All"
            key_features = []
            if sku.premium_io:
                key_features.append("Premium")
            if sku.accelerated_networking:
                key_features.append("AccelNet")
            if sku.ultra_ssd_available:
                key_features.append("UltraSSD")
            if sku.nested_virtualization:
                key_features.append("Nested")
            if sku.confidential_computing:
                key_features.append("Confidential")
            
            table.add_row(
                sku.name,
                str(sku.vcpus),
                f"{sku.memory_gb}GB",
                sku.generation,
                zones,
                ", ".join(key_features[:3]) if key_features else "-",
            )
        
        if len(available_skus) > 30:
            table.add_row(
                f"[dim]... and {len(available_skus) - 30} more available SKUs[/dim]",
                "", "", "", "", ""
            )
        
        console.print(table)
        
        # Restricted SKUs table
        if show_restricted and restricted_skus:
            console.print()
            
            restricted_table = Table(
                title=f"🚫 Restricted SKUs in {region}",
                box=box.ROUNDED,
            )
            
            restricted_table.add_column("SKU Name", style="yellow")
            restricted_table.add_column("vCPUs", justify="center")
            restricted_table.add_column("Memory", justify="center")
            restricted_table.add_column("Restriction Reason", style="red")
            
            for sku in sorted(restricted_skus, key=lambda x: x.name)[:20]:
                reason = sku.get_restriction_reason() or "Unknown"
                
                restricted_table.add_row(
                    sku.name,
                    str(sku.vcpus),
                    f"{sku.memory_gb}GB",
                    reason[:50] + "..." if len(reason) > 50 else reason,
                )
            
            if len(restricted_skus) > 20:
                restricted_table.add_row(
                    f"[dim]... and {len(restricted_skus) - 20} more restricted SKUs[/dim]",
                    "", "", ""
                )
            
            console.print(restricted_table)
            
            console.print("\n[bold yellow]💡 To request quota increases:[/bold yellow]")
            console.print("  Azure Portal → Subscriptions → Usage + quotas → Request increase")
        elif restricted_skus:
            console.print(f"\n[dim]ℹ️  {len(restricted_skus)} SKUs are restricted. Use --show-restricted to view them.[/dim]")
        
        # Zone availability summary
        zone_skus = [s for s in available_skus if s.available_zones]
        if zone_skus:
            console.print("\n[bold cyan]🗺️  Zone Availability Notes:[/bold cyan]")
            console.print(f"  • {len(zone_skus)} SKUs have zone restrictions")
            console.print("  • Check specific SKU zones before deploying to availability zones")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def check_quota(
    region: str = typer.Option(..., "--region", "-r", help="Azure region to check"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    family: Optional[str] = typer.Option(None, "--family", "-f", help="Filter by VM family (e.g., D, E, F)"),
):
    """
    📊 Check VM quota usage for a region.
    
    Shows current vCPU usage vs limits for all VM families.
    """
    create_header()
    
    if not CONSTRAINT_VALIDATION_AVAILABLE:
        console.print("[red]Error: Constraint validation module not available[/red]")
        raise typer.Exit(1)
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        validator = ConstraintValidator(azure_client)
        
        console.print(f"\n[bold]Checking quota for region:[/bold] {region}\n")
        
        with console.status("[bold cyan]Fetching quota information..."):
            quotas = validator.get_quota_usage(region)
        
        if not quotas:
            console.print("[yellow]No quota information found for this region[/yellow]")
            raise typer.Exit(0)
        
        # Filter by family if specified
        if family:
            quotas = [q for q in quotas if family.lower() in q.family.lower()]
        
        # Create summary
        total_used = sum(q.current_usage for q in quotas if "total" in q.family.lower())
        total_limit = sum(q.limit for q in quotas if "total" in q.family.lower())
        critical_quotas = [q for q in quotas if q.usage_percent >= 90]
        warning_quotas = [q for q in quotas if 70 <= q.usage_percent < 90]
        
        # Summary panel
        summary = f"""
[bold cyan]📊 Quota Summary for {region}[/bold cyan]

  • Total VM Families: {len(quotas)}
  • 🔴 Critical (>90%): {len(critical_quotas)}
  • 🟡 Warning (70-90%): {len(warning_quotas)}
  • 🟢 OK (<70%): {len(quotas) - len(critical_quotas) - len(warning_quotas)}
"""
        console.print(Panel(summary, border_style="blue"))
        
        # Show table
        console.print(create_quota_table(quotas))
        
        # Show critical warnings
        if critical_quotas:
            console.print("\n[bold red]⚠️ Critical Quota Warnings:[/bold red]")
            for q in critical_quotas:
                console.print(f"  • {q.family}: {q.current_usage}/{q.limit} ({q.usage_percent:.1f}%)")
            console.print("\n[dim]Consider requesting a quota increase for these families[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def validate_sku(
    sku: str = typer.Option(..., "--sku", "-k", help="SKU name to validate (e.g., Standard_D4s_v5)"),
    region: str = typer.Option(..., "--region", "-r", help="Azure region"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    vcpus: int = typer.Option(0, "--vcpus", "-c", help="Number of vCPUs needed (for quota check)"),
    zones: Optional[str] = typer.Option(None, "--zones", "-z", help="Required zones (comma-separated, e.g., 1,2,3)"),
    features: Optional[str] = typer.Option(None, "--features", "-f", help="Required features (comma-separated)"),
):
    """
    ✅ Validate if a SKU can be deployed in a region.
    
    Checks restrictions, quota, zone availability, and feature support.
    """
    create_header()
    
    if not CONSTRAINT_VALIDATION_AVAILABLE:
        console.print("[red]Error: Constraint validation module not available[/red]")
        raise typer.Exit(1)
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        validator = ConstraintValidator(azure_client)
        
        console.print(f"\n[bold]Validating SKU:[/bold] {sku} in {region}\n")
        
        # Parse zones and features
        required_zones = zones.split(",") if zones else None
        required_features = features.split(",") if features else None
        
        with console.status("[bold cyan]Validating SKU constraints..."):
            result = validator.validate_sku(
                sku_name=sku,
                location=region,
                required_vcpus=vcpus,
                required_zones=required_zones,
                required_features=required_features,
            )
        
        # Display result
        if result.is_valid:
            console.print(Panel(
                f"[green]✅ SKU {sku} is available in {region}[/green]",
                border_style="green",
            ))
        else:
            console.print(Panel(
                f"[red]❌ SKU {sku} cannot be deployed in {region}[/red]",
                border_style="red",
            ))
        
        # Show details
        details = f"""
[bold cyan]Validation Details[/bold cyan]

[bold]SKU:[/bold] {result.sku_name}
[bold]Location:[/bold] {result.location}
[bold]Valid:[/bold] {"✅ Yes" if result.is_valid else "❌ No"}
"""
        
        # Restrictions
        if result.restrictions:
            details += "\n[bold red]Restrictions Found:[/bold red]\n"
            for r in result.restrictions:
                details += f"  • [{r.restriction_type.value}] {r.reason.value}: {r.message}\n"
        else:
            details += "\n[bold green]No restrictions found[/bold green]\n"
        
        # Quota info
        if result.quota_info:
            q = result.quota_info
            quota_color = "red" if q.usage_percent >= 90 else "yellow" if q.usage_percent >= 70 else "green"
            details += f"""
[bold cyan]Quota Information[/bold cyan]
  • Family: {q.family}
  • Current Usage: {q.current_usage} {q.unit}
  • Limit: {q.limit} {q.unit}
  • Available: [{quota_color}]{q.available} {q.unit}[/{quota_color}]
  • Usage: [{quota_color}]{q.usage_percent:.1f}%[/{quota_color}]
"""
        
        # Capacity info
        if result.capacity_info:
            c = result.capacity_info
            details += f"""
[bold cyan]Capacity Information[/bold cyan]
  • Available Zones: {', '.join(c.zones) if c.zones else 'None/Not zonal'}
  • On-Demand Available: {"✅ Yes" if c.on_demand_available else "❌ No"}
  • Spot Available: {"✅ Yes" if c.spot_available else "❌ No"}
"""
        
        # Warnings
        if result.warnings:
            details += "\n[bold yellow]Warnings:[/bold yellow]\n"
            for w in result.warnings:
                details += f"  • {w}\n"
        
        console.print(Panel(details, title="Validation Report", border_style="blue"))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def check_capacity(
    region: str = typer.Option(..., "--region", "-r", help="Azure region"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    vcpus: int = typer.Option(4, "--vcpus", "-c", help="Filter by minimum vCPUs"),
    memory: float = typer.Option(8, "--memory", "-m", help="Filter by minimum memory (GB)"),
    features: Optional[str] = typer.Option(None, "--features", "-f", help="Required features (comma-separated)"),
    show_restricted: bool = typer.Option(False, "--show-restricted", help="Include restricted SKUs"),
):
    """
    🔍 Check available SKU capacity in a region.
    
    Lists all available SKUs with their constraints and zone availability.
    """
    create_header()
    
    if not CONSTRAINT_VALIDATION_AVAILABLE:
        console.print("[red]Error: Constraint validation module not available[/red]")
        raise typer.Exit(1)
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        validator = ConstraintValidator(azure_client)
        
        console.print(f"\n[bold]Checking SKU capacity in:[/bold] {region}")
        console.print(f"[dim]Filters: ≥{vcpus} vCPUs, ≥{memory}GB RAM[/dim]\n")
        
        required_features = features.split(",") if features else None
        
        with console.status("[bold cyan]Fetching available SKUs..."):
            skus = validator.get_available_skus(
                location=region,
                min_vcpus=vcpus,
                min_memory_gb=memory,
                required_features=required_features,
                exclude_restricted=not show_restricted,
            )
        
        if not skus:
            console.print("[yellow]No SKUs found matching the criteria[/yellow]")
            raise typer.Exit(0)
        
        # Create table
        table = Table(
            title=f"🔍 Available SKUs in {region}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        
        table.add_column("SKU", style="cyan")
        table.add_column("vCPUs", justify="center")
        table.add_column("Memory", justify="center")
        table.add_column("Generation")
        table.add_column("Zones", justify="center")
        table.add_column("Features")
        table.add_column("Status", justify="center")
        
        # Sort by vCPUs then memory
        skus.sort(key=lambda x: (x["vcpus"], x["memory_gb"]))
        
        for sku in skus[:50]:  # Limit to 50 rows
            zones = ", ".join(sku.get("available_zones", [])) or "-"
            features_str = ", ".join(sku.get("features", [])[:3]) or "-"
            
            if sku.get("is_restricted"):
                status = "[red]⚠️ Restricted[/red]"
            else:
                status = "[green]✅ Available[/green]"
            
            table.add_row(
                sku["name"],
                str(sku["vcpus"]),
                f"{sku['memory_gb']}GB",
                sku.get("generation", "-"),
                zones,
                features_str,
                status,
            )
        
        console.print(table)
        
        # Summary
        available_count = sum(1 for s in skus if not s.get("is_restricted"))
        restricted_count = sum(1 for s in skus if s.get("is_restricted"))
        
        console.print(f"\n[bold cyan]Summary:[/bold cyan]")
        console.print(f"  • Total SKUs found: {len(skus)}")
        console.print(f"  • Available: [green]{available_count}[/green]")
        if show_restricted:
            console.print(f"  • Restricted: [red]{restricted_count}[/red]")
        
        if len(skus) > 50:
            console.print(f"\n[dim]Showing first 50 of {len(skus)} SKUs[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def check_deployment(
    sku: str = typer.Option(..., "--sku", "-k", help="Target SKU name"),
    region: str = typer.Option(..., "--region", "-r", help="Target region"),
    count: int = typer.Option(1, "--count", "-n", help="Number of VMs to deploy"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    zones: Optional[str] = typer.Option(None, "--zones", "-z", help="Target zones (comma-separated)"),
):
    """
    🚀 Check if a deployment is feasible.
    
    Validates quota, restrictions, and capacity before deployment.
    """
    create_header()
    
    if not CONSTRAINT_VALIDATION_AVAILABLE:
        console.print("[red]Error: Constraint validation module not available[/red]")
        raise typer.Exit(1)
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    if not sub_id:
        console.print("[red]Error: Subscription ID required[/red]")
        raise typer.Exit(1)
    
    try:
        azure_client = AzureClient(subscription_id=sub_id)
        validator = ConstraintValidator(azure_client)
        
        console.print(f"\n[bold]Checking deployment feasibility:[/bold]")
        console.print(f"  • SKU: {sku}")
        console.print(f"  • Region: {region}")
        console.print(f"  • Count: {count} VM(s)")
        if zones:
            console.print(f"  • Zones: {zones}")
        console.print()
        
        target_zones = zones.split(",") if zones else None
        
        with console.status("[bold cyan]Checking deployment feasibility..."):
            is_feasible, issues = validator.check_deployment_feasibility(
                sku_name=sku,
                location=region,
                count=count,
                zones=target_zones,
            )
        
        if is_feasible:
            console.print(Panel(
                f"[green]✅ Deployment is feasible![/green]\n\n"
                f"You can deploy {count} x {sku} in {region}",
                title="Deployment Check",
                border_style="green",
            ))
        else:
            issues_text = "\n".join(f"  • {issue}" for issue in issues)
            console.print(Panel(
                f"[red]❌ Deployment is NOT feasible[/red]\n\n"
                f"[bold]Issues found:[/bold]\n{issues_text}",
                title="Deployment Check",
                border_style="red",
            ))
            
            # Suggestions
            console.print("\n[bold cyan]Suggestions:[/bold cyan]")
            if any("quota" in i.lower() for i in issues):
                console.print("  • Request a quota increase via Azure Portal or Support")
                console.print("  • Consider a different VM family with available quota")
            if any("restrict" in i.lower() for i in issues):
                console.print("  • Try a different region")
                console.print("  • Use a different SKU from the same family")
            if any("zone" in i.lower() for i in issues):
                console.print("  • Remove zone requirements or use a different zone")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """Show version information."""
    console.print("\n[bold cyan]Azure VM Rightsizer CLI[/bold cyan]")
    console.print("Version: 1.0.0")
    console.print("Author: FinOps Team")
    console.print()


@app.command()
def check_availability(
    sku: str = typer.Option(..., "--sku", "-k", help="VM SKU to check (e.g., Standard_D16ds_v5)"),
    region: str = typer.Option("eastus2", "--region", "-r", help="Azure region to check"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    no_zones: bool = typer.Option(False, "--no-zones", help="Skip per-zone availability check"),
    no_alternatives: bool = typer.Option(False, "--no-alternatives", help="Skip finding alternative SKUs"),
    log_analytics: bool = typer.Option(False, "--log-analytics", help="Log results to Azure Monitor"),
    endpoint: Optional[str] = typer.Option(None, "--endpoint", help="Log Analytics Data Collection Endpoint"),
    rule_id: Optional[str] = typer.Option(None, "--rule-id", help="Log Analytics Data Collection Rule ID"),
    stream_name: str = typer.Option("Custom-VMSKUCapacity_CL", "--stream-name", help="Log Analytics stream name"),
    output_json: Optional[str] = typer.Option(None, "--output", "-o", help="Output results to JSON file"),
):
    """
    🔍 Check VM SKU availability with per-zone awareness.
    
    Checks if a specific VM SKU is available in a region, shows zone-level
    availability, and suggests similar alternatives if the SKU is constrained.
    
    Examples:
        python main.py check-availability --sku Standard_D16ds_v5 --region eastus2
        python main.py check-availability -k Standard_E8s_v5 -r westeurope --log-analytics
    """
    create_header()
    
    from availability_checker import (
        SKUAvailabilityChecker,
        LogAnalyticsLogger,
        display_availability_result,
    )
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    try:
        console.print(f"\n[bold]Checking availability for:[/bold] {sku} in {region}\n")
        
        with console.status("[bold cyan]Checking SKU availability..."):
            checker = SKUAvailabilityChecker(subscription_id=sub_id)
            result = checker.check_sku_availability(
                sku_name=sku,
                region=region,
                check_zones=not no_zones,
                find_alternatives=not no_alternatives,
            )
        
        # Display results
        display_availability_result(
            result,
            show_specs=True,
            show_alternatives=not no_alternatives,
        )
        
        # Log to Azure Monitor if enabled
        if log_analytics:
            if not endpoint or not rule_id:
                console.print("\n[yellow]⚠️  Log Analytics requires --endpoint and --rule-id[/yellow]")
            else:
                try:
                    la_logger = LogAnalyticsLogger(
                        endpoint=endpoint,
                        rule_id=rule_id,
                        stream_name=stream_name,
                    )
                    if la_logger.log_availability_check(result):
                        console.print("\n[green]✓ Logged to Azure Monitor Log Analytics[/green]")
                except Exception as e:
                    console.print(f"\n[red]Error logging to Log Analytics: {e}[/red]")
        
        # Output to JSON if requested
        if output_json:
            import json
            output_data = result.to_dict()
            output_data['alternative_skus'] = [alt.to_dict() for alt in result.alternative_skus]
            
            with open(output_json, 'w') as f:
                json.dump(output_data, f, indent=2, default=str)
            console.print(f"\n[green]✓ Results saved to {output_json}[/green]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def check_availability_multi(
    sku: str = typer.Option(..., "--sku", "-k", help="VM SKU to check"),
    regions: str = typer.Option(
        "eastus,eastus2,westus2,westeurope,northeurope",
        "--regions", "-r",
        help="Comma-separated list of regions to check"
    ),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    log_analytics: bool = typer.Option(False, "--log-analytics", help="Log results to Azure Monitor"),
    endpoint: Optional[str] = typer.Option(None, "--endpoint", help="Log Analytics Data Collection Endpoint"),
    rule_id: Optional[str] = typer.Option(None, "--rule-id", help="Log Analytics Data Collection Rule ID"),
):
    """
    🌍 Check VM SKU availability across multiple regions.
    
    Useful for finding which regions have capacity for a specific SKU.
    
    Examples:
        python main.py check-availability-multi --sku Standard_D16ds_v5
        python main.py check-availability-multi -k Standard_E8s_v5 -r "eastus,westeurope,southeastasia"
    """
    create_header()
    
    from availability_checker import (
        SKUAvailabilityChecker,
        LogAnalyticsLogger,
        display_multi_region_results,
    )
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    region_list = [r.strip() for r in regions.split(",")]
    
    try:
        console.print(f"\n[bold]Checking availability for:[/bold] {sku}")
        console.print(f"[bold]Regions:[/bold] {', '.join(region_list)}\n")
        
        with console.status("[bold cyan]Checking availability across regions..."):
            checker = SKUAvailabilityChecker(subscription_id=sub_id)
            results = checker.check_sku_across_regions(
                sku_name=sku,
                regions=region_list,
                check_zones=True,
            )
        
        # Display results
        display_multi_region_results(sku, results)
        
        # Log to Azure Monitor if enabled
        if log_analytics and endpoint and rule_id:
            try:
                la_logger = LogAnalyticsLogger(
                    endpoint=endpoint,
                    rule_id=rule_id,
                )
                success, failed = la_logger.log_batch(list(results.values()))
                console.print(f"\n[green]✓ Logged {success} results to Azure Monitor[/green]")
            except Exception as e:
                console.print(f"\n[red]Error logging to Log Analytics: {e}[/red]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def find_alternatives(
    sku: str = typer.Option(..., "--sku", "-k", help="Target VM SKU"),
    region: str = typer.Option(..., "--region", "-r", help="Azure region"),
    subscription: Optional[str] = typer.Option(None, "--subscription", "-s", help="Azure Subscription ID"),
    max_results: int = typer.Option(10, "--max", "-m", help="Maximum alternatives to show"),
    min_similarity: int = typer.Option(60, "--min-similarity", help="Minimum similarity percentage"),
):
    """
    🔄 Find alternative SKUs similar to a target SKU.
    
    Useful when your preferred SKU is capacity-constrained.
    Shows available alternatives sorted by similarity.
    
    Examples:
        python main.py find-alternatives --sku Standard_D16ds_v5 --region eastus2
    """
    create_header()
    
    from availability_checker import SKUAvailabilityChecker
    
    settings = Settings()
    sub_id = subscription or settings.azure_subscription_id
    
    try:
        console.print(f"\n[bold]Finding alternatives for:[/bold] {sku} in {region}\n")
        
        with console.status("[bold cyan]Searching for similar SKUs..."):
            checker = SKUAvailabilityChecker(subscription_id=sub_id)
            result = checker.check_sku_availability(
                sku_name=sku,
                region=region,
                check_zones=True,
                find_alternatives=True,
                max_alternatives=max_results * 2,  # Get more to filter
            )
        
        # Filter by similarity
        alternatives = [
            alt for alt in result.alternative_skus
            if alt.similarity_score >= min_similarity
        ][:max_results]
        
        # Display target SKU info
        console.print(Panel(
            f"""[bold]Target SKU:[/bold] {sku}
[bold]Region:[/bold] {region}
[bold]Available:[/bold] {"✅ Yes" if result.is_available else "❌ No"}
[bold]vCPUs:[/bold] {result.specifications.vcpus if result.specifications else 'N/A'}
[bold]Memory:[/bold] {result.specifications.memory_gb if result.specifications else 'N/A'} GB""",
            title="🎯 Target SKU",
            border_style="cyan",
        ))
        
        if alternatives:
            table = Table(
                title=f"🔄 Available Alternatives (Similarity ≥ {min_similarity}%)",
                box=box.ROUNDED,
            )
            
            table.add_column("Rank", style="bold", justify="center")
            table.add_column("SKU Name", style="green")
            table.add_column("vCPUs", justify="center")
            table.add_column("Memory", justify="center")
            table.add_column("Family")
            table.add_column("Similarity", justify="center")
            table.add_column("Zones")
            
            for i, alt in enumerate(alternatives, 1):
                sim_color = "green" if alt.similarity_score >= 80 else "yellow"
                zones = ", ".join(alt.available_zones[:3]) if alt.available_zones else "All"
                if len(alt.available_zones) > 3:
                    zones += f" (+{len(alt.available_zones) - 3})"
                
                table.add_row(
                    str(i),
                    alt.name,
                    str(alt.vcpus),
                    f"{alt.memory_gb} GB",
                    alt.family,
                    f"[{sim_color}]{alt.similarity_score}%[/{sim_color}]",
                    zones,
                )
            
            console.print()
            console.print(table)
            
            console.print(f"\n[bold cyan]💡 Tip:[/bold cyan] Higher similarity means more compatible specifications")
            console.print("[dim]Consider family, premium storage support, and accelerated networking when choosing[/dim]")
        else:
            console.print(f"\n[yellow]No alternatives found with ≥{min_similarity}% similarity[/yellow]")
            console.print("[dim]Try lowering --min-similarity to see more options[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def main():
    """Main entry point."""
    # If no arguments provided, show interactive menu
    if len(sys.argv) == 1:
        interactive_menu()
    else:
        app()


# Global state for interactive mode
_interactive_state = {
    "subscriptions": [],
    "selected_subscriptions": [],
    "logged_in": False,
}


def azure_login_flow():
    """Handle Azure login and subscription selection."""
    from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    from azure.mgmt.subscription import SubscriptionClient
    
    console.print(Panel("[bold]🔐 Azure Authentication[/bold]", style="cyan"))
    console.print()
    
    # Try to get credentials
    try:
        with console.status("[cyan]🦎 Checking Azure credentials...[/cyan]"):
            credential = DefaultAzureCredential()
            sub_client = SubscriptionClient(credential)
            
            # Fetch all subscriptions
            subscriptions = []
            for sub in sub_client.subscriptions.list():
                subscriptions.append({
                    "id": sub.subscription_id,
                    "name": sub.display_name,
                    "state": sub.state,
                    "tenant_id": sub.tenant_id,
                })
        
        if not subscriptions:
            console.print("[yellow]⚠️  No subscriptions found. Please check your Azure access.[/yellow]")
            return False
        
        console.print(f"[green]✅ Logged in successfully! Found {len(subscriptions)} subscription(s)[/green]\n")
        _interactive_state["subscriptions"] = subscriptions
        _interactive_state["logged_in"] = True
        
        return select_subscriptions(subscriptions)
        
    except Exception as e:
        console.print(f"[yellow]⚠️  Default credentials not found. Attempting browser login...[/yellow]")
        
        try:
            credential = InteractiveBrowserCredential()
            sub_client = SubscriptionClient(credential)
            
            subscriptions = []
            for sub in sub_client.subscriptions.list():
                subscriptions.append({
                    "id": sub.subscription_id,
                    "name": sub.display_name,
                    "state": sub.state,
                    "tenant_id": sub.tenant_id,
                })
            
            if subscriptions:
                console.print(f"[green]✅ Logged in successfully! Found {len(subscriptions)} subscription(s)[/green]\n")
                _interactive_state["subscriptions"] = subscriptions
                _interactive_state["logged_in"] = True
                return select_subscriptions(subscriptions)
                
        except Exception as e2:
            console.print(f"[red]❌ Login failed: {e2}[/red]")
            console.print("[dim]Try running 'az login' first, or check your credentials.[/dim]")
            return False
    
    return False


def select_subscriptions(subscriptions: list) -> bool:
    """Let user select one, multiple, or all subscriptions using keyboard."""
    import questionary
    from questionary import Style
    
    # Subtle inverse bar style
    custom_style = Style([
        ('qmark', 'fg:#888888'),
        ('question', 'fg:#ffffff bold'),
        ('answer', 'fg:#88cc88'),
        ('pointer', 'fg:#ffffff bold'),
        ('highlighted', 'bg:#444444 fg:#ffffff'),
        ('selected', 'fg:#88cc88'),
    ])
    
    # Build choices - add "All" option at top
    choices = ["🌐 ALL SUBSCRIPTIONS (whole tenant)"]
    for sub in subscriptions:
        state_icon = "✅" if sub["state"] == "Enabled" else "⚠️"
        choices.append(f"{state_icon} {sub['name']} ({sub['id'][:8]}...)")
    
    console.print("\n[dim]Use ↑↓ arrows to navigate, Space to select multiple, Enter to confirm[/dim]\n")
    
    # Use checkbox for multi-select
    answers = questionary.checkbox(
        "🦎 Select subscription(s):",
        choices=choices,
        style=custom_style,
        qmark="",
    ).ask()
    
    if answers is None:
        return False
    
    selected = []
    
    # Check if "ALL" was selected
    if choices[0] in answers:
        selected = subscriptions.copy()
        console.print(f"\n[green]✅ Selected ALL {len(selected)} subscription(s)[/green]")
    else:
        # Map selected choices back to subscriptions
        for answer in answers:
            # Extract subscription by matching (skip the icon)
            for sub in subscriptions:
                if sub['name'] in answer:
                    selected.append(sub)
                    break
    
    if not selected:
        # If nothing selected, default to first
        console.print("[yellow]No selection made. Using first subscription.[/yellow]")
        selected = [subscriptions[0]]
    
    _interactive_state["selected_subscriptions"] = selected
    
    # Show selected
    if len(selected) <= 5:
        names = ", ".join([s["name"] for s in selected])
        console.print(f"[green]🦎 Selected: {names}[/green]\n")
    else:
        console.print(f"[green]🦎 Selected {len(selected)} subscriptions[/green]\n")
    
    return True


def get_selected_subscription_ids() -> list:
    """Get list of selected subscription IDs."""
    return [s["id"] for s in _interactive_state.get("selected_subscriptions", [])]


def get_first_subscription_id() -> str:
    """Get the first selected subscription ID."""
    subs = _interactive_state.get("selected_subscriptions", [])
    if subs:
        return subs[0]["id"]
    return os.environ.get("AZURE_SUBSCRIPTION_ID", "")


def interactive_menu():
    """Show an interactive menu for the CLI using a loop (no recursion)."""
    import questionary
    from questionary import Style

    create_header()

    # First, handle Azure login
    if not _interactive_state.get("logged_in"):
        if not azure_login_flow():
            console.print("\n[yellow]Continuing without Azure login...[/yellow]")
            console.print("[dim]Some features may require manual subscription input.[/dim]\n")

    # Menu options - (key, display_name, command, description)
    menu_items = [
        ("1", "🔍 Analyze VMs", "analyze", "Full VM analysis with rightsizing recommendations"),
        ("2", "🌍 Compare Regions", "compare-regions", "Find cheaper regions for your VMs"),
        ("3", "📊 Rank SKUs", "rank-skus", "Compare and rank VM SKUs"),
        ("4", "📜 Show Generations", "show-generations", "View generation upgrade paths"),
        ("5", "🔒 Show Constraints", "show-constraints", "View SKU constraints for a region"),
        ("6", "📊 Check Quota", "check-quota", "Check VM quota usage"),
        ("7", "✅ Validate SKU", "validate-sku", "Validate SKU deployment"),
        ("8", "🔍 Check Capacity", "check-capacity", "Check available SKU capacity"),
        ("9", "🔍 Check Availability", "check-availability", "Check SKU availability with zones"),
        ("10", "🌍 Multi-Region Availability", "check-availability-multi", "Check SKU across regions"),
        ("11", "🔄 Find Alternatives", "find-alternatives", "Find similar SKUs"),
        ("C", "🔄 Change Subscription", "change-sub", "Select different subscription(s)"),
        ("0", "❌ Exit", "exit", "Exit the CLI"),
    ]

    # Subtle inverse bar style (less harsh than bright cyan)
    custom_style = Style([
        ('qmark', 'fg:#888888'),
        ('question', 'fg:#ffffff bold'),
        ('answer', 'fg:#88cc88'),
        ('pointer', 'fg:#ffffff bold'),
        ('highlighted', 'bg:#444444 fg:#ffffff'),
        ('selected', 'fg:#88cc88'),
    ])

    # Build choices for questionary
    choices = [f"{item[1]} - {item[3]}" for item in menu_items]

    while True:
        # Show current subscription info
        if _interactive_state.get("selected_subscriptions"):
            subs = _interactive_state["selected_subscriptions"]
            if len(subs) == 1:
                console.print(f"[dim]📍 Active: {subs[0]['name']}[/dim]")
            else:
                console.print(f"[dim]📍 Active: {len(subs)} subscriptions selected[/dim]")
            console.print()

        console.print("[dim]Use ↑↓ arrows to navigate, Enter to select[/dim]\n")

        # Get user choice using keyboard navigation
        answer = questionary.select(
            "🦎 Choose your evolution:",
            choices=choices,
            style=custom_style,
            qmark="",
            pointer="▶",
        ).ask()

        if answer is None:
            # User pressed Ctrl+C
            console.print("\n[bold magenta]🦎 The Skælvox rests... Goodbye! ✨[/bold magenta]\n")
            raise typer.Exit(0)

        # Find selected item by matching the display string
        selected_idx = choices.index(answer)
        selected = menu_items[selected_idx]

        if selected[0] == "0":
            console.print("\n[bold magenta]🦎 The Skælvox rests... Goodbye! ✨[/bold magenta]\n")
            raise typer.Exit(0)

        if selected[2] == "change-sub":
            # Change subscription
            if _interactive_state.get("subscriptions"):
                select_subscriptions(_interactive_state["subscriptions"])
            else:
                azure_login_flow()
            continue

        command = selected[2]
        console.print(f"\n[bold green]🦎 Evolving to: {selected[1]}[/bold green]\n")

        # Gather parameters based on command
        try:
            if command == "analyze":
                run_interactive_analyze()
            elif command == "compare-regions":
                run_interactive_compare_regions()
            elif command == "rank-skus":
                run_interactive_rank_skus()
            elif command == "show-generations":
                # No parameters needed
                sys.argv = ["main.py", "show-generations"]
                app()
            elif command == "show-constraints":
                run_interactive_show_constraints()
            elif command == "check-quota":
                run_interactive_check_quota()
            elif command == "validate-sku":
                run_interactive_validate_sku()
            elif command == "check-capacity":
                run_interactive_check_capacity()
            elif command == "check-availability":
                run_interactive_check_availability()
            elif command == "check-availability-multi":
                run_interactive_check_availability_multi()
            elif command == "find-alternatives":
                run_interactive_find_alternatives()
        except SystemExit:
            pass  # Typer raises SystemExit after commands; continue the menu loop

        console.print()  # Add spacing before next menu iteration


def run_interactive_analyze():
    """Interactive mode for analyze command."""
    console.print(Panel("[bold]🔍 VM Analysis Configuration[/bold]", style="cyan"))
    
    # Use selected subscriptions or ask
    selected_subs = get_selected_subscription_ids()
    
    if len(selected_subs) > 1:
        # Multiple subscriptions selected - analyze all
        console.print(f"[cyan]Analyzing {len(selected_subs)} subscription(s)...[/cyan]")
        analyze_all = Confirm.ask("[cyan]Analyze all selected subscriptions?[/cyan]", default=True)
        if not analyze_all:
            # Let them pick one
            subscription = Prompt.ask("[cyan]Subscription ID[/cyan]", default=selected_subs[0])
            selected_subs = [subscription]
    elif len(selected_subs) == 1:
        subscription = selected_subs[0]
    else:
        subscription = Prompt.ask("[cyan]Subscription ID[/cyan]", default=os.environ.get("AZURE_SUBSCRIPTION_ID", ""))
        selected_subs = [subscription]
    
    resource_group = Prompt.ask("[cyan]Resource Group (optional, press Enter for all)[/cyan]", default="")
    use_ai = Confirm.ask("[cyan]Enable AI-powered analysis?[/cyan]", default=True)
    detailed = Confirm.ask("[cyan]Show detailed results?[/cyan]", default=False)
    
    # Run for each subscription
    for sub_id in selected_subs:
        if len(selected_subs) > 1:
            sub_name = next((s["name"] for s in _interactive_state.get("selected_subscriptions", []) if s["id"] == sub_id), sub_id)
            console.print(f"\n[bold magenta]═══ Analyzing: {sub_name} ═══[/bold magenta]\n")
        
        args = ["main.py", "analyze", "-s", sub_id]
        if resource_group:
            args.extend(["-g", resource_group])
        if not use_ai:
            args.append("--no-ai")
        if detailed:
            args.append("--detailed")
        
        console.print(f"[dim]Running: {' '.join(args)}[/dim]\n")
        sys.argv = args
        try:
            app()
        except SystemExit:
            pass  # Continue to next subscription


def run_interactive_compare_regions():
    """Interactive mode for compare-regions command."""
    console.print(Panel("[bold]🌍 Regional Price Comparison[/bold]", style="cyan"))
    
    vm_name = Prompt.ask("[cyan]VM Name[/cyan]")
    resource_group = Prompt.ask("[cyan]Resource Group[/cyan]")
    subscription = Prompt.ask("[cyan]Subscription ID[/cyan]", default=get_first_subscription_id())
    
    args = ["main.py", "compare-regions", "-v", vm_name, "-g", resource_group]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_rank_skus():
    """Interactive mode for rank-skus command."""
    console.print(Panel("[bold]📊 SKU Ranking Configuration[/bold]", style="cyan"))
    
    vcpus = IntPrompt.ask("[cyan]Number of vCPUs[/cyan]", default=4)
    memory = IntPrompt.ask("[cyan]Memory (GB)[/cyan]", default=16)
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    os_type = Prompt.ask("[cyan]OS Type[/cyan]", choices=["Linux", "Windows"], default="Linux")
    subscription = get_first_subscription_id()
    
    args = ["main.py", "rank-skus", "-c", str(vcpus), "-m", str(memory), "-r", region, "--os", os_type]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_show_constraints():
    """Interactive mode for show-constraints command."""
    console.print(Panel("[bold]🔒 SKU Constraints[/bold]", style="cyan"))
    
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    family = Prompt.ask("[cyan]Filter by family (optional)[/cyan]", default="")
    show_restricted = Confirm.ask("[cyan]Show restricted SKUs?[/cyan]", default=False)
    subscription = get_first_subscription_id()
    
    args = ["main.py", "show-constraints", "-r", region]
    if family:
        args.extend(["--family", family])
    if show_restricted:
        args.append("--show-restricted")
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_check_quota():
    """Interactive mode for check-quota command."""
    console.print(Panel("[bold]📊 Quota Check[/bold]", style="cyan"))
    
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    subscription = get_first_subscription_id()
    
    args = ["main.py", "check-quota", "-r", region]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_validate_sku():
    """Interactive mode for validate-sku command."""
    console.print(Panel("[bold]✅ SKU Validation[/bold]", style="cyan"))
    
    sku = Prompt.ask("[cyan]SKU Name[/cyan]", default="Standard_D4s_v5")
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    subscription = get_first_subscription_id()
    
    args = ["main.py", "validate-sku", "--sku", sku, "-r", region]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_check_capacity():
    """Interactive mode for check-capacity command."""
    console.print(Panel("[bold]🔍 Capacity Check[/bold]", style="cyan"))

    vcpus = IntPrompt.ask("[cyan]Minimum vCPUs[/cyan]", default=4)
    memory = IntPrompt.ask("[cyan]Minimum Memory (GB)[/cyan]", default=8)
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    subscription = get_first_subscription_id()

    args = ["main.py", "check-capacity", "-r", region, "-c", str(vcpus), "-m", str(memory)]
    if subscription:
        args.extend(["-s", subscription])

    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_check_availability():
    """Interactive mode for check-availability command."""
    console.print(Panel("[bold]🔍 SKU Availability Check[/bold]", style="cyan"))
    
    sku = Prompt.ask("[cyan]SKU Name[/cyan]", default="Standard_D4s_v5")
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    subscription = get_first_subscription_id()
    
    args = ["main.py", "check-availability", "--sku", sku, "-r", region]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_check_availability_multi():
    """Interactive mode for check-availability-multi command."""
    console.print(Panel("[bold]🌍 Multi-Region Availability Check[/bold]", style="cyan"))
    
    sku = Prompt.ask("[cyan]SKU Name[/cyan]", default="Standard_D4s_v5")
    regions = Prompt.ask("[cyan]Regions (comma-separated)[/cyan]", default="eastus,westeurope,southeastasia")
    subscription = get_first_subscription_id()
    
    args = ["main.py", "check-availability-multi", "--sku", sku, "--regions", regions]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


def run_interactive_find_alternatives():
    """Interactive mode for find-alternatives command."""
    console.print(Panel("[bold]🔄 Find Alternative SKUs[/bold]", style="cyan"))
    
    sku = Prompt.ask("[cyan]SKU Name[/cyan]", default="Standard_D4s_v5")
    region = Prompt.ask("[cyan]Region[/cyan]", default="westeurope")
    min_similarity = IntPrompt.ask("[cyan]Minimum similarity %[/cyan]", default=70)
    subscription = get_first_subscription_id()
    
    args = ["main.py", "find-alternatives", "--sku", sku, "-r", region, "--min-similarity", str(min_similarity)]
    if subscription:
        args.extend(["-s", subscription])
    
    console.print(f"\n[dim]Running: {' '.join(args)}[/dim]\n")
    sys.argv = args
    app()


if __name__ == "__main__":
    main()
