#!/usr/bin/env python3
"""
Demo script showing sample output from the Azure VM Rightsizer CLI.
This demonstrates the rich CLI output without requiring Azure credentials.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box
from datetime import datetime

console = Console()


def create_header():
    """Create a beautiful header for the CLI."""
    header = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     █████╗ ███████╗██╗   ██╗██████╗ ███████╗    ██╗   ██╗███╗   ███╗        ║
║    ██╔══██╗╚══███╔╝██║   ██║██╔══██╗██╔════╝    ██║   ██║████╗ ████║        ║
║    ███████║  ███╔╝ ██║   ██║██████╔╝█████╗      ██║   ██║██╔████╔██║        ║
║    ██╔══██║ ███╔╝  ██║   ██║██╔══██╗██╔══╝      ╚██╗ ██╔╝██║╚██╔╝██║        ║
║    ██║  ██║███████╗╚██████╔╝██║  ██║███████╗     ╚████╔╝ ██║ ╚═╝ ██║        ║
║    ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝      ╚═══╝  ╚═╝     ╚═╝        ║
║                                                                              ║
║                    🔧  R I G H T S I Z E R   C L I  🔧                       ║
║                                                                              ║
║          Intelligent VM Analysis • Cost Optimization • AI-Powered           ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    console.print(header, style="bold blue")


def demo_analysis():
    """Demonstrate the analysis output."""
    create_header()
    
    console.print("\n[bold]Starting analysis for subscription:[/bold] 12345678-abcd-efgh-ijkl-123456789012\n")
    console.print("[green]✓ AI analysis enabled[/green]")
    console.print()
    
    # Simulated progress
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    import time
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task1 = progress.add_task("[cyan]Discovering VMs...", total=100)
        for _ in range(100):
            progress.update(task1, advance=1)
            time.sleep(0.01)
        
        task2 = progress.add_task("[cyan]Fetching Advisor recommendations...", total=100)
        for _ in range(100):
            progress.update(task2, advance=1)
            time.sleep(0.005)
        
        task3 = progress.add_task("[cyan]Analyzing VMs...", total=100)
        for _ in range(100):
            progress.update(task3, advance=1)
            time.sleep(0.02)
    
    console.print("[green]Found 45 VMs[/green]")
    console.print("[green]Found 12 Advisor recommendations[/green]")
    
    # Summary Panel
    summary = """
[bold]Analysis Timestamp:[/bold] 2025-01-30 14:23:45 UTC
[bold]Subscription ID:[/bold] 12345678-abcd-efgh-ijkl-123456789012

[bold cyan]📊 VM Statistics[/bold cyan]
  • Total VMs Discovered: 45
  • VMs Analyzed: 45
  • VMs with Recommendations: 23

[bold cyan]💰 Cost Summary[/bold cyan]
  • Current Monthly Cost: $12,450.00
  • Potential Monthly Savings: [green]$3,247.50[/green]
  • Potential Annual Savings: [green]$38,970.00[/green]
  • Savings Percentage: [green]26.1%[/green]

[bold cyan]📋 Recommendation Breakdown[/bold cyan]
  • 🔴 Shutdown Candidates: 3
  • 📐 Rightsize Candidates: 14
  • ⬆️  Generation Upgrades: 8
  • 🌍 Region Move Candidates: 5
