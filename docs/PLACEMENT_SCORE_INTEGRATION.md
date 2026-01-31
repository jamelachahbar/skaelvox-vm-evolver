# Azure Spot Placement Score Integration

## Overview

This integration adds support for the **Azure Spot Placement Score API**, which provides real-time VM allocation probability scores to help you make informed deployment decisions before provisioning resources.

## What is the Spot Placement Score API?

The Azure Spot Placement Score API assesses the likelihood of successfully deploying VMs based on:
- **Subscription**: Your Azure subscription capacity
- **Region**: Target Azure region (e.g., eastus, westeurope)
- **SKU**: VM size (e.g., Standard_D4s_v5)
- **Zone**: Specific availability zone (optional)
- **Count**: Number of VMs you want to deploy

The API returns a score of:
- **High**: 🟢 Very likely to succeed - proceed with confidence
- **Medium**: 🟡 May succeed - have a backup plan ready
- **Low**: 🔴 Unlikely to succeed - consider alternatives or different regions/zones

## Why Use It?

### Benefits
✅ **Avoid Deployment Failures** - Check capacity before attempting deployment
✅ **Optimize Zone Selection** - Choose zones with highest success probability
✅ **Save Time** - Don't waste time on deployments that will fail
✅ **Better Planning** - Make data-driven decisions about resource placement

### Use Cases
- Pre-deployment capacity checking
- Multi-region failover planning
- Capacity-aware orchestration
- Zone selection optimization
- Development/test environment provisioning

## How to Enable

### 1. Configuration

Add to your `.env` file:
```bash
CHECK_PLACEMENT_SCORES=true
```

Or set the environment variable:
```bash
export CHECK_PLACEMENT_SCORES=true
```

### 2. Azure Permissions

Ensure your Azure credentials have access to:
- `Microsoft.Compute/locations/placementScores/spot/generate` (POST)

This is included in most standard compute roles.

## Usage Examples

### Check Single SKU Availability

```bash
# Basic availability check (without placement scores)
python main.py check-availability --sku Standard_D4s_v5 --region eastus

# With placement scores enabled
CHECK_PLACEMENT_SCORES=true python main.py check-availability -k Standard_D4s_v5 -r eastus
```

**Output with Placement Scores:**
```
╭─────────────────────────── 🔍 SKU Availability ───────────────────────────╮
│ SKU Availability Check                                                    │
│                                                                           │
│ SKU: Standard_D4s_v5                                                      │
│ Region: eastus                                                            │
│ Status: AVAILABLE                                                         │
╰───────────────────────────────────────────────────────────────────────────╯

📍 Zone Availability
╭──────┬───────────┬─────────────────┬─────────────────╮
│ Zone │ Available │ Capacity Status │ Placement Score │
├──────┼───────────┼─────────────────┼─────────────────┤
│ 1    │    ✅     │    Available    │      High       │
│ 2    │    ✅     │    Available    │     Medium      │
│ 3    │    ✅     │    Available    │       Low       │
╰──────┴───────────┴─────────────────┴─────────────────╯
```

### Check Multiple Regions

```bash
CHECK_PLACEMENT_SCORES=true python main.py check-availability-multi \
  --sku Standard_D8s_v5 \
  --regions "eastus,westeurope,southeastasia"
```

This shows placement scores across multiple regions, helping you choose the best location.

### In Your Code

```python
from availability_checker import SKUAvailabilityChecker
from config import Settings

settings = Settings()

# Initialize checker with placement scores enabled
checker = SKUAvailabilityChecker(
    subscription_id="your-sub-id",
    check_placement_scores=settings.check_placement_scores,
)

# Check availability
result = checker.check_sku_availability(
    sku_name="Standard_D4s_v5",
    region="eastus",
    check_zones=True,
)

# Access placement scores
print(f"Regional score: {result.placement_score}")
for zone, score in result.zone_placement_scores.items():
    print(f"Zone {zone}: {score}")
```

## API Details

### Endpoint
```
POST https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Compute/locations/{location}/placementScores/spot/generate?api-version=2025-06-05
```

### Request Body
```json
{
  "availabilityZones": true,
  "desiredCount": 1,
  "desiredLocations": ["eastus"],
  "desiredSizes": [
    {"sku": "Standard_D4s_v5"}
  ]
}
```

### Response Format
```json
{
  "placementScores": [
    {
      "sku": "Standard_D4s_v5",
      "location": "eastus",
      "isZonal": true,
      "zoneScores": [
        {"zone": "1", "score": "High"},
        {"zone": "2", "score": "Medium"},
        {"zone": "3", "score": "Low"}
      ]
    }
  ]
}
```

