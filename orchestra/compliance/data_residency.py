"""
Data Residency Controls.

Enforces where data is stored and processed to comply with GDPR (EU),
PIPL (China), CCPA (California), LGPD (Brazil), and other data
sovereignty regulations. Controls model provider routing, storage
placement, and cross-border transfer validation.
"""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

__all__ = [
    "DataRegion",
    "ResidencyPolicy",
    "DataResidencyController",
    "RegionInfo",
    "CrossBorderTransfer",
]


# ---------------------------------------------------------------------------
# Data Region Enum
# ---------------------------------------------------------------------------

class DataRegion(str, Enum):
    """
    Supported data regions for storage and processing.

    Aligned with major cloud provider regions.
    """
    US_EAST = "us-east"
    US_WEST = "us-west"
    EU_WEST = "eu-west"
    EU_CENTRAL = "eu-central"
    APAC_TOKYO = "apac-tokyo"
    APAC_SINGAPORE = "apac-singapore"
    CA_CENTRAL = "ca-central"


# ---------------------------------------------------------------------------
# Region metadata
# ---------------------------------------------------------------------------

@dataclass
class RegionInfo:
    """Metadata about a data region."""
    region: DataRegion
    display_name: str
    country: str
    jurisdiction: str  # e.g., "EU", "US", "APAC", "CA"
    cloud_zones: List[str] = field(default_factory=list)
    adequacy_decision: bool = False  # EU adequacy for GDPR
    supported_providers: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "region": self.region.value,
            "display_name": self.display_name,
            "country": self.country,
            "jurisdiction": self.jurisdiction,
            "cloud_zones": self.cloud_zones,
            "adequacy_decision": self.adequacy_decision,
            "supported_providers": self.supported_providers,
        }


# Region registry
REGION_REGISTRY: Dict[DataRegion, RegionInfo] = {
    DataRegion.US_EAST: RegionInfo(
        region=DataRegion.US_EAST,
        display_name="US East (Virginia)",
        country="US",
        jurisdiction="US",
        cloud_zones=["us-east-1", "eastus", "us-east1"],
        adequacy_decision=False,
        supported_providers=["openai", "anthropic", "google", "aws", "azure"],
    ),
    DataRegion.US_WEST: RegionInfo(
        region=DataRegion.US_WEST,
        display_name="US West (Oregon)",
        country="US",
        jurisdiction="US",
        cloud_zones=["us-west-2", "westus2", "us-west1"],
        adequacy_decision=False,
        supported_providers=["openai", "anthropic", "google", "aws", "azure"],
    ),
    DataRegion.EU_WEST: RegionInfo(
        region=DataRegion.EU_WEST,
        display_name="EU West (Ireland)",
        country="IE",
        jurisdiction="EU",
        cloud_zones=["eu-west-1", "westeurope", "europe-west1"],
        adequacy_decision=True,
        supported_providers=["anthropic", "google", "aws", "azure"],
    ),
    DataRegion.EU_CENTRAL: RegionInfo(
        region=DataRegion.EU_CENTRAL,
        display_name="EU Central (Frankfurt)",
        country="DE",
        jurisdiction="EU",
        cloud_zones=["eu-central-1", "germanywestcentral", "europe-west3"],
        adequacy_decision=True,
        supported_providers=["anthropic", "google", "aws", "azure"],
    ),
    DataRegion.APAC_TOKYO: RegionInfo(
        region=DataRegion.APAC_TOKYO,
        display_name="APAC (Tokyo)",
        country="JP",
        jurisdiction="APAC",
        cloud_zones=["ap-northeast-1", "japaneast", "asia-northeast1"],
        adequacy_decision=True,  # EU-Japan adequacy
        supported_providers=["anthropic", "google", "aws", "azure"],
    ),
    DataRegion.APAC_SINGAPORE: RegionInfo(
        region=DataRegion.APAC_SINGAPORE,
        display_name="APAC (Singapore)",
        country="SG",
        jurisdiction="APAC",
        cloud_zones=["ap-southeast-1", "southeastasia", "asia-southeast1"],
        adequacy_decision=False,
        supported_providers=["anthropic", "google", "aws", "azure"],
    ),
    DataRegion.CA_CENTRAL: RegionInfo(
        region=DataRegion.CA_CENTRAL,
        display_name="Canada Central (Montreal)",
        country="CA",
        jurisdiction="CA",
        cloud_zones=["ca-central-1", "canadacentral", "northamerica-northeast1"],
        adequacy_decision=True,  # EU-Canada adequacy
        supported_providers=["anthropic", "google", "aws", "azure"],
    ),
}


