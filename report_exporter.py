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
                "total_potential_savings": self.report.total_potential_savings,
                "total_annual_savings": self.report.total_potential_savings * 12,
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
        """Export report as HTML with embedded CSS and charts.
        
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
        
        # Build HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Azure VM Rightsizing Report - {self.report.timestamp.strftime('%Y-%m-%d')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}
        
        .header .subtitle {{
            font-size: 1.2em;
            opacity: 0.9;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            padding: 40px;
            background: #f8f9fa;
        }}
        
        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }}
        
        .stat-card h3 {{
            color: #667eea;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        
        .stat-card .value {{
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }}
        
        .stat-card.savings {{
            border-left-color: #28a745;
        }}
        
        .stat-card.savings .value {{
            color: #28a745;
        }}
        
        .content {{
            padding: 40px;
        }}
        
        .section {{
            margin-bottom: 40px;
        }}
        
        .section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }}
        
        .breakdown {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .breakdown-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .breakdown-item .label {{
            font-weight: 500;
            color: #666;
        }}
        
        .breakdown-item .count {{
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        
        thead {{
            background: #667eea;
            color: white;
        }}
        
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
        }}
        
        tbody tr:hover {{
            background-color: #f8f9fa;
        }}
        
        .priority-high {{
            color: #dc3545;
            font-weight: bold;
        }}
        
        .priority-medium {{
            color: #ffc107;
            font-weight: bold;
        }}
        
        .priority-low {{
            color: #28a745;
            font-weight: bold;
        }}
        
        .savings-cell {{
            color: #28a745;
            font-weight: bold;
        }}
        
        .status-ok {{
            color: #28a745;
        }}
        
        .status-warning {{
            color: #ffc107;
        }}
        
        .footer {{
            background: #f8f9fa;
            padding: 20px 40px;
            text-align: center;
            color: #666;
            font-size: 0.9em;
        }}
        
        .executive-summary {{
            background: #fff8e1;
            border-left: 4px solid #ffc107;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 4px;
        }}
        
        .executive-summary h3 {{
            color: #f57c00;
            margin-bottom: 10px;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        
        .badge-success {{
            background: #d4edda;
            color: #155724;
        }}
        
        .badge-warning {{
            background: #fff3cd;
            color: #856404;
        }}
        
        .badge-danger {{
            background: #f8d7da;
            color: #721c24;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🦎 Skælvox VM Evolver Report</h1>
            <div class="subtitle">Azure VM Cost Optimization Analysis</div>
            <div class="subtitle">Generated: {self.report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</div>
        </div>
        
        <div class="summary">
            <div class="stat-card">
                <h3>Total VMs</h3>
                <div class="value">{self.report.total_vms}</div>
            </div>
            <div class="stat-card">
                <h3>Analyzed VMs</h3>
                <div class="value">{self.report.analyzed_vms}</div>
            </div>
            <div class="stat-card">
                <h3>With Recommendations</h3>
                <div class="value">{self.report.vms_with_recommendations}</div>
            </div>
            <div class="stat-card">
                <h3>Current Monthly Cost</h3>
                <div class="value">${self.report.total_current_cost:,.2f}</div>
            </div>
            <div class="stat-card savings">
                <h3>Monthly Savings</h3>
                <div class="value">${total_monthly:,.2f}</div>
            </div>
            <div class="stat-card savings">
                <h3>Annual Savings</h3>
                <div class="value">${total_annual:,.2f}</div>
            </div>
            <div class="stat-card savings">
                <h3>Savings Percentage</h3>
                <div class="value">{savings_pct:.1f}%</div>
            </div>
        </div>
        
        <div class="content">
            <div class="section">
                <h2>📊 Recommendation Breakdown</h2>
                <div class="breakdown">
                    <div class="breakdown-item">
                        <span class="label">🔴 Shutdown Candidates</span>
                        <span class="count">{self.report.shutdown_candidates}</span>
                    </div>
                    <div class="breakdown-item">
                        <span class="label">📐 Rightsize Candidates</span>
                        <span class="count">{self.report.rightsize_candidates}</span>
                    </div>
                    <div class="breakdown-item">
                        <span class="label">⬆️ Generation Upgrades</span>
                        <span class="count">{self.report.generation_upgrade_candidates}</span>
                    </div>
                    <div class="breakdown-item">
                        <span class="label">🌍 Region Moves</span>
                        <span class="count">{self.report.region_move_candidates}</span>
                    </div>
                </div>
            </div>
"""
        
        # Add executive summary if available
        if self.report.executive_summary:
            html += f"""
            <div class="section">
                <div class="executive-summary">
                    <h3>🤖 AI Executive Summary</h3>
                    <p>{self._html_escape(self.report.executive_summary)}</p>
                </div>
            </div>
"""
        
        # Add recommendations table
        html += """
            <div class="section">
                <h2>💡 VM Recommendations</h2>
                <table>
                    <thead>
                        <tr>
                            <th>VM Name</th>
                            <th>Resource Group</th>
                            <th>Current SKU</th>
                            <th>Recommended</th>
                            <th>Type</th>
                            <th>Monthly Savings</th>
                            <th>Priority</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        
        # Add table rows
        for result in self.report.results:
            vm = result.vm
            recommended_sku = self._get_recommended_sku(result)
            
            # Priority class
            priority_class = f"priority-{result.priority.lower()}"
            
            # Status
            if result.deployment_feasible:
                status = '<span class="status-ok">✅ Ready</span>'
            elif result.constraint_issues:
                status = '<span class="status-warning">⚠️ Issues</span>'
            else:
                status = '-'
            
            html += f"""
                        <tr>
                            <td>{self._html_escape(vm.name)}</td>
                            <td>{self._html_escape(vm.resource_group)}</td>
                            <td>{self._html_escape(vm.vm_size)}</td>
                            <td>{self._html_escape(recommended_sku)}</td>
                            <td>{self._html_escape(result.recommendation_type or '-')}</td>
                            <td class="savings-cell">${result.total_potential_savings:,.2f}</td>
                            <td class="{priority_class}">{result.priority}</td>
                            <td>{status}</td>
                        </tr>
"""
        
        html += """
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="footer">
            <p>Generated by Skælvox VM Evolver - Azure VM Cost Optimization Tool</p>
            <p>Subscription ID: """ + self._html_escape(self.report.subscription_id) + """</p>
        </div>
    </div>
</body>
</html>
"""
        
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(html)
        
        return output_path
    
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