"""
    
    console.print()
    console.print(Panel(
        summary,
        title="[bold white]📈 Analysis Summary[/bold white]",
        border_style="blue",
        box=box.DOUBLE,
    ))
    
    # VM Table
    console.print()
    
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
    
    # Sample data
    vms = [
        ("web-prod-01", "production-rg", "Standard_D8s_v3", "Standard_D4s_v5", "rightsize", 245.00, "High"),
        ("api-server-02", "production-rg", "Standard_E16s_v3", "Standard_E8s_v5", "rightsize", 312.50, "High"),
        ("db-staging-01", "staging-rg", "Standard_D16s_v4", "Standard_D8s_v5", "rightsize", 198.00, "High"),
        ("worker-batch-03", "batch-rg", "Standard_F8s_v2", "[dim]Shutdown[/dim]", "shutdown", 456.00, "High"),
        ("cache-prod-01", "production-rg", "Standard_E4s_v3", "Standard_E4s_v5", "generation_upgrade", 89.00, "Medium"),
        ("monitor-01", "infra-rg", "Standard_D4s_v3", "Standard_D4s_v5", "generation_upgrade", 67.50, "Medium"),
        ("app-test-02", "test-rg", "Standard_D2s_v3", "Standard_D2s_v5", "generation_upgrade", 45.00, "Medium"),
        ("web-dev-01", "dev-rg", "Standard_B4ms", "[dim]Move to eastus[/dim]", "region_move", 34.00, "Low"),
        ("jenkins-01", "cicd-rg", "Standard_D4_v3", "Standard_D4s_v5", "generation_upgrade", 78.00, "Medium"),
        ("elastic-01", "logging-rg", "Standard_E8_v3", "Standard_E8s_v5", "generation_upgrade", 156.00, "Medium"),
        ("redis-prod-01", "production-rg", "Standard_D4s_v4", "Standard_D4s_v5", "rightsize", 42.50, "Low"),
        ("grafana-01", "monitoring-rg", "Standard_D2s_v3", "Standard_B2ms", "rightsize", 67.00, "Medium"),
    ]
    
    for vm_name, rg, current, recommended, rec_type, savings, priority in vms:
        priority_colors = {"High": "red", "Medium": "yellow", "Low": "green"}
        priority_text = f"[{priority_colors[priority]}]●[/{priority_colors[priority]}] {priority}"
        
        table.add_row(
            vm_name,
            rg,
            current,
            recommended,
            rec_type,
            f"${savings:,.2f}",
            priority_text,
        )
    
    table.add_row(
        "[dim]... and 11 more VMs[/dim]",
        "", "", "", "", "", ""
    )
    
    console.print(table)
    
    # Detailed VM Analysis
    console.print("\n[bold cyan]═══ Detailed Analysis (Top 3) ═══[/bold cyan]\n")
    
    detailed_vm = """[bold cyan]VM Information[/bold cyan]
  • Name: web-prod-01
  • Resource Group: production-rg
  • Location: westeurope
  • Current SKU: Standard_D8s_v3
  • OS Type: Linux
  • Power State: running
  • Current Monthly Cost: $584.00

[bold cyan]Performance Metrics (30-day avg)[/bold cyan]
  • Avg CPU: 23.4%
  • Max CPU: 67.2%
  • Avg Memory: 31.2%
  • Max Memory: 58.9%

[bold cyan]Azure Advisor Recommendation[/bold cyan]
  • Problem: Virtual machine is underutilized
  • Solution: Consider resizing to a smaller VM size
  • Recommended SKU: Standard_D4s_v5
  • Impact: Medium

[bold cyan]🤖 AI-Powered Recommendation[/bold cyan]
  • Recommended SKU: [green]Standard_D4s_v5[/green]
  • Confidence: [green]High[/green]
  • Est. Monthly Savings: [green]$245.00[/green]
  • Migration Complexity: Low
  
  [bold]Reasoning:[/bold]
  Based on 30-day performance data, this VM averages 23% CPU with peak at 67%. 
  The current D8s_v3 (8 vCPUs) is oversized. A D4s_v5 (4 vCPUs) provides adequate 
  headroom while offering v5 generation benefits including better price/performance.
  
  [bold]Risk Assessment:[/bold]
  Low risk - the recommended SKU maintains 50%+ headroom even at peak utilization. 
  Monitor for 1 week post-migration.

[bold cyan]⬆️ Generation Upgrade Available[/bold cyan]
  • Current Generation: v3
  • Recommended SKU: [green]Standard_D8s_v5[/green]
  • Monthly Savings: [green]$89.00[/green]

[bold cyan]🌍 Cheaper Regions Available[/bold cyan]
  • northeurope: $512.00/mo (save $72.00)
  • uksouth: $534.00/mo (save $50.00)
  • germanywestcentral: $556.00/mo (save $28.00)

[bold cyan]📊 Top Alternative SKUs (by score)[/bold cyan]
  1. Standard_D4s_v5 - Score: 92.5, $339.00/mo [green](save $245.00)[/green]
     4 vCPUs, 16GB RAM, V1,V2
  2. Standard_D4as_v5 - Score: 89.3, $298.00/mo [green](save $286.00)[/green]
     4 vCPUs, 16GB RAM, V1,V2
  3. Standard_D8s_v5 - Score: 85.1, $495.00/mo [green](save $89.00)[/green]
     8 vCPUs, 32GB RAM, V1,V2
"""
    
    console.print(Panel(
        detailed_vm,
        title="[red]●[/red] web-prod-01 - RIGHTSIZE",
        border_style="red",
        box=box.ROUNDED,
    ))
    
    # AI Executive Summary
    ai_summary = """
## Azure VM Rightsizing Analysis - Executive Summary

### Key Findings

This analysis identified **$38,970 in potential annual savings** across 45 virtual machines 
in the subscription. The primary optimization opportunities fall into three categories:

1. **Rightsizing (14 VMs, $18,500/year)**: Several production workloads are significantly 
   overprovisioned, with average CPU utilization below 30%. These VMs can be safely 
   downsized while maintaining performance headroom.

2. **Generation Upgrades (8 VMs, $9,800/year)**: Legacy v3-series VMs can be migrated to 
   v5-series, offering both cost savings and improved performance.

