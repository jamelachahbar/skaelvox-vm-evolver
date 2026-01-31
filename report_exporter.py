"""
Report exporter module for VM analysis results.
Supports multiple export formats: JSON, CSV, HTML.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from io import StringIO

from analysis_engine import AnalysisReport, RightsizingResult


class ReportExporter:
    """Export analysis reports to various formats."""
    
    def __init__(self, report: AnalysisReport):
        """Initialize exporter with an analysis report.
        
        Args:
            report: The AnalysisReport to export
        """
        self.report = report
    
    def export(self, output_path: str, output_format: Optional[str] = None) -> str:
        """Export report to file, auto-detecting format from extension.
        
        Args:
            output_path: Path to output file
            output_format: Optional format override ('json', 'csv', 'html'). 
                   If None, detected from file extension.
        
        Returns:
            Path to the exported file
        """
        # Detect format from extension if not specified
        if output_format is None:
            ext = Path(output_path).suffix.lower()
            format_map = {
                '.json': 'json',
                '.csv': 'csv', 
                '.html': 'html',
                '.htm': 'html'
            }
            output_format = format_map.get(ext, 'json')
        
        # Export based on format
        if output_format == 'json':
            return self.export_json(output_path)
        elif output_format == 'csv':
            return self.export_csv(output_path)
        elif output_format == 'html':
            return self.export_html(output_path)
        else:
            raise ValueError(f"Unsupported export format: {output_format}")
    
    def export_json(self, output_path: str) -> str:
        """Export report as JSON.
        
        Args:
            output_path: Path to output JSON file
            
        Returns:
            Path to the exported file
        """
        output_data = {
            "timestamp": self.report.timestamp.isoformat(),
            "subscription_id": self.report.subscription_id,
            "summary": {
                "total_vms": self.report.total_vms,
                "analyzed_vms": self.report.analyzed_vms,
                "vms_with_recommendations": self.report.vms_with_recommendations,
                "total_current_cost": self.report.total_current_cost,
                "total_potential_savings": self.report.total_potential_savings,  # Monthly savings
                "total_annual_savings": self.report.total_potential_savings * 12,  # Annualized (monthly * 12)
                "shutdown_candidates": self.report.shutdown_candidates,
                "rightsize_candidates": self.report.rightsize_candidates,
                "generation_upgrade_candidates": self.report.generation_upgrade_candidates,
                "region_move_candidates": self.report.region_move_candidates,
            },
            "executive_summary": self.report.executive_summary,
            "results": [
                self._format_result_json(r)
                for r in self.report.results
            ],
        }
        
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2)
        
        return output_path
    
    def export_csv(self, output_path: str) -> str:
        """Export report as CSV.
        
        Args:
            output_path: Path to output CSV file
            
        Returns:
            Path to the exported file
        """
        with open(output_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                "VM Name",
                "Resource Group",
                "Location",
                "Current SKU",
                "Current Cost (Monthly)",
                "Recommended SKU",
                "Recommended Cost (Monthly)",
                "Monthly Savings",
                "Annual Savings",
                "Savings %",
                "Recommendation Type",
                "Priority",
                "Allocation Score",
                "Confidence",
                "Avg CPU %",
                "Max CPU %",
                "Avg Memory %",
                "Current Generation",
                "Recommended Generation",
                "Deployment Feasible",
                "Constraint Issues",
                "Power State",
                "OS Type"
            ])
            
            # Write data rows
            for result in self.report.results:
                vm = result.vm
                
                # Get recommended SKU
                recommended_sku = self._get_recommended_sku(result)
                recommended_cost = self._get_recommended_cost(result)
                confidence = self._get_confidence(result)
                
                # Calculate savings percentage
                savings_pct = 0.0
                if vm.current_price_monthly and vm.current_price_monthly > 0:
                    savings_pct = (result.total_potential_savings / vm.current_price_monthly) * 100
                
                writer.writerow([
                    vm.name,
                    vm.resource_group,
                    vm.location,
                    vm.vm_size,
                    f"{vm.current_price_monthly:.2f}" if vm.current_price_monthly else "N/A",
                    recommended_sku,
                    f"{recommended_cost:.2f}" if recommended_cost else "N/A",
                    f"{result.total_potential_savings:.2f}",
                    f"{result.total_potential_savings * 12:.2f}",
                    f"{savings_pct:.1f}%",
                    result.recommendation_type or "N/A",
                    result.priority,
                    getattr(result, 'placement_score', 'Unknown'),
                    confidence,
                    f"{vm.avg_cpu:.1f}" if vm.avg_cpu else "N/A",
                    f"{vm.max_cpu:.1f}" if vm.max_cpu else "N/A",
                    f"{vm.avg_memory:.1f}" if vm.avg_memory else "N/A",
                    result.current_generation or "N/A",
                    self._get_recommended_generation(result),
                    "Yes" if result.deployment_feasible else "No",
                    "; ".join(result.constraint_issues) if result.constraint_issues else "None",
                    vm.power_state,
                    vm.os_type
                ])
        
        return output_path
    
    def export_html(self, output_path: str) -> str:
        """Export report as modern dashboard-style HTML.
        
        Args:
            output_path: Path to output HTML file
            
        Returns:
            Path to the exported file
        """
        # Calculate summary statistics
        total_monthly = self.report.total_potential_savings
        total_annual = total_monthly * 12
        savings_pct = 0.0
        if self.report.total_current_cost > 0:
            savings_pct = (total_monthly / self.report.total_current_cost) * 100
        
        # Calculate recommendation breakdown for charts
        total_recs = self.report.vms_with_recommendations or 1
        shutdown_pct = (self.report.shutdown_candidates / total_recs * 100) if total_recs else 0
        rightsize_pct = (self.report.rightsize_candidates / total_recs * 100) if total_recs else 0
        upgrade_pct = (self.report.generation_upgrade_candidates / total_recs * 100) if total_recs else 0
        region_pct = (self.report.region_move_candidates / total_recs * 100) if total_recs else 0
        no_change = self.report.analyzed_vms - self.report.vms_with_recommendations
        
        # Count by priority
        high_priority = sum(1 for r in self.report.results if r.priority == "High")
        med_priority = sum(1 for r in self.report.results if r.priority == "Medium")
        low_priority = sum(1 for r in self.report.results if r.priority == "Low")
        
        # Build HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VM Cost Optimization Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.5;
            color: #1f2937;
            background: #f9fafb;
        }}
        
        .navbar {{
            background: #fff;
            border-bottom: 1px solid #e5e7eb;
            padding: 12px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .navbar .logo {{
            font-weight: 700;
            font-size: 18px;
            color: #7c3aed;
        }}
        
        .navbar .meta {{
            font-size: 13px;
            color: #6b7280;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px 32px;
        }}
        
        .summary-banner {{
            background: #fff;
            border-radius: 12px;
            padding: 24px 32px;
            margin-bottom: 24px;
            border: 1px solid #e5e7eb;
        }}
        
        .summary-banner h2 {{
            font-size: 15px;
            color: #6b7280;
            font-weight: 500;
            margin-bottom: 8px;
        }}
        
        .summary-banner .headline {{
            font-size: 24px;
            font-weight: 600;
            color: #111827;
        }}
        
        .summary-banner .headline .highlight {{
            color: #059669;
        }}
        
        .score-cards {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        
        .score-card {{
            background: #fff;
            border-radius: 12px;
            padding: 20px 24px;
            border: 1px solid #e5e7eb;
            text-align: center;
        }}
        
        .score-card .score {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        
        .score-card .score.green {{ color: #059669; }}
        .score-card .score.yellow {{ color: #d97706; }}
        .score-card .score.red {{ color: #dc2626; }}
        .score-card .score.purple {{ color: #7c3aed; }}
        .score-card .score.blue {{ color: #2563eb; }}
        
        .score-card .label {{
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 12px;
        }}
        
        .score-card .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .badge-green {{ background: #d1fae5; color: #065f46; }}
        .badge-yellow {{ background: #fef3c7; color: #92400e; }}
        .badge-red {{ background: #fee2e2; color: #991b1b; }}
        .badge-gray {{ background: #f3f4f6; color: #374151; }}
        
        .dashboard-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }}
        
        .card {{
            background: #fff;
            border-radius: 12px;
            padding: 24px;
            border: 1px solid #e5e7eb;
        }}
        
        .card-title {{
            font-size: 14px;
            font-weight: 600;
            color: #374151;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .card-title .icon {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #7c3aed;
        }}
        
        .chart-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 32px;
        }}
        
        .donut-chart {{
            position: relative;
            width: 180px;
            height: 180px;
        }}
        
        .donut-chart svg {{
            transform: rotate(-90deg);
        }}
        
        .donut-chart svg circle.segment {{
            transition: all 0.3s ease;
            cursor: pointer;
        }}
        
        .donut-chart svg circle.segment:hover {{
            stroke-width: 25;
            filter: brightness(1.15) drop-shadow(0 0 8px currentColor);
        }}
        
        .chart-tooltip {{
            position: fixed;
            background: #1f2937;
            color: #fff;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            pointer-events: none;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.2s;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        
        .chart-tooltip.visible {{
            opacity: 1;
        }}
        
        .donut-chart .center-text {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }}
        
        .donut-chart .center-text .value {{
            font-size: 28px;
            font-weight: 700;
            color: #111827;
        }}
        
        .donut-chart .center-text .label {{
            font-size: 12px;
            color: #6b7280;
        }}
        
        .chart-legend {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 13px;
        }}
        
        .legend-item.interactive {{
            cursor: pointer;
            padding: 6px 10px;
            margin: -6px -10px;
            border-radius: 8px;
            transition: background 0.2s;
        }}
        
        .legend-item.interactive:hover {{
            background: #f3f4f6;
        }}
        
        .legend-item.interactive.active {{
            background: #ede9fe;
        }}
        
        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }}
        
        .legend-value {{
            font-weight: 600;
            margin-left: auto;
        }}
        
        .savings-display {{
            text-align: center;
            padding: 20px;
        }}
        
        .savings-display .amount {{
            font-size: 42px;
            font-weight: 700;
            color: #059669;
            margin-bottom: 8px;
        }}
        
        .savings-display .sublabel {{
            font-size: 13px;
            color: #6b7280;
        }}
        
        .savings-breakdown {{
            display: flex;
            justify-content: center;
            gap: 32px;
            margin-top: 24px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
        
        .savings-item {{
            text-align: center;
        }}
        
        .savings-item .value {{
            font-size: 20px;
            font-weight: 600;
            color: #111827;
        }}
        
        .savings-item .label {{
            font-size: 12px;
            color: #6b7280;
        }}
        
        .table-card {{
            background: #fff;
            border-radius: 12px;
            border: 1px solid #e5e7eb;
            overflow: hidden;
        }}
        
        .table-header {{
            padding: 16px 24px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        
        .table-header h3 {{
            font-size: 14px;
            font-weight: 600;
            color: #374151;
            margin: 0;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        thead {{
            background: #f9fafb;
        }}
        
        th {{
            padding: 12px 16px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid #e5e7eb;
        }}
        
        td {{
            padding: 14px 16px;
            font-size: 14px;
            border-bottom: 1px solid #f3f4f6;
            color: #374151;
        }}
        
        tbody tr:hover {{
            background: #f9fafb;
        }}
        
        .vm-name {{
            font-weight: 600;
            color: #111827;
        }}
        
        .sku-badge {{
            display: inline-block;
            padding: 2px 8px;
            background: #f3f4f6;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px;
        }}
        
        .savings-cell {{
            color: #059669;
            font-weight: 600;
        }}
        
        .priority-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .priority-high {{ background: #fee2e2; color: #991b1b; }}
        .priority-medium {{ background: #fef3c7; color: #92400e; }}
        .priority-low {{ background: #d1fae5; color: #065f46; }}
        
        .type-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .type-rightsize {{ background: #ede9fe; color: #5b21b6; }}
        .type-shutdown {{ background: #fee2e2; color: #991b1b; }}
        .type-upgrade {{ background: #dbeafe; color: #1e40af; }}
        
        .status-ready {{ color: #059669; }}
        .status-review {{ color: #d97706; }}
        
        .executive-summary {{
            background: #fff;
            border-radius: 12px;
            padding: 24px;
            border: 1px solid #e5e7eb;
            margin-bottom: 24px;
        }}
        
        .executive-summary h3 {{
            font-size: 14px;
            font-weight: 600;
            color: #374151;
            margin-bottom: 16px;
        }}
        
        .executive-summary p {{
            font-size: 14px;
            color: #4b5563;
            line-height: 1.8;
            margin-bottom: 12px;
        }}
        
        .executive-summary p:last-child {{
            margin-bottom: 0;
        }}
        
        /* Interactive Features */
        .filters {{
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }}
        
        .filter-btn {{
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid #e5e7eb;
            background: #fff;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        
        .filter-btn:hover {{
            border-color: #7c3aed;
            color: #7c3aed;
        }}
        
        .filter-btn.active {{
            background: #7c3aed;
            color: #fff;
            border-color: #7c3aed;
        }}
        
        .search-box {{
            padding: 8px 14px;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            font-size: 13px;
            width: 220px;
        }}
        
        .search-box:focus {{
            outline: none;
            border-color: #7c3aed;
            box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1);
        }}
        
        th.sortable {{
            cursor: pointer;
            user-select: none;
        }}
        
        th.sortable:hover {{
            background: #f3f4f6;
        }}
        
        th.sortable::after {{
            content: ' ↕';
            opacity: 0.3;
            font-size: 10px;
        }}
        
        th.sort-asc::after {{
            content: ' ↑';
            opacity: 1;
        }}
        
        th.sort-desc::after {{
            content: ' ↓';
            opacity: 1;
        }}
        
        .expandable {{
            cursor: pointer;
        }}
        
        .expand-icon {{
            display: inline-block;
            width: 20px;
            height: 20px;
            text-align: center;
            line-height: 18px;
            border-radius: 4px;
            background: #f3f4f6;
            margin-right: 8px;
            font-size: 12px;
            transition: transform 0.15s;
        }}
        
        .expand-icon.open {{
            transform: rotate(90deg);
        }}
        
        .detail-row {{
            display: none;
            background: #f9fafb;
        }}
        
        .detail-row.open {{
            display: table-row;
        }}
        
        .detail-content {{
            padding: 20px 24px;
        }}
        
        .detail-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }}
        
        .detail-section h4 {{
            font-size: 12px;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            margin-bottom: 8px;
        }}
        
        .detail-section p {{
            font-size: 13px;
            color: #374151;
            line-height: 1.6;
        }}
        
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 13px;
        }}
        
        .metric-label {{ color: #6b7280; }}
        .metric-value {{ font-weight: 500; color: #111827; }}
        
        .no-results {{
            text-align: center;
            padding: 40px;
            color: #6b7280;
            display: none;
        }}
        
        .stats-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            font-size: 13px;
            color: #6b7280;
        }}
        
        .footer {{
            text-align: center;
            padding: 24px;
            color: #9ca3af;
            font-size: 12px;
        }}
        
        @media (max-width: 1024px) {{
            .score-cards {{ grid-template-columns: repeat(3, 1fr); }}
            .dashboard-grid {{ grid-template-columns: 1fr; }}
        }}
        
        @media print {{
            body {{ background: #fff; }}
            .navbar {{ display: none; }}
        }}
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="logo">Skælvox VM Evolver</div>
        <div class="meta">Report generated {self.report.timestamp.strftime('%B %d, %Y at %H:%M UTC')}</div>
    </nav>
    
    <div class="container">
        <div class="summary-banner">
            <h2>VM Cost Optimization Summary</h2>
            <div class="headline">
                {self.report.vms_with_recommendations} optimization opportunities found across {self.report.analyzed_vms} VMs. 
                <span class="highlight">${total_annual:,.0f}/yr potential savings</span>
            </div>
        </div>
        
        <div class="score-cards">
            <div class="score-card">
                <div class="score purple">{self.report.analyzed_vms}</div>
                <div class="label">VMs Analyzed</div>
                <span class="badge badge-gray">Total</span>
            </div>
            <div class="score-card">
                <div class="score blue">{self.report.vms_with_recommendations}</div>
                <div class="label">With Recommendations</div>
                <span class="badge badge-gray">{self.report.vms_with_recommendations / max(self.report.analyzed_vms, 1) * 100:.0f}%</span>
            </div>
            <div class="score-card">
                <div class="score green">{high_priority}</div>
                <div class="label">High Priority</div>
                <span class="badge badge-green">Quick Wins</span>
            </div>
            <div class="score-card">
                <div class="score yellow">{med_priority}</div>
                <div class="label">Medium Priority</div>
                <span class="badge badge-yellow">Review</span>
            </div>
            <div class="score-card">
                <div class="score">{low_priority}</div>
                <div class="label">Low Priority</div>
                <span class="badge badge-gray">Optional</span>
            </div>
        </div>
        
        <div class="dashboard-grid">
            <div class="card">
                <div class="card-title"><span class="icon"></span>Recommendation Breakdown</div>
                <div class="chart-container">
                    <div class="donut-chart" id="donutChart">
                        <svg width="180" height="180" viewBox="0 0 180 180">
                            <circle cx="90" cy="90" r="70" fill="none" stroke="#e5e7eb" stroke-width="20"/>
                            <circle class="segment" data-label="Rightsize" data-value="{self.report.rightsize_candidates}" data-pct="{self.report.rightsize_candidates / max(self.report.analyzed_vms, 1) * 100:.1f}" cx="90" cy="90" r="70" fill="none" stroke="#7c3aed" stroke-width="20"
                                stroke-dasharray="{self.report.rightsize_candidates / max(self.report.analyzed_vms, 1) * 440} 440"
                                stroke-linecap="round"
                                onmouseenter="showTooltip(event, this)" onmouseleave="hideTooltip()" onmousemove="moveTooltip(event)"/>
                            <circle class="segment" data-label="Shutdown" data-value="{self.report.shutdown_candidates}" data-pct="{self.report.shutdown_candidates / max(self.report.analyzed_vms, 1) * 100:.1f}" cx="90" cy="90" r="70" fill="none" stroke="#f472b6" stroke-width="20"
                                stroke-dasharray="{self.report.shutdown_candidates / max(self.report.analyzed_vms, 1) * 440} 440"
                                stroke-dashoffset="-{self.report.rightsize_candidates / max(self.report.analyzed_vms, 1) * 440}"
                                stroke-linecap="round"
                                onmouseenter="showTooltip(event, this)" onmouseleave="hideTooltip()" onmousemove="moveTooltip(event)"/>
                            <circle class="segment" data-label="Gen Upgrade" data-value="{self.report.generation_upgrade_candidates}" data-pct="{self.report.generation_upgrade_candidates / max(self.report.analyzed_vms, 1) * 100:.1f}" cx="90" cy="90" r="70" fill="none" stroke="#60a5fa" stroke-width="20"
                                stroke-dasharray="{self.report.generation_upgrade_candidates / max(self.report.analyzed_vms, 1) * 440} 440"
                                stroke-dashoffset="-{(self.report.rightsize_candidates + self.report.shutdown_candidates) / max(self.report.analyzed_vms, 1) * 440}"
                                stroke-linecap="round"
                                onmouseenter="showTooltip(event, this)" onmouseleave="hideTooltip()" onmousemove="moveTooltip(event)"/>
                            <circle class="segment" data-label="No Change" data-value="{no_change}" data-pct="{no_change / max(self.report.analyzed_vms, 1) * 100:.1f}" cx="90" cy="90" r="70" fill="none" stroke="#e5e7eb" stroke-width="20"
                                stroke-dasharray="{no_change / max(self.report.analyzed_vms, 1) * 440} 440"
                                stroke-dashoffset="-{(self.report.rightsize_candidates + self.report.shutdown_candidates + self.report.generation_upgrade_candidates) / max(self.report.analyzed_vms, 1) * 440}"
                                stroke-linecap="round"
                                onmouseenter="showTooltip(event, this)" onmouseleave="hideTooltip()" onmousemove="moveTooltip(event)"/>
                        </svg>
                        <div class="center-text" id="donutCenter">
                            <div class="value" id="centerValue">{self.report.vms_with_recommendations}</div>
                            <div class="label" id="centerLabel">total</div>
                        </div>
                    </div>
                    <div class="chart-legend">
                        <div class="legend-item interactive" data-type="rightsize" onclick="filterByType('rightsize')">
                            <span class="legend-dot" style="background: #7c3aed"></span>
                            <span>Rightsize</span>
                            <span class="legend-value">{self.report.rightsize_candidates}</span>
                        </div>
                        <div class="legend-item interactive" data-type="shutdown" onclick="filterByType('shutdown')">
                            <span class="legend-dot" style="background: #f472b6"></span>
                            <span>Shutdown</span>
                            <span class="legend-value">{self.report.shutdown_candidates}</span>
                        </div>
                        <div class="legend-item interactive" data-type="generation-upgrade" onclick="filterByType('generation-upgrade')">
                            <span class="legend-dot" style="background: #60a5fa"></span>
                            <span>Generation Upgrade</span>
                            <span class="legend-value">{self.report.generation_upgrade_candidates}</span>
                        </div>
                        <div class="legend-item interactive" data-type="" onclick="filterByType('')">
                            <span class="legend-dot" style="background: #e5e7eb"></span>
                            <span>No Change Needed</span>
                            <span class="legend-value">{no_change}</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-title"><span class="icon" style="background: #059669"></span>Cost Impact</div>
                <div class="savings-display">
                    <div class="amount">${total_annual:,.0f}</div>
                    <div class="sublabel">estimated annual savings</div>
                </div>
                <div class="savings-breakdown">
                    <div class="savings-item">
                        <div class="value">${total_monthly:,.0f}</div>
                        <div class="label">Monthly Savings</div>
                    </div>
                    <div class="savings-item">
                        <div class="value">${self.report.total_current_cost:,.0f}</div>
                        <div class="label">Current Monthly Cost</div>
                    </div>
                    <div class="savings-item">
                        <div class="value">{savings_pct:.1f}%</div>
                        <div class="label">Reduction</div>
                    </div>
                </div>
            </div>
        </div>
"""
        
        # Add executive summary if available
        if self.report.executive_summary:
            summary_text = self._clean_executive_summary(self.report.executive_summary)
            # Split into paragraphs and wrap each in <p> tags
            paragraphs = [p.strip() for p in summary_text.split('\n\n') if p.strip()]
            if len(paragraphs) == 1:
                # Try splitting on single newlines if no double newlines
                paragraphs = [p.strip() for p in summary_text.split('\n') if p.strip()]
            if not paragraphs:
                paragraphs = [summary_text]
            paragraphs_html = ''.join(f'<p>{self._html_escape(p)}</p>' for p in paragraphs)
            html += f"""
        <div class="executive-summary">
            <h3>Executive Summary</h3>
            {paragraphs_html}
        </div>
"""
        
        # Add recommendations table with interactive controls
        html += """
        <div class="table-card">
            <div class="table-header">
                <h3>VM Recommendations</h3>
                <div class="filters">
                    <input type="text" class="search-box" id="searchBox" placeholder="Search VMs..." oninput="filterTable()">
                    <button class="filter-btn active" data-filter="all" onclick="setFilter('all', this)">All</button>
                    <button class="filter-btn" data-filter="high" onclick="setFilter('high', this)">High Priority</button>
                    <button class="filter-btn" data-filter="medium" onclick="setFilter('medium', this)">Medium</button>
                    <button class="filter-btn" data-filter="low" onclick="setFilter('low', this)">Low</button>
                </div>
            </div>
            <div class="stats-row">
                <span id="visibleCount">Showing all recommendations</span>
                <span>Click any row for details</span>
            </div>
            <table id="vmTable">
                <thead>
                    <tr>
                        <th class="sortable" data-col="0" onclick="sortTable(0)">VM Name</th>
                        <th class="sortable" data-col="1" onclick="sortTable(1)">Resource Group</th>
                        <th class="sortable" data-col="2" onclick="sortTable(2)">Current SKU</th>
                        <th class="sortable" data-col="3" onclick="sortTable(3)">Recommended SKU</th>
                        <th class="sortable" data-col="4" onclick="sortTable(4)">Type</th>
                        <th class="sortable" data-col="5" onclick="sortTable(5, 'number')">Est. Savings</th>
                        <th class="sortable" data-col="6" onclick="sortTable(6)">Priority</th>
                        <th class="sortable" data-col="7" onclick="sortTable(7)">Allocation</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="tableBody">
"""
        
        # Add table rows
        row_id = 0
        for result in self.report.results:
            vm = result.vm
            recommended_sku = self._get_recommended_sku(result)
            
            # Type badge
            rec_type = result.recommendation_type or '-'
            type_class = rec_type.replace('_', '-') if rec_type != '-' else ''
            if rec_type == 'rightsize':
                type_html = '<span class="type-badge type-rightsize">Rightsize</span>'
            elif rec_type == 'shutdown':
                type_html = '<span class="type-badge type-shutdown">Shutdown</span>'
            elif rec_type == 'generation_upgrade':
                type_html = '<span class="type-badge type-upgrade">Upgrade</span>'
            else:
                type_html = '-'
            
            # Priority badge
            priority_class = result.priority.lower()
            
            # Status
            if result.deployment_feasible:
                status = '<span class="status-ready">Ready</span>'
            elif result.constraint_issues:
                status = '<span class="status-review">Review</span>'
            else:
                status = '-'
            
            # Placement Score (Allocation)
            placement_score = getattr(result, 'placement_score', 'Unknown')
            if placement_score == 'High':
                allocation_html = '<span class="status-ready">🟢 High</span>'
            elif placement_score == 'Medium':
                allocation_html = '<span style="color: #d97706;">🟡 Medium</span>'
            elif placement_score == 'Low':
                allocation_html = '<span style="color: #dc2626;">🔴 Low</span>'
            else:
                allocation_html = '-'
            
            # Savings
            savings_val = result.total_potential_savings if result.total_potential_savings else 0
            savings_html = f'<span class="savings-cell">${savings_val:,.0f}/mo</span>' if savings_val > 0 else '-'
            
            # AI recommendation details
            ai_reasoning = ''
            ai_decision = ''
            ai_alternatives = ''
            if result.ai_recommendation:
                ai_rec = result.ai_recommendation
                ai_reasoning = self._html_escape(ai_rec.reasoning or '')
                ai_decision = self._html_escape(getattr(ai_rec, 'decision_summary', '') or '')
                options = getattr(ai_rec, 'options', []) or []
                # Options is a list of dicts - extract the SKU names
                if options:
                    alt_names = [str(opt.get('sku', opt)) if isinstance(opt, dict) else str(opt) for opt in options[:3]]
                    ai_alternatives = ', '.join(alt_names)
                else:
                    ai_alternatives = 'N/A'
            
            # Constraint issues
            constraints = ', '.join(result.constraint_issues) if result.constraint_issues else 'None'
            
            html += f"""
                    <tr class="expandable" data-row="{row_id}" data-priority="{priority_class}" data-type="{type_class}" onclick="toggleDetail({row_id})">
                        <td><span class="expand-icon" id="icon-{row_id}">▶</span><span class="vm-name">{self._html_escape(vm.name)}</span></td>
                        <td>{self._html_escape(vm.resource_group)}</td>
                        <td><span class="sku-badge">{self._html_escape(vm.vm_size)}</span></td>
                        <td><span class="sku-badge">{self._html_escape(recommended_sku)}</span></td>
                        <td>{type_html}</td>
                        <td data-value="{savings_val}">{savings_html}</td>
                        <td><span class="priority-badge priority-{priority_class}">{result.priority}</span></td>
                        <td>{allocation_html}</td>
                        <td>{status}</td>
                    </tr>
                    <tr class="detail-row" id="detail-{row_id}">
                        <td colspan="9">
                            <div class="detail-content">
                                <div class="detail-grid">
                                    <div class="detail-section">
                                        <h4>VM Metrics</h4>
                                        <div class="metric-row">
                                            <span class="metric-label">Avg CPU:</span>
                                            <span class="metric-value">{f'{vm.avg_cpu:.1f}%' if vm.avg_cpu else 'N/A'}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Max CPU:</span>
                                            <span class="metric-value">{f'{vm.max_cpu:.1f}%' if vm.max_cpu else 'N/A'}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Avg Memory:</span>
                                            <span class="metric-value">{f'{vm.avg_memory:.1f}%' if vm.avg_memory else 'N/A'}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Max Memory:</span>
                                            <span class="metric-value">{f'{vm.max_memory:.1f}%' if vm.max_memory else 'N/A'}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Location:</span>
                                            <span class="metric-value">{vm.location}</span>
                                        </div>
                                    </div>
                                    <div class="detail-section">
                                        <h4>AI Analysis</h4>
                                        <p>{ai_reasoning if ai_reasoning else 'No AI analysis available.'}</p>
                                        {f'<p><strong>Decision:</strong> {ai_decision}</p>' if ai_decision else ''}
                                        {f'<p><strong>Alternatives:</strong> {ai_alternatives}</p>' if ai_alternatives != 'N/A' else ''}
                                    </div>
                                    <div class="detail-section">
                                        <h4>Deployment Info</h4>
                                        <div class="metric-row">
                                            <span class="metric-label">Feasible:</span>
                                            <span class="metric-value">{'Yes' if result.deployment_feasible else 'No'}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Allocation Score:</span>
                                            <span class="metric-value">{allocation_html}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Constraints:</span>
                                            <span class="metric-value">{constraints}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Annual Savings:</span>
                                            <span class="metric-value">${savings_val * 12:,.0f}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </td>
                    </tr>
"""
            row_id += 1
        
        html += """
                </tbody>
            </table>
            <div class="no-results" id="noResults">No VMs match your filters</div>
        </div>
        
        <div class="footer">
            <p>Generated by Skælvox VM Evolver · Subscription: """ + self._html_escape(self.report.subscription_id) + """</p>
        </div>
    </div>
    
    <!-- Tooltip for donut chart -->
    <div class="chart-tooltip" id="chartTooltip"></div>
    
    <script>
        let currentFilter = 'all';
        let sortCol = -1;
        let sortAsc = true;
        const originalCenterValue = document.getElementById('centerValue').textContent;
        const originalCenterLabel = document.getElementById('centerLabel').textContent;
        
        // Donut chart interactivity
        function showTooltip(event, el) {
            const tooltip = document.getElementById('chartTooltip');
            const label = el.dataset.label;
            const value = el.dataset.value;
            const pct = el.dataset.pct;
            tooltip.innerHTML = `<strong>${label}</strong>: ${value} VMs (${pct}%)`;
            tooltip.classList.add('visible');
            
            // Update center text
            document.getElementById('centerValue').textContent = value;
            document.getElementById('centerLabel').textContent = label;
        }
        
        function hideTooltip() {
            document.getElementById('chartTooltip').classList.remove('visible');
            // Restore original center text
            document.getElementById('centerValue').textContent = originalCenterValue;
            document.getElementById('centerLabel').textContent = originalCenterLabel;
        }
        
        function moveTooltip(event) {
            const tooltip = document.getElementById('chartTooltip');
            tooltip.style.left = (event.clientX + 15) + 'px';
            tooltip.style.top = (event.clientY - 10) + 'px';
        }
        
        function setFilter(filter, btn) {
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterTable();
        }
        
        function filterTable() {
            const search = document.getElementById('searchBox').value.toLowerCase();
            const rows = document.querySelectorAll('#tableBody tr.expandable');
            let visible = 0;
            
            rows.forEach(row => {
                const priority = row.dataset.priority;
                const text = row.textContent.toLowerCase();
                const detailRow = document.getElementById('detail-' + row.dataset.row);
                
                const matchesFilter = currentFilter === 'all' || priority === currentFilter;
                const matchesSearch = search === '' || text.includes(search);
                
                if (matchesFilter && matchesSearch) {
                    row.style.display = '';
                    visible++;
                } else {
                    row.style.display = 'none';
                    detailRow.classList.remove('open');
                    document.getElementById('icon-' + row.dataset.row).classList.remove('open');
                }
            });
            
            document.getElementById('visibleCount').textContent = 
                visible === rows.length ? 'Showing all recommendations' : 
                `Showing ${visible} of ${rows.length} recommendations`;
            
            document.getElementById('noResults').style.display = visible === 0 ? 'block' : 'none';
        }
        
        function toggleDetail(rowId) {
            const detail = document.getElementById('detail-' + rowId);
            const icon = document.getElementById('icon-' + rowId);
            detail.classList.toggle('open');
            icon.classList.toggle('open');
        }
        
        function sortTable(colIndex, type = 'string') {
            const table = document.getElementById('vmTable');
            const tbody = document.getElementById('tableBody');
            const rows = Array.from(tbody.querySelectorAll('tr.expandable'));
            const headers = table.querySelectorAll('th.sortable');
            
            // Toggle direction or set new column
            if (sortCol === colIndex) {
                sortAsc = !sortAsc;
            } else {
                sortCol = colIndex;
                sortAsc = true;
            }
            
            // Update header icons
            headers.forEach((h, i) => {
                h.classList.remove('sort-asc', 'sort-desc');
                if (i === colIndex) {
                    h.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
                }
            });
            
            // Sort rows
            rows.sort((a, b) => {
                let aVal, bVal;
                const aCell = a.cells[colIndex];
                const bCell = b.cells[colIndex];
                
                if (type === 'number') {
                    aVal = parseFloat(aCell.dataset.value) || 0;
                    bVal = parseFloat(bCell.dataset.value) || 0;
                } else {
                    aVal = aCell.textContent.trim().toLowerCase();
                    bVal = bCell.textContent.trim().toLowerCase();
                }
                
                if (aVal < bVal) return sortAsc ? -1 : 1;
                if (aVal > bVal) return sortAsc ? 1 : -1;
                return 0;
            });
            
            // Re-append rows (with their detail rows)
            rows.forEach(row => {
                const detailRow = document.getElementById('detail-' + row.dataset.row);
                tbody.appendChild(row);
                tbody.appendChild(detailRow);
            });
        }
        
        // Filter table by recommendation type (from legend clicks)
        let currentTypeFilter = null;
        function filterByType(type) {
            const legendItems = document.querySelectorAll('.legend-item.interactive');
            
            // Toggle filter
            if (currentTypeFilter === type) {
                currentTypeFilter = null;
                legendItems.forEach(item => item.classList.remove('active'));
            } else {
                currentTypeFilter = type;
                legendItems.forEach(item => {
                    item.classList.toggle('active', item.dataset.type === type);
                });
            }
            
            filterTableByType();
        }
        
        function filterTableByType() {
            const search = document.getElementById('searchBox').value.toLowerCase();
            const rows = document.querySelectorAll('#tableBody tr.expandable');
            let visible = 0;
            
            rows.forEach(row => {
                const priority = row.dataset.priority;
                const type = row.dataset.type;
                const text = row.textContent.toLowerCase();
                const detailRow = document.getElementById('detail-' + row.dataset.row);
                
                const matchesPriority = currentFilter === 'all' || priority === currentFilter;
                const matchesSearch = search === '' || text.includes(search);
                const matchesType = currentTypeFilter === null || type === currentTypeFilter;
                
                if (matchesPriority && matchesSearch && matchesType) {
                    row.style.display = '';
                    visible++;
                } else {
                    row.style.display = 'none';
                    detailRow.classList.remove('open');
                    document.getElementById('icon-' + row.dataset.row).classList.remove('open');
                }
            });
            
            document.getElementById('visibleCount').textContent = 
                visible === rows.length ? 'Showing all recommendations' : 
                `Showing ${visible} of ${rows.length} recommendations`;
            
            document.getElementById('noResults').style.display = visible === 0 ? 'block' : 'none';
        }
        
        // Override filterTable to use combined filtering
        function filterTable() {
            filterTableByType();
        }
    </script>
</body>
</html>
"""
        
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(html)
        
        return output_path
    
    def _clean_executive_summary(self, summary: str) -> str:
        """Clean up AI-generated executive summary to be more readable."""
        import re
        # Remove JSON artifacts
        if summary.startswith('{'):
            # Try to extract just the summary text from JSON
            try:
                data = json.loads(summary)
                if isinstance(data, dict):
                    if 'summary' in data:
                        return data['summary']
                    if 'executiveSummary' in data:
                        es = data['executiveSummary']
                        if isinstance(es, dict) and 'summary' in es:
                            return es['summary']
            except json.JSONDecodeError:
                pass
        
        # Remove markdown-style formatting
        summary = re.sub(r'\*\*([^*]+)\*\*', r'\1', summary)
        summary = re.sub(r'\\n', ' ', summary)
        summary = summary.replace('  ', ' ')
        return summary.strip()
    
    def _format_result_json(self, result: RightsizingResult) -> Dict[str, Any]:
        """Format a single result for JSON export."""
        vm = result.vm
        
        return {
            "vm_name": vm.name,
            "resource_group": vm.resource_group,
            "location": vm.location,
            "current_sku": vm.vm_size,
            "os_type": vm.os_type,
            "power_state": vm.power_state,
            "current_monthly_cost": vm.current_price_monthly,
            "recommendation_type": result.recommendation_type,
            "priority": result.priority,
            "placement_score": getattr(result, 'placement_score', 'Unknown'),
            "placement_score_warning": getattr(result, 'placement_score_warning', False),
            "potential_monthly_savings": result.total_potential_savings,
            "potential_annual_savings": result.total_potential_savings * 12,
            "current_generation": result.current_generation,
            "recommended_generation": result.recommended_generation_upgrade,
            "deployment_feasible": result.deployment_feasible,
            "constraint_issues": result.constraint_issues,
            "metrics": {
                "avg_cpu": vm.avg_cpu,
                "max_cpu": vm.max_cpu,
                "avg_memory": vm.avg_memory,
                "max_memory": vm.max_memory,
            },
            "advisor_recommendation": {
                "recommended_sku": result.advisor_recommendation.recommended_sku if result.advisor_recommendation else None,
                "problem": result.advisor_recommendation.problem if result.advisor_recommendation else None,
                "solution": result.advisor_recommendation.solution if result.advisor_recommendation else None,
            } if result.advisor_recommendation else None,
            "ai_recommendation": {
                "recommended_sku": result.ai_recommendation.recommended_sku if result.ai_recommendation else None,
                "confidence": result.ai_recommendation.confidence if result.ai_recommendation else None,
                "estimated_monthly_savings": result.ai_recommendation.estimated_monthly_savings if result.ai_recommendation else None,
                "reasoning": result.ai_recommendation.reasoning if result.ai_recommendation else None,
            } if result.ai_recommendation else None,
            "ranked_alternatives": result.ranked_alternatives[:5],
            "cheaper_regions": [
                {"region": r[0], "monthly_price": r[1], "savings": r[2]}
                for r in result.cheaper_regions[:3]
            ],
        }
    
    def _get_recommended_sku(self, result: RightsizingResult) -> str:
        """Get the recommended SKU from a result."""
        if result.ai_recommendation:
            return result.ai_recommendation.recommended_sku
        elif result.advisor_recommendation and result.advisor_recommendation.recommended_sku:
            return result.advisor_recommendation.recommended_sku
        elif result.recommended_generation_upgrade:
            return result.recommended_generation_upgrade
        elif result.ranked_alternatives:
            return result.ranked_alternatives[0]["sku"]
        return "No change"
    
    def _get_recommended_cost(self, result: RightsizingResult) -> Optional[float]:
        """Get the recommended monthly cost from a result."""
        if result.vm.current_price_monthly:
            return result.vm.current_price_monthly - result.total_potential_savings
        return None
    
    def _get_confidence(self, result: RightsizingResult) -> str:
        """Get confidence level from a result."""
        if result.ai_recommendation:
            return result.ai_recommendation.confidence
        return "N/A"
    
    def _get_recommended_generation(self, result: RightsizingResult) -> str:
        """Get recommended generation from a result."""
        if result.recommended_generation_upgrade:
            # Extract generation from SKU name (e.g., "v5" from "Standard_D4s_v5")
            parts = result.recommended_generation_upgrade.split('_')
            for part in parts:
                if part.startswith('v') and part[1:].isdigit():
                    return part
        return "N/A"
    
    def _html_escape(self, text: str) -> str:
        """Escape HTML special characters."""
        if not text:
            return ""
        return (str(text)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#x27;"))


def export_report(report: AnalysisReport, output_path: str, output_format: Optional[str] = None) -> str:
    """Convenience function to export a report.
    
    Args:
        report: The AnalysisReport to export
        output_path: Path to output file
        output_format: Optional format ('json', 'csv', 'html'). Auto-detected if None.
    
    Returns:
        Path to the exported file
    """
    exporter = ReportExporter(report)
    return exporter.export(output_path, output_format)