# ---------------------------------------------------------------------------
# Residency Policy
# ---------------------------------------------------------------------------

@dataclass
class ResidencyPolicy:
    """
    Data residency policy for an organization.

    Defines where data may and may not be stored or processed.
    """
    id: str = ""
    org_id: str = ""
    allowed_regions: List[DataRegion] = field(default_factory=list)
    prohibited_regions: List[DataRegion] = field(default_factory=list)
    model_regions: List[DataRegion] = field(default_factory=list)  # Where models may process data
    storage_region: DataRegion = DataRegion.US_EAST  # Primary storage region
    require_eu_adequacy: bool = False
    allow_cross_border: bool = True
    sccs_in_place: bool = False  # Standard Contractual Clauses
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "allowed_regions": [r.value for r in self.allowed_regions],
            "prohibited_regions": [r.value for r in self.prohibited_regions],
            "model_regions": [r.value for r in self.model_regions],
            "storage_region": self.storage_region.value,
            "require_eu_adequacy": self.require_eu_adequacy,
            "allow_cross_border": self.allow_cross_border,
            "sccs_in_place": self.sccs_in_place,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Cross-Border Transfer Record
# ---------------------------------------------------------------------------

@dataclass
class CrossBorderTransfer:
    """Record of a cross-border data transfer."""
    id: str = ""
    org_id: str = ""
    source_region: DataRegion = DataRegion.US_EAST
    target_region: DataRegion = DataRegion.US_EAST
    data_type: str = ""
    purpose: str = ""
    legal_basis: str = ""  # adequacy | sccs | consent | derogation
    timestamp: str = ""
    approved: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "source_region": self.source_region.value,
            "target_region": self.target_region.value,
            "data_type": self.data_type,
            "purpose": self.purpose,
            "legal_basis": self.legal_basis,
            "timestamp": self.timestamp,
            "approved": self.approved,
        }


# ---------------------------------------------------------------------------
# Data Residency Controller
# ---------------------------------------------------------------------------

