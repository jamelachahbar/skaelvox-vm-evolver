"""
Configuration and settings for Azure VM Rightsizer CLI.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Azure Authentication
    azure_subscription_id: Optional[str] = Field(default=None, alias="AZURE_SUBSCRIPTION_ID")
    azure_tenant_id: Optional[str] = Field(default=None, alias="AZURE_TENANT_ID")
    azure_client_id: Optional[str] = Field(default=None, alias="AZURE_CLIENT_ID")
    azure_client_secret: Optional[str] = Field(default=None, alias="AZURE_CLIENT_SECRET")
    
    # AI Configuration
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    ai_model: str = Field(default="claude-sonnet-4-20250514", alias="AI_MODEL")
    
    # Analysis Settings
    lookback_days: int = Field(default=30, alias="LOOKBACK_DAYS")
    cpu_threshold_low: float = Field(default=20.0, alias="CPU_THRESHOLD_LOW")
    cpu_threshold_high: float = Field(default=80.0, alias="CPU_THRESHOLD_HIGH")
    memory_threshold_low: float = Field(default=20.0, alias="MEMORY_THRESHOLD_LOW")
    memory_threshold_high: float = Field(default=80.0, alias="MEMORY_THRESHOLD_HIGH")
    
    # SKU Filtering Options (defaults: check disk and network requirements)
    check_disk_requirements: bool = Field(default=True, alias="CHECK_DISK_REQUIREMENTS")
    check_network_requirements: bool = Field(default=True, alias="CHECK_NETWORK_REQUIREMENTS")
    prefer_same_family: bool = Field(default=False, alias="PREFER_SAME_FAMILY")
    allow_burstable: bool = Field(default=True, alias="ALLOW_BURSTABLE")
    
    # 🦎✨ Skælvox Mode - Adaptive Generation Evolution (ENABLED BY DEFAULT!)
    # Named after the mythical cosmic chameleon that naturally evolves to newer generations
    # while gracefully adapting when the ideal isn't available
    skaelvox_enabled: bool = Field(default=True, alias="SKAELVOX_ENABLED")  # Enabled by default!
    skaelvox_leap: int = Field(default=2, alias="SKAELVOX_LEAP")  # How many generations to leap forward (1-3)
    skaelvox_fallback: bool = Field(default=True, alias="SKAELVOX_FALLBACK")  # Fall back if ideal not available
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# VM Generation mappings (old -> new)
VM_GENERATION_MAP = {
    # D-series evolution
    "Standard_D": "Standard_D",
    "Standard_DS": "Standard_D",
    "Standard_D1": "Standard_D2s_v5",
    "Standard_D2": "Standard_D2s_v5",
    "Standard_D3": "Standard_D4s_v5",
    "Standard_D4": "Standard_D8s_v5",
    "Standard_D11": "Standard_D2s_v5",
    "Standard_D12": "Standard_D4s_v5",
    "Standard_D13": "Standard_D8s_v5",
    "Standard_D14": "Standard_D16s_v5",
    "Standard_D1_v2": "Standard_D2s_v5",
    "Standard_D2_v2": "Standard_D2s_v5",
    "Standard_D3_v2": "Standard_D4s_v5",
    "Standard_D4_v2": "Standard_D8s_v5",
    "Standard_D5_v2": "Standard_D16s_v5",
    "Standard_D2_v3": "Standard_D2s_v5",
    "Standard_D4_v3": "Standard_D4s_v5",
    "Standard_D8_v3": "Standard_D8s_v5",
    "Standard_D16_v3": "Standard_D16s_v5",
    "Standard_D32_v3": "Standard_D32s_v5",
    "Standard_D2s_v3": "Standard_D2s_v5",
    "Standard_D4s_v3": "Standard_D4s_v5",
    "Standard_D8s_v3": "Standard_D8s_v5",
    "Standard_D16s_v3": "Standard_D16s_v5",
    "Standard_D32s_v3": "Standard_D32s_v5",
    "Standard_D2_v4": "Standard_D2s_v5",
    "Standard_D4_v4": "Standard_D4s_v5",
    "Standard_D8_v4": "Standard_D8s_v5",
    "Standard_D16_v4": "Standard_D16s_v5",
    "Standard_D32_v4": "Standard_D32s_v5",
    "Standard_D2s_v4": "Standard_D2s_v5",
    "Standard_D4s_v4": "Standard_D4s_v5",
    "Standard_D8s_v4": "Standard_D8s_v5",
    "Standard_D16s_v4": "Standard_D16s_v5",
    "Standard_D32s_v4": "Standard_D32s_v5",
    
    # E-series (memory optimized) evolution
    "Standard_E2_v3": "Standard_E2s_v5",
    "Standard_E4_v3": "Standard_E4s_v5",
    "Standard_E8_v3": "Standard_E8s_v5",
    "Standard_E16_v3": "Standard_E16s_v5",
    "Standard_E32_v3": "Standard_E32s_v5",
    "Standard_E2s_v3": "Standard_E2s_v5",
    "Standard_E4s_v3": "Standard_E4s_v5",
    "Standard_E8s_v3": "Standard_E8s_v5",
    "Standard_E16s_v3": "Standard_E16s_v5",
    "Standard_E32s_v3": "Standard_E32s_v5",
    "Standard_E2_v4": "Standard_E2s_v5",
    "Standard_E4_v4": "Standard_E4s_v5",
    "Standard_E8_v4": "Standard_E8s_v5",
    "Standard_E16_v4": "Standard_E16s_v5",
    "Standard_E32_v4": "Standard_E32s_v5",
    "Standard_E2s_v4": "Standard_E2s_v5",
    "Standard_E4s_v4": "Standard_E4s_v5",
    "Standard_E8s_v4": "Standard_E8s_v5",
    "Standard_E16s_v4": "Standard_E16s_v5",
    "Standard_E32s_v4": "Standard_E32s_v5",
    
    # F-series (compute optimized) evolution
    "Standard_F1": "Standard_F2s_v2",
    "Standard_F2": "Standard_F2s_v2",
    "Standard_F4": "Standard_F4s_v2",
    "Standard_F8": "Standard_F8s_v2",
    "Standard_F16": "Standard_F16s_v2",
    "Standard_F1s": "Standard_F2s_v2",
    "Standard_F2s": "Standard_F2s_v2",
    "Standard_F4s": "Standard_F4s_v2",
    "Standard_F8s": "Standard_F8s_v2",
    "Standard_F16s": "Standard_F16s_v2",
    
    # B-series (burstable)
    "Standard_B1s": "Standard_B2s_v2",
    "Standard_B1ms": "Standard_B2ms_v2",
    "Standard_B2s": "Standard_B2s_v2",
    "Standard_B2ms": "Standard_B2ms_v2",
    "Standard_B4ms": "Standard_B4ms_v2",
    "Standard_B8ms": "Standard_B8ms_v2",
    
    # A-series (legacy) -> D-series
    "Standard_A1": "Standard_D2s_v5",
    "Standard_A2": "Standard_D2s_v5",
    "Standard_A3": "Standard_D4s_v5",
    "Standard_A4": "Standard_D8s_v5",
    "Standard_A1_v2": "Standard_D2s_v5",
    "Standard_A2_v2": "Standard_D2s_v5",
    "Standard_A4_v2": "Standard_D4s_v5",
    "Standard_A8_v2": "Standard_D8s_v5",
}

# Cheaper alternative regions (comprehensive list)
REGION_ALTERNATIVES = {
    # Europe
    "westeurope": ["northeurope", "uksouth", "francecentral", "germanywestcentral", "swedencentral"],
    "northeurope": ["westeurope", "uksouth", "swedencentral", "norwayeast"],
    "uksouth": ["ukwest", "northeurope", "westeurope", "francecentral"],
    "ukwest": ["uksouth", "northeurope", "westeurope"],
    "francecentral": ["francesouth", "westeurope", "northeurope", "germanywestcentral"],
    "francesouth": ["francecentral", "westeurope", "switzerlandnorth"],
    "germanywestcentral": ["germanynorth", "westeurope", "northeurope", "switzerlandnorth"],
    "germanynorth": ["germanywestcentral", "northeurope", "westeurope"],
    "swedencentral": ["norwayeast", "northeurope", "westeurope", "uksouth", "finlandcentral"],
    "norwayeast": ["norwaywest", "swedencentral", "northeurope", "westeurope"],
    "norwaywest": ["norwayeast", "swedencentral", "northeurope"],
    "switzerlandnorth": ["switzerlandwest", "germanywestcentral", "westeurope", "francecentral"],
    "switzerlandwest": ["switzerlandnorth", "germanywestcentral", "francecentral"],
    "polandcentral": ["germanywestcentral", "swedencentral", "northeurope"],
    "italynorth": ["switzerlandnorth", "francecentral", "westeurope"],
    "spaincentral": ["francecentral", "westeurope", "uksouth"],
    "finlandcentral": ["swedencentral", "norwayeast", "northeurope"],
    
    # US
    "eastus": ["eastus2", "southcentralus", "northcentralus", "centralus", "westus2"],
    "eastus2": ["eastus", "centralus", "southcentralus", "northcentralus"],
    "westus": ["westus2", "westus3", "centralus", "southcentralus"],
    "westus2": ["westus", "westus3", "centralus", "southcentralus"],
    "westus3": ["westus2", "westus", "southcentralus"],
    "centralus": ["eastus", "eastus2", "southcentralus", "northcentralus"],
    "southcentralus": ["centralus", "eastus", "westus2", "southcentralus"],
    "northcentralus": ["centralus", "eastus", "eastus2"],
    "westcentralus": ["centralus", "westus2", "southcentralus"],
    
    # Asia Pacific
    "southeastasia": ["eastasia", "australiaeast", "japaneast", "koreacentral"],
    "eastasia": ["southeastasia", "japaneast", "koreacentral"],
    "australiaeast": ["australiasoutheast", "southeastasia", "australiacentral"],
    "australiasoutheast": ["australiaeast", "southeastasia"],
    "australiacentral": ["australiaeast", "australiasoutheast"],
    "japaneast": ["japanwest", "eastasia", "koreacentral"],
    "japanwest": ["japaneast", "eastasia"],
    "koreacentral": ["koreasouth", "japaneast", "eastasia"],
    "koreasouth": ["koreacentral", "japaneast"],
    "centralindia": ["southindia", "westindia", "southeastasia"],
    "southindia": ["centralindia", "westindia"],
    "westindia": ["centralindia", "southindia"],
    
    # Middle East & Africa
    "uaenorth": ["uaecentral", "westeurope", "southeastasia"],
    "uaecentral": ["uaenorth", "westeurope"],
    "southafricanorth": ["southafricawest", "westeurope", "uksouth"],
    "southafricawest": ["southafricanorth", "westeurope"],
    "qatarcentral": ["uaenorth", "westeurope"],
    "israelcentral": ["westeurope", "northeurope", "uaenorth"],
    
    # Americas (non-US)
    "canadacentral": ["canadaeast", "eastus", "eastus2"],
    "canadaeast": ["canadacentral", "eastus", "eastus2"],
    "brazilsouth": ["brazilsoutheast", "eastus", "eastus2"],
    "brazilsoutheast": ["brazilsouth", "eastus"],
    "mexicocentral": ["southcentralus", "eastus", "westus2"],
}

# SKU capability weights for ranking
SKU_RANKING_WEIGHTS = {
    "price": 0.35,
    "performance": 0.25,
    "generation": 0.20,
    "features": 0.20,
}
