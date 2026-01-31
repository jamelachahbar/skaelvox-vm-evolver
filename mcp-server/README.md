# Skælvox VM Evolver - MCP Server

An MCP (Model Context Protocol) server that exposes Azure VM rightsizing tools for AI assistants like Claude, GitHub Copilot, and others.

## 🦎 Available Tools

| Tool | Description |
|------|-------------|
| `analyze_subscription` | Analyze all VMs in a subscription for cost optimization |
| `check_sku_availability` | Check if a VM SKU is available in a region with zones |
| `get_vm_pricing` | Get pricing for VM SKUs across regions |
| `rank_skus` | Rank SKUs by price-performance for requirements |
| `check_quota` | Check vCPU quota usage in a region |
| `compare_regions` | Compare VM pricing across Azure regions |

## 🐳 Container Usage

### Pull from GitHub Container Registry

```bash
docker pull ghcr.io/jamelachahbar/skaelvox-vm-evolver:latest
```

### Run with Azure CLI credentials

```bash
docker run -it --rm \
  -v ~/.azure:/root/.azure:ro \
  ghcr.io/jamelachahbar/skaelvox-vm-evolver:latest
```

### Run with Service Principal

```bash
docker run -it --rm \
  -e AZURE_TENANT_ID=your-tenant-id \
  -e AZURE_CLIENT_ID=your-client-id \
  -e AZURE_CLIENT_SECRET=your-client-secret \
  ghcr.io/jamelachahbar/skaelvox-vm-evolver:latest
```

## 🔧 VS Code / Copilot Integration

Add to your `settings.json`:

```json
{
  "mcp.servers": {
    "skaelvox-vm-evolver": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "${env:USERPROFILE}/.azure:/root/.azure:ro",
        "ghcr.io/jamelachahbar/skaelvox-vm-evolver:latest"
      ]
    }
  }
}
```

Or for local development:

```json
{
  "mcp.servers": {
    "skaelvox-vm-evolver": {
      "command": "python",
      "args": ["${workspaceFolder}/mcp-server/server.py"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

## 🏗️ Build from Source

```bash
# Clone the repo
git clone https://github.com/jamelachahbar/skaelvox-vm-evolver.git
cd skaelvox-vm-evolver

# Build the container
docker build -t skaelvox-vm-evolver -f mcp-server/Dockerfile .

# Test locally
python mcp-server/server.py
```

## 📦 GitHub Actions - Auto-publish

The container is automatically built and published to GHCR on every push to `main`. See `.github/workflows/docker-publish.yml`.

## 🔐 Authentication

The server uses `DefaultAzureCredential` which supports:
- Azure CLI (`az login`)
- Managed Identity (when running in Azure)
- Service Principal (via environment variables)
- VS Code Azure extension

## Example Tool Calls

### Analyze a subscription
```json
{
  "name": "analyze_subscription",
  "arguments": {
    "subscription_id": "e9b4640d-1f1f-45fe-a543-c0ea45ac34c1"
  }
}
```

### Check SKU availability
```json
{
  "name": "check_sku_availability", 
  "arguments": {
    "subscription_id": "e9b4640d-1f1f-45fe-a543-c0ea45ac34c1",
    "sku": "Standard_D4s_v5",
    "region": "swedencentral"
  }
}
```

### Rank SKUs by requirements
```json
{
  "name": "rank_skus",
  "arguments": {
    "subscription_id": "e9b4640d-1f1f-45fe-a543-c0ea45ac34c1",
    "vcpus": 4,
    "memory_gb": 16,
    "region": "westeurope"
  }
}
```