class DataResidencyController:
    """
    Controls data residency for compliance with GDPR, PIPL, CCPA, and
    other data sovereignty regulations.

    Manages per-org residency policies, validates operations against
    policies, and provides compliant region routing.
    """

    def __init__(self, default_region: DataRegion = DataRegion.US_EAST):
        self._policies: Dict[str, ResidencyPolicy] = {}
        self._default_region = default_region
        self._transfer_log: List[CrossBorderTransfer] = []
        self._current_region: DataRegion | None = None

        # Jurisdiction-level constraints
        self._jurisdiction_rules: Dict[str, Dict[str, Any]] = {
            "EU": {
                "require_adequacy_or_sccs": True,
                "prohibited_destinations_without_safeguards": ["US"],
                "regulation": "GDPR",
            },
            "US": {
                "require_adequacy_or_sccs": False,
                "prohibited_destinations_without_safeguards": [],
                "regulation": "CCPA/State laws",
            },
            "APAC": {
                "require_adequacy_or_sccs": False,
                "prohibited_destinations_without_safeguards": [],
                "regulation": "Various (PIPL, PDPA, APPI)",
            },
            "CA": {
                "require_adequacy_or_sccs": False,
                "prohibited_destinations_without_safeguards": [],
                "regulation": "PIPEDA",
            },
        }

    # -- Policy management --------------------------------------------------

    async def set_policy(self, org_id: str, policy: ResidencyPolicy) -> None:
        """Set or update the residency policy for an organization."""
        policy.org_id = org_id
        if not policy.id:
            policy.id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        if not policy.created_at:
            policy.created_at = now
        policy.updated_at = now
        self._policies[org_id] = policy

    async def get_policy(self, org_id: str) -> ResidencyPolicy:
        """
        Get the residency policy for an organization.

        Returns a default policy if none is set.
        """
        if org_id in self._policies:
            return self._policies[org_id]

        # Return default policy (all regions allowed)
        return ResidencyPolicy(
            org_id=org_id,
            allowed_regions=list(DataRegion),
            storage_region=self._default_region,
            model_regions=list(DataRegion),
        )

    # -- Compliance checks --------------------------------------------------

    async def check_request(
        self,
        org_id: str,
        operation: str,
        target_region: DataRegion,
    ) -> Tuple[bool, str]:
        """
        Check if an operation in a target region is compliant with the
        organization's residency policy.

        Args:
            org_id: Organization identifier.
            operation: Type of operation (e.g., 'store', 'process', 'model_inference').
            target_region: The target data region.

        Returns:
            Tuple of (allowed, reason).
        """
        policy = await self.get_policy(org_id)

        # Check prohibited regions
        if target_region in policy.prohibited_regions:
            return (
                False,
                f"Region '{target_region.value}' is prohibited by org policy.",
            )

        # Check allowed regions (if specified, acts as whitelist)
        if policy.allowed_regions and target_region not in policy.allowed_regions:
            return (
                False,
                f"Region '{target_region.value}' is not in the allowed regions list.",
            )

        # Model-specific region check
        if operation in ("model_inference", "llm_call", "embedding"):
            if policy.model_regions and target_region not in policy.model_regions:
                return (
                    False,
                    f"Model processing not allowed in '{target_region.value}'.",
                )

        # EU adequacy check
        if policy.require_eu_adequacy:
            region_info = REGION_REGISTRY.get(target_region)
            if region_info and not region_info.adequacy_decision:
                if not policy.sccs_in_place:
                    return (
                        False,
                        f"Region '{target_region.value}' lacks EU adequacy decision "
                        f"and no Standard Contractual Clauses in place.",
                    )

        # Cross-border transfer check
        current = await self.get_current_region()
        if current != target_region and not policy.allow_cross_border:
            return (
                False,
                f"Cross-border transfer from '{current.value}' to "
                f"'{target_region.value}' is not allowed.",
            )

        # Jurisdiction-level check
        source_info = REGION_REGISTRY.get(current)
        target_info = REGION_REGISTRY.get(target_region)
        if source_info and target_info:
            jurisdiction_rule = self._jurisdiction_rules.get(
                source_info.jurisdiction, {}
            )
            prohibited_without_safeguards = jurisdiction_rule.get(
                "prohibited_destinations_without_safeguards", []
            )
            if target_info.jurisdiction in prohibited_without_safeguards:
                if not policy.sccs_in_place and not (
                    target_info.adequacy_decision
                ):
                    return (
                        False,
                        f"Transfer from {source_info.jurisdiction} to "
                        f"{target_info.jurisdiction} requires adequacy decision "
                        f"or Standard Contractual Clauses.",
                    )

        return (True, "Operation is compliant with residency policy.")

    async def route_to_compliant_region(
        self,
        org_id: str,
        operation: str,
    ) -> DataRegion:
        """
        Find the best compliant region for an operation.

        Returns the primary storage region if compliant, otherwise
        the first allowed region that passes compliance checks.
        """
        policy = await self.get_policy(org_id)

        # Try storage region first
        allowed, _ = await self.check_request(org_id, operation, policy.storage_region)
        if allowed:
            return policy.storage_region

        # Try model regions for model operations
        if operation in ("model_inference", "llm_call", "embedding"):
            for region in policy.model_regions:
                allowed, _ = await self.check_request(org_id, operation, region)
                if allowed:
                    return region

        # Try all allowed regions
        for region in policy.allowed_regions:
            allowed, _ = await self.check_request(org_id, operation, region)
            if allowed:
                return region

        # Fallback to default
        return self._default_region

    async def get_current_region(self) -> DataRegion:
        """
        Detect the current data region where this code is running.

        Uses environment variables, hostname heuristics, or falls back
        to the configured default.
        """
        if self._current_region:
            return self._current_region

        # Check environment variables (common in cloud deployments)
        env_region = os.environ.get("DATA_REGION", "")
        if env_region:
            try:
                return DataRegion(env_region)
            except ValueError:
                pass

        # AWS region detection
        aws_region = os.environ.get("AWS_REGION", "")
        if aws_region:
            return self._map_cloud_zone_to_region(aws_region)

        # Azure region
        azure_region = os.environ.get("AZURE_REGION", os.environ.get("WEBSITE_SITE_NAME", ""))
        if azure_region:
            return self._map_cloud_zone_to_region(azure_region)

        # GCP region
        gcp_zone = os.environ.get("GOOGLE_CLOUD_REGION", "")
        if gcp_zone:
            return self._map_cloud_zone_to_region(gcp_zone)

        return self._default_region

    def set_current_region(self, region: DataRegion) -> None:
        """Manually set the current region (for testing or override)."""
        self._current_region = region

    def _map_cloud_zone_to_region(self, zone: str) -> DataRegion:
        """Map a cloud provider zone/region string to a DataRegion."""
        zone_lower = zone.lower()
        for dr, info in REGION_REGISTRY.items():
            for cz in info.cloud_zones:
                if cz in zone_lower or zone_lower.startswith(cz.split("-")[0]):
                    return dr
        return self._default_region

    # -- Model Provider Validation ------------------------------------------

    async def validate_model_provider(
        self,
        org_id: str,
        provider: str,
        provider_region: DataRegion,
    ) -> bool:
        """
        Validate that a model provider in a given region is compliant
        with the organization's residency policy.

        Args:
            org_id: Organization identifier.
            provider: Model provider name (e.g., 'openai', 'anthropic').
            provider_region: Region where the provider processes data.

        Returns:
            True if the provider/region combination is compliant.
        """
        # Check provider is available in the region
        region_info = REGION_REGISTRY.get(provider_region)
        if region_info and provider not in region_info.supported_providers:
            return False

        # Check residency policy
        allowed, _ = await self.check_request(
            org_id, "model_inference", provider_region
        )
        return allowed

    # -- Data Map -----------------------------------------------------------

    async def generate_data_map(self, org_id: str) -> Dict[str, Any]:
        """
        Generate a map of where all data lives for an organization.

        Returns a structured overview of data locations, policies,
        and compliance status.
        """
        policy = await self.get_policy(org_id)
        current = await self.get_current_region()

        # Check compliance for each region
        region_status = {}
        for region in DataRegion:
            allowed, reason = await self.check_request(org_id, "store", region)
            region_info = REGION_REGISTRY.get(region, None)
            region_status[region.value] = {
                "allowed": allowed,
                "reason": reason,
                "info": region_info.to_dict() if region_info else {},
                "is_storage_region": region == policy.storage_region,
                "is_current_region": region == current,
            }

        # Cross-border transfer summary
        transfers = [
            t.to_dict() for t in self._transfer_log
            if t.org_id == org_id
        ]

        return {
            "org_id": org_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_region": current.value,
            "policy": policy.to_dict(),
            "region_status": region_status,
            "cross_border_transfers": transfers,
            "compliance_summary": {
                "storage_region": policy.storage_region.value,
                "allowed_regions": [r.value for r in policy.allowed_regions],
                "prohibited_regions": [r.value for r in policy.prohibited_regions],
                "eu_adequacy_required": policy.require_eu_adequacy,
                "sccs_in_place": policy.sccs_in_place,
                "cross_border_allowed": policy.allow_cross_border,
            },
        }

    # -- Transfer logging ---------------------------------------------------

    async def log_transfer(
        self,
        org_id: str,
        source_region: DataRegion,
        target_region: DataRegion,
        data_type: str,
        purpose: str,
        legal_basis: str = "adequacy",
    ) -> CrossBorderTransfer:
        """Log a cross-border data transfer."""
        allowed, _ = await self.check_request(org_id, "transfer", target_region)

        transfer = CrossBorderTransfer(
            id=str(uuid.uuid4()),
            org_id=org_id,
            source_region=source_region,
            target_region=target_region,
            data_type=data_type,
            purpose=purpose,
            legal_basis=legal_basis,
            timestamp=datetime.now(timezone.utc).isoformat(),
            approved=allowed,
        )
        self._transfer_log.append(transfer)
        return transfer

    async def get_transfer_log(
        self,
        org_id: str | None = None,
        limit: int = 100,
    ) -> List[CrossBorderTransfer]:
        """Retrieve cross-border transfer log entries."""
        entries = list(self._transfer_log)
        if org_id:
            entries = [e for e in entries if e.org_id == org_id]
        return entries[-limit:]

    # -- Utility ------------------------------------------------------------

    def get_region_info(self, region: DataRegion) -> RegionInfo | None:
        """Get metadata about a data region."""
        return REGION_REGISTRY.get(region)

    def list_regions(self) -> List[RegionInfo]:
        """List all available regions with metadata."""
        return list(REGION_REGISTRY.values())

    def get_regions_by_jurisdiction(self, jurisdiction: str) -> List[DataRegion]:
        """Get all regions in a jurisdiction (e.g., 'EU', 'US')."""
        return [
            info.region
            for info in REGION_REGISTRY.values()
            if info.jurisdiction == jurisdiction
        ]

    def get_eu_adequate_regions(self) -> List[DataRegion]:
        """Get all regions with EU adequacy decisions."""
        return [
            info.region
            for info in REGION_REGISTRY.values()
            if info.adequacy_decision
        ]