## Implementation Details

### Architecture

The integration consists of three main components:

1. **SpotPlacementScoreClient** (`azure_client.py`)
   - Handles API authentication and requests
   - Manages HTTP communication
   - Implements retry logic for transient failures

2. **SKUAvailabilityChecker** (`availability_checker.py`)
   - Orchestrates availability checks
   - Integrates placement score queries
   - Enriches results with score data

3. **Display Functions** (`availability_checker.py`)
   - Rich terminal UI with color-coded scores
   - Zone-level and regional score visualization
   - Helper function for score color mapping

### Data Flow

```
User Command
    ↓
SKUAvailabilityChecker
    ↓
1. Check SKU availability (existing)
2. Query placement scores (new) → SpotPlacementScoreClient → Azure API
    ↓
SKUAvailabilityResult (enriched with scores)
    ↓
Display Functions (show color-coded scores)
    ↓
Terminal Output
```

### Error Handling

The integration gracefully handles failures:
- **API Errors**: Returns "Unknown" scores, continues without blocking
- **Authentication Issues**: Logged as warnings, doesn't crash
- **Network Timeouts**: Retries with exponential backoff (3 attempts)
- **Missing Permissions**: Falls back to availability check only

## Performance Considerations

### API Call Frequency
- Placement score API is called **once per SKU check** (if enabled)
- Results are **not cached** (real-time capacity assessment)
- Parallel checks use concurrent workers efficiently

### Cost Implications
- API calls are subject to Azure API throttling limits
- Typically very low volume (< 100 calls per analysis run)
- No direct monetary cost for API usage

### Optimization Tips
1. **Disable when not needed**: Set `CHECK_PLACEMENT_SCORES=false` for routine checks
2. **Batch regions**: Use `check-availability-multi` instead of individual calls
3. **Cache decisions**: Store scores temporarily if making multiple related decisions

## Testing

### Unit Tests
```bash
pytest tests/test_placement_score.py -v
```

Tests cover:
- ✅ Placement score creation and defaults
- ✅ Successful API responses (zonal and regional)
- ✅ Error handling (HTTP errors, timeouts)
- ✅ Multiple SKU queries
- ✅ Mock authentication

### Demo Script
```bash
python demo_placement_score.py
```

Interactive demo showing:
- Zone-level score visualization
- Regional score display
- Score interpretation guide
- API information

### Manual Testing
```bash
# Set credentials
export AZURE_SUBSCRIPTION_ID="your-sub-id"
export AZURE_TENANT_ID="your-tenant-id"
# ... other credentials

# Enable placement scores
export CHECK_PLACEMENT_SCORES=true

# Test with real API
python main.py check-availability --sku Standard_D4s_v5 --region eastus
```

## Troubleshooting

### Scores Always Show "Unknown"

**Cause**: Placement score API call is failing

**Solutions**:
1. Check Azure credentials are valid
2. Verify subscription has proper permissions
3. Check network connectivity to Azure
4. Review logs for error details: `--log-level debug`

### Slow Performance

**Cause**: API calls add latency (typically 200-500ms per call)

**Solutions**:
1. Disable placement scores for bulk operations
2. Use `--no-zones` to skip zone-level scores
3. Increase `--workers` for parallel processing

### API Rate Limiting

**Cause**: Too many requests to placement score API

**Solutions**:
1. Reduce check frequency
2. Implement local caching if needed
3. Space out checks over time
4. Contact Azure support for limit increase

## Future Enhancements

Potential improvements for future versions:

1. **Caching**: Optional local cache for scores (with TTL)
2. **Historical Tracking**: Store scores over time in database
3. **Alerting**: Notify when scores drop below threshold
4. **Auto-selection**: Automatically choose best zone based on scores
5. **Capacity Predictions**: ML model to predict capacity trends
6. **Cost Integration**: Combine scores with pricing for optimization

## References

- [Azure Spot Placement Score API Documentation](https://learn.microsoft.com/en-us/rest/api/recommenderrp/spot-placement-scores/post)
- [Azure Virtual Machine Scale Sets - Spot Placement Score](https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/spot-placement-score)
- [Understanding Azure VM SKU Capacity Limitations](https://azureis.fun/posts/Undrstanding-And-Overcoming-Azure-VM-SKU-Capacity-Limitations/)

## Support

For issues or questions:
1. Check this documentation
2. Run the demo script: `python demo_placement_score.py`
3. Review test examples: `tests/test_placement_score.py`
4. File an issue on GitHub with logs and details

## License

This integration follows the same MIT license as the parent project.
