"""
Enterprise Compliance & Identity Layer for Horizon Orchestra.

Provides SCIM 2.0 provisioning, GDPR/CCPA data privacy, HIPAA PHI controls,
data residency enforcement, and per-org quota management — everything
Fortune 500 legal and IT teams require before signing.

Modules:
    scim            — SCIM 2.0 User/Group provisioning (RFC 7644)
    gdpr            — GDPR / CCPA data subject rights
    hipaa           — HIPAA PHI scanning, encryption, BAA tracking
    data_residency  — Data residency controls (GDPR, PIPL, CCPA)
    org_quotas      — Per-org rate limits and quotas
"""

from orchestra.compliance.scim import (
    SCIMUser,
    SCIMGroup,
    SCIMPatch,
    SCIMPatchOp,
    SCIMListResponse,
    SCIMProvider,
    SCIMError,
    SCIMFilterParser,
)
from orchestra.compliance.gdpr import (
    DataSubjectRequest,
    DeletionReport,
    PersonalDataInventory,
    GDPRProcessor,
    RequestType,
    RequestStatus,
    DataCategory,
    RetentionPolicy,
)
from orchestra.compliance.hipaa import (
    PHIField,
    PHIMatch,
    PHIScanner,
    HIPAAControls,
    BAARecord,
    BAATracker,
)
from orchestra.compliance.data_residency import (
    DataRegion,
    ResidencyPolicy,
    DataResidencyController,
    RegionInfo,
    CrossBorderTransfer,
)
from orchestra.compliance.org_quotas import (
    OrgQuota,
    QuotaUsage,
    OrgQuotaManager,
    QuotaTier,
    TIER_QUOTAS,
)

__all__ = [
    # SCIM
    "SCIMUser",
    "SCIMGroup",
    "SCIMPatch",
    "SCIMPatchOp",
    "SCIMListResponse",
    "SCIMProvider",
    "SCIMError",
    "SCIMFilterParser",
    # GDPR
    "DataSubjectRequest",
    "DeletionReport",
    "PersonalDataInventory",
    "GDPRProcessor",
    "RequestType",
    "RequestStatus",
    "DataCategory",
    "RetentionPolicy",
    # HIPAA
    "PHIField",
    "PHIMatch",
    "PHIScanner",
    "HIPAAControls",
    "BAARecord",
    "BAATracker",
    # Data Residency
    "DataRegion",
    "ResidencyPolicy",
    "DataResidencyController",
    "RegionInfo",
    "CrossBorderTransfer",
    # Org Quotas
    "OrgQuota",
    "QuotaUsage",
    "OrgQuotaManager",
    "QuotaTier",
    "TIER_QUOTAS",
]