3. **Shutdown Candidates (3 VMs, $6,200/year)**: Three VMs show minimal utilization 
   (< 5% CPU) and should be evaluated for decommissioning.

### Quick Wins (Implement This Week)

- Resize `worker-batch-03` - Saving $456/month with shutdown
- Resize `api-server-02` from E16s_v3 to E8s_v5 - Saving $312/month
- Resize `web-prod-01` from D8s_v3 to D4s_v5 - Saving $245/month

### Recommended Next Steps

1. Review and approve high-confidence recommendations (14 VMs)
2. Schedule migrations during maintenance windows
3. Implement Azure Monitor alerts on resized VMs
4. Consider Reserved Instances for consistently utilized workloads
"""
    
    console.print(Panel(
        Markdown(ai_summary),
        title="[bold]🤖 AI Executive Summary[/bold]",
        border_style="magenta",
        box=box.DOUBLE,
    ))
    
    console.print("\n[green]✓ Analysis complete![/green]")
    console.print("[dim]Run with --output results.json to export data[/dim]\n")


def demo_region_comparison():
    """Demonstrate region comparison output."""
    create_header()
    
    console.print("\n[bold]Comparing regional prices for:[/bold] web-prod-01 (Standard_D8s_v3)\n")
    
    table = Table(
        title="🌍 Regional Price Comparison for web-prod-01 (Standard_D8s_v3)",
        box=box.ROUNDED,
    )
    
    table.add_column("Region", style="cyan")
    table.add_column("Hourly Price", justify="right")
    table.add_column("Monthly Price", justify="right")
    table.add_column("Monthly Savings", justify="right", style="green")
    table.add_column("Savings %", justify="right", style="green")
    
    regions = [
        ("eastus", 0.584, 426.32, 157.68, "27.0%"),
        ("centralus", 0.612, 446.76, 137.24, "23.5%"),
        ("northeurope", 0.698, 509.54, 74.46, "12.8%"),
        ("[bold]westeurope[/bold]", 0.800, 584.00, "-", "-"),
        ("uksouth", 0.734, 535.82, 48.18, "8.2%"),
    ]
    
    for region, hourly, monthly, savings, pct in regions:
        table.add_row(
            region,
            f"${hourly:.3f}",
            f"${monthly:.2f}",
            f"${savings:.2f}" if isinstance(savings, float) else savings,
            pct,
        )
    
    console.print(table)
    console.print("\n[bold cyan]💡 Recommendation:[/bold cyan] Moving to [green]eastus[/green] would save [green]$1,892.16/year[/green]\n")


def demo_sku_ranking():
    """Demonstrate SKU ranking output."""
    create_header()
    
    console.print("\n[bold]Finding best SKUs for:[/bold] 4 vCPUs, 16GB RAM in westeurope\n")
    
    table = Table(
        title="📊 Top 10 SKUs for 4 vCPUs / 16GB RAM",
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
    
    skus = [
        ("1", "Standard_D4as_v5", "4", "16", "V1,V2", "Premium, AccelNet", "$0.154", "$112.42"),
        ("2", "Standard_D4s_v5", "4", "16", "V1,V2", "Premium, AccelNet", "$0.173", "$126.29"),
        ("3", "Standard_D4ds_v5", "4", "16", "V1,V2", "Premium, AccelNet", "$0.194", "$141.62"),
        ("4", "Standard_D4as_v4", "4", "16", "V1,V2", "Premium, AccelNet", "$0.169", "$123.37"),
        ("5", "Standard_D4s_v4", "4", "16", "V1,V2", "Premium, AccelNet", "$0.192", "$140.16"),
        ("6", "Standard_D4ds_v4", "4", "16", "V1,V2", "Premium, AccelNet", "$0.211", "$154.03"),
        ("7", "Standard_E4s_v5", "4", "32", "V1,V2", "Premium, AccelNet", "$0.226", "$164.98"),
        ("8", "Standard_D4s_v3", "4", "16", "V1,V2", "Premium", "$0.201", "$146.73"),
        ("9", "Standard_E4as_v5", "4", "32", "V1,V2", "Premium, AccelNet", "$0.202", "$147.46"),
        ("10", "Standard_D4_v3", "4", "16", "V1,V2", "-", "$0.184", "$134.32"),
    ]
    
    for row in skus:
        table.add_row(*row)
    
    console.print(table)
    
    console.print("\n[bold cyan]💡 Summary:[/bold cyan]")
    console.print("  • Cheapest option: [green]Standard_D4as_v5[/green] at $112.42/month")
    console.print("  • Total options found: 28")
    console.print("  • Recommended (newest gen): [green]Standard_D4as_v5[/green] at $112.42/month\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "regions":
        demo_region_comparison()
    elif len(sys.argv) > 1 and sys.argv[1] == "skus":
        demo_sku_ranking()
    else:
        demo_analysis()
