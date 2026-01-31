#!/usr/bin/env python3
"""
Demo script for Azure Spot Placement Score integration.

This demonstrates how the placement score feature works without requiring
actual Azure credentials. It uses mocked responses to show the functionality.
"""
from unittest.mock import Mock, MagicMock
from azure_client import SpotPlacementScoreClient, PlacementScore
from availability_checker import SKUAvailabilityResult, _get_placement_score_color
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def demo_placement_score_client():
    """Demo the SpotPlacementScoreClient with mock data."""
    console.print("\n[bold cyan]═══ Azure Spot Placement Score Client Demo ═══[/bold cyan]\n")
    
    # Create some example placement scores
    scores = [
        PlacementScore(sku="Standard_D4s_v5", location="eastus", zone="1", score="High", is_zonal=True),
        PlacementScore(sku="Standard_D4s_v5", location="eastus", zone="2", score="Medium", is_zonal=True),
        PlacementScore(sku="Standard_D4s_v5", location="eastus", zone="3", score="Low", is_zonal=True),
        PlacementScore(sku="Standard_E8s_v5", location="westeurope", score="High", is_zonal=False),
    ]
    
    console.print("[bold]Example 1: Zone-level placement scores[/bold]")
    console.print(f"SKU: Standard_D4s_v5 in eastus\n")
    
    table = Table(box=box.ROUNDED)
    table.add_column("Zone", style="cyan")
    table.add_column("Placement Score", justify="center")
    
    for score in scores[:3]:
        color = _get_placement_score_color(score.score)
        table.add_row(score.zone, f"[{color}]{score.score}[/{color}]")
    
    console.print(table)
    
    console.print("\n[bold]Example 2: Regional placement score[/bold]")
    console.print(f"SKU: {scores[3].sku} in {scores[3].location}")
    
    score_color = _get_placement_score_color(scores[3].score)
    console.print(f"[bold]🎯 Spot Placement Score:[/bold] [{score_color}]{scores[3].score}[/{score_color}]")


def demo_availability_result_with_scores():
    """Demo SKUAvailabilityResult with placement scores."""
    console.print("\n\n[bold cyan]═══ SKU Availability with Placement Scores Demo ═══[/bold cyan]\n")
    
    # Create a mock result with placement scores
    result = SKUAvailabilityResult(
        sku_name="Standard_D8s_v5",
        region="eastus2",
        is_available=True,
        available_zones=["1", "2", "3"],
        placement_score="Unknown",
        zone_placement_scores={
            "1": "High",
            "2": "High",
            "3": "Medium",
        },
        subscription_id="test-sub-id",
        subscription_name="Test Subscription",
    )
    
    header = f"""[bold]SKU Availability Check[/bold]

[bold]SKU:[/bold] {result.sku_name}
[bold]Region:[/bold] {result.region}
[bold]Status:[/bold] [green]AVAILABLE[/green]
[bold]Subscription:[/bold] {result.subscription_name}"""
    
    console.print(Panel(header, title="🔍 SKU Availability", border_style="blue"))
    
    # Zone availability table
    console.print("\n[bold cyan]📍 Zone Availability with Placement Scores[/bold cyan]")
    
    zone_table = Table(box=box.ROUNDED)
    zone_table.add_column("Zone", style="cyan")
    zone_table.add_column("Available", justify="center")
    zone_table.add_column("Placement Score", justify="center")
    
    for zone in sorted(result.available_zones):
        score = result.zone_placement_scores.get(zone, "Unknown")
        score_color = _get_placement_score_color(score)
        zone_table.add_row(
            zone,
            "✅",
            f"[{score_color}]{score}[/{score_color}]",
        )
    
    console.print(zone_table)
    
    console.print("\n[dim]💡 Tip: Zones with 'High' scores have the best deployment success probability[/dim]")


def demo_score_interpretation():
    """Demo score interpretation guide."""
    console.print("\n\n[bold cyan]═══ Placement Score Interpretation Guide ═══[/bold cyan]\n")
    
    guide_table = Table(box=box.ROUNDED, title="Score Meanings")
    guide_table.add_column("Score", style="bold")
    guide_table.add_column("Meaning")
    guide_table.add_column("Recommendation")
    
    guide_table.add_row(
        "[green]High[/green]",
        "Very likely to succeed",
        "✅ Proceed with deployment",
    )
    guide_table.add_row(
        "[yellow]Medium[/yellow]",
        "May succeed",
        "⚠️  Have backup plan ready",
    )
    guide_table.add_row(
        "[red]Low[/red]",
        "Unlikely to succeed",
        "❌ Consider alternatives",
    )
    guide_table.add_row(
        "[dim]Unknown[/dim]",
        "No data available",
        "ℹ️  Enable CHECK_PLACEMENT_SCORES",
    )
    
    console.print(guide_table)


def demo_api_info():
    """Demo API information."""
    console.print("\n\n[bold cyan]═══ Azure Spot Placement Score API Info ═══[/bold cyan]\n")
    
    info = """[bold]API Details:[/bold]
• Endpoint: POST https://management.azure.com/.../placementScores/spot/generate
• API Version: 2025-06-05
• Purpose: Assess VM deployment success probability before provisioning
• Scope: Per subscription, region, SKU, and optionally per zone

[bold]Configuration:[/bold]
Set CHECK_PLACEMENT_SCORES=true in .env to enable this feature

[bold]Benefits:[/bold]
✓ Avoid deployment failures due to capacity issues
✓ Make informed decisions about region/zone selection
✓ Optimize for deployment success rate
✓ Reduce wasted time on failed provisions"""
    
    console.print(Panel(info, border_style="blue", padding=(1, 2)))


def main():
    """Run all demos."""
    console.print("\n[bold magenta]🎯 Azure Spot Placement Score Integration Demo[/bold magenta]")
    console.print("[dim]This demo shows the new placement score feature without requiring Azure credentials[/dim]\n")
    
    demo_placement_score_client()
    demo_availability_result_with_scores()
    demo_score_interpretation()
    demo_api_info()
    
    console.print("\n[bold green]✅ Demo completed![/bold green]")
    console.print("[dim]To use this feature, set CHECK_PLACEMENT_SCORES=true in your .env file[/dim]\n")


if __name__ == "__main__":
    main()
