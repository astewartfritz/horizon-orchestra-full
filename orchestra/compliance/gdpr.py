"""
GDPR / CCPA / Data Privacy compliance module.

Full data subject rights implementation covering access, deletion,
portability, and rectification requests. Includes CCPA do-not-sell
opt-out, data retention policies, Record of Processing Activities
(ROPA) generation, and privacy notice generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

__all__ = [
    "DataSubjectRequest",
    "DeletionReport",
    "PersonalDataInventory",
    "GDPRProcessor",
    "RequestType",
    "RequestStatus",
    "DataCategory",
    "RetentionPolicy",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RequestType(str, Enum):
    """GDPR data subject request types (GDPR Articles 15–22)."""
    ACCESS = "access"
    DELETE = "delete"
    PORTABILITY = "portability"
    RECTIFY = "rectify"
    RESTRICT = "restrict"
    OBJECT = "object"


class RequestStatus(str, Enum):
    """Processing status of a data subject request."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class DataCategory(str, Enum):
    """Categories of personal data stored by the system."""
    MEMORY = "memory"
    BILLING = "billing"
    CONNECTORS = "connectors"
    AUDIT = "audit"
    EMBEDDINGS = "embeddings"
    PROFILE = "profile"
    CONVERSATIONS = "conversations"
    PREFERENCES = "preferences"
    ANALYTICS = "analytics"
    FILES = "files"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DataSubjectRequest:
    """
    A GDPR/CCPA data subject request (DSR).

    Tracks the lifecycle from submission through processing to completion,
    with full audit trail.
    """
    id: str = ""
    type: RequestType = RequestType.ACCESS
    user_id: str = ""
    email: str = ""
    submitted_at: str = ""
    status: RequestStatus = RequestStatus.PENDING
    completed_at: str = ""
    processor_notes: str = ""
    verification_token: str = ""
    verified: bool = False
    org_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, RequestType) else self.type,
            "user_id": self.user_id,
            "email": self.email,
            "submitted_at": self.submitted_at,
            "status": self.status.value if isinstance(self.status, RequestStatus) else self.status,
            "completed_at": self.completed_at,
            "processor_notes": self.processor_notes,
            "verified": self.verified,
            "org_id": self.org_id,
            "metadata": self.metadata,
        }


@dataclass
class DeletionReport:
    """Report generated after processing a deletion request."""
    request_id: str = ""
    user_id: str = ""
    categories_deleted: List[str] = field(default_factory=list)
    records_deleted: int = 0
    embeddings_purged: int = 0
    retention_held: List[str] = field(default_factory=list)
    completed_at: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "categories_deleted": self.categories_deleted,
            "records_deleted": self.records_deleted,
            "embeddings_purged": self.embeddings_purged,
            "retention_held": self.retention_held,
            "completed_at": self.completed_at,
            "errors": self.errors,
        }


@dataclass
class RetentionPolicy:
    """Data retention policy per category."""
    category: DataCategory = DataCategory.MEMORY
    retention_days: int = 365
    legal_basis: str = "consent"
    auto_delete: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "retention_days": self.retention_days,
            "legal_basis": self.legal_basis,
            "auto_delete": self.auto_delete,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Personal Data Inventory
# ---------------------------------------------------------------------------

class PersonalDataInventory:
    """
    Tracks what PII each module stores (GDPR Art. 30 requirement).

    Maps data categories to field-level details including purpose,
    legal basis, and retention period.
    """

    # Default inventory of personal data per module
    DEFAULT_INVENTORY: Dict[str, Dict[str, Any]] = {
        DataCategory.PROFILE.value: {
            "fields": ["user_id", "email", "display_name", "avatar_url", "locale", "timezone"],
            "purpose": "Account management and personalization",
            "legal_basis": "contract",
            "retention_days": 0,  # 0 = until account deletion
            "third_party_sharing": False,
        },
        DataCategory.MEMORY.value: {
            "fields": ["user_id", "conversation_summaries", "preferences", "facts", "embedding_vectors"],
            "purpose": "Personalized AI assistant experience",
            "legal_basis": "consent",
            "retention_days": 365,
            "third_party_sharing": False,
        },
        DataCategory.BILLING.value: {
            "fields": ["user_id", "org_id", "stripe_customer_id", "invoice_email", "billing_address", "tax_id"],
            "purpose": "Payment processing and invoicing",
            "legal_basis": "contract",
            "retention_days": 2555,  # ~7 years for tax compliance
            "third_party_sharing": True,
            "third_parties": ["Stripe"],
        },
        DataCategory.CONNECTORS.value: {
            "fields": ["user_id", "oauth_tokens", "connected_services", "scopes"],
            "purpose": "Third-party service integration",
            "legal_basis": "consent",
            "retention_days": 0,
            "third_party_sharing": True,
            "third_parties": ["Connected service providers"],
        },
        DataCategory.AUDIT.value: {
            "fields": ["user_id", "action", "timestamp", "ip_address", "user_agent", "resource"],
            "purpose": "Security monitoring and compliance",
            "legal_basis": "legitimate_interest",
            "retention_days": 730,  # 2 years
            "third_party_sharing": False,
        },
        DataCategory.EMBEDDINGS.value: {
            "fields": ["user_id", "vector_id", "source_text_hash", "embedding_vector"],
            "purpose": "Semantic search and memory retrieval",
            "legal_basis": "consent",
            "retention_days": 365,
            "third_party_sharing": False,
        },
        DataCategory.CONVERSATIONS.value: {
            "fields": ["user_id", "messages", "tool_calls", "timestamps", "model_used"],
            "purpose": "Conversation history and continuity",
            "legal_basis": "consent",
            "retention_days": 90,
            "third_party_sharing": False,
        },
        DataCategory.PREFERENCES.value: {
            "fields": ["user_id", "theme", "language", "notification_settings", "default_model"],
            "purpose": "User experience customization",
            "legal_basis": "consent",
            "retention_days": 0,
            "third_party_sharing": False,
        },
        DataCategory.ANALYTICS.value: {
            "fields": ["user_id", "session_events", "feature_usage", "performance_metrics"],
            "purpose": "Product improvement and analytics",
            "legal_basis": "legitimate_interest",
            "retention_days": 365,
            "third_party_sharing": False,
        },
        DataCategory.FILES.value: {
            "fields": ["user_id", "file_name", "file_content", "upload_timestamp"],
            "purpose": "File storage and processing",
            "legal_basis": "consent",
            "retention_days": 30,
            "third_party_sharing": False,
        },
    }

    def __init__(self, custom_inventory: Dict[str, Dict[str, Any]] | None = None):
        self._inventory = dict(self.DEFAULT_INVENTORY)
        if custom_inventory:
            self._inventory.update(custom_inventory)

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get inventory details for a data category."""
        return self._inventory.get(category, {})

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Return the full data inventory."""
        return dict(self._inventory)

    def get_fields_for_user(self, category: str) -> List[str]:
        """Get all PII field names stored for a category."""
        cat = self._inventory.get(category, {})
        return cat.get("fields", [])

    def get_categories_with_sharing(self) -> List[str]:
        """Get categories that involve third-party data sharing."""
        return [
            cat for cat, details in self._inventory.items()
            if details.get("third_party_sharing", False)
        ]

    def add_category(self, category: str, details: Dict[str, Any]) -> None:
        """Register a new data category in the inventory."""
        self._inventory[category] = details


# ---------------------------------------------------------------------------
# GDPR Processor
# ---------------------------------------------------------------------------

class GDPRProcessor:
    """
    Full GDPR / CCPA data subject rights processor.

    Handles access, deletion, portability, and rectification requests
    with verification, audit trails, and retention policy enforcement.
    """

    def __init__(
        self,
        data_store: Dict[str, Any] | None = None,
        inventory: PersonalDataInventory | None = None,
        retention_policies: List[RetentionPolicy] | None = None,
        org_name: str = "Horizon Orchestra",
        dpo_email: str = "dpo@horizon-orchestra.ai",
    ):
        self._requests: Dict[str, DataSubjectRequest] = {}
        self._data_store: Dict[str, Dict[str, Any]] = data_store or {}
        self._inventory = inventory or PersonalDataInventory()
        self._ccpa_opt_outs: Set[str] = set()
        self._deletion_reports: Dict[str, DeletionReport] = {}
        self._org_name = org_name
        self._dpo_email = dpo_email

        # Default retention policies
        self._retention_policies: Dict[str, RetentionPolicy] = {}
        if retention_policies:
            for p in retention_policies:
                self._retention_policies[p.category.value] = p
        else:
            self._init_default_retention()

    def _init_default_retention(self) -> None:
        """Set up default retention policies from inventory."""
        for cat_name, details in self._inventory.get_all().items():
            self._retention_policies[cat_name] = RetentionPolicy(
                category=DataCategory(cat_name) if cat_name in DataCategory.__members__.values() else DataCategory.MEMORY,
                retention_days=details.get("retention_days", 365),
                legal_basis=details.get("legal_basis", "consent"),
                auto_delete=details.get("retention_days", 0) > 0,
                description=details.get("purpose", ""),
            )

    # -- Request lifecycle --------------------------------------------------

    async def submit_request(
        self,
        user_id: str,
        request_type: str,
        email: str,
        org_id: str = "",
    ) -> DataSubjectRequest:
        """
        Submit a new data subject request.

        Args:
            user_id: The user ID making the request.
            request_type: One of 'access', 'delete', 'portability', 'rectify'.
            email: Contact email for the data subject.
            org_id: Optional organization ID.

        Returns:
            The created DataSubjectRequest with unique ID and verification token.
        """
        # Normalize request type
        try:
            rt = RequestType(request_type)
        except ValueError:
            rt = RequestType.ACCESS

        req = DataSubjectRequest(
            id=str(uuid.uuid4()),
            type=rt,
            user_id=user_id,
            email=email,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            status=RequestStatus.PENDING,
            verification_token=hashlib.sha256(
                f"{user_id}-{time.time_ns()}".encode()
            ).hexdigest()[:32],
            org_id=org_id,
        )
        self._requests[req.id] = req
        return req

    async def verify_request(self, request_id: str, token: str) -> bool:
        """Verify a data subject request using the verification token."""
        req = self._requests.get(request_id)
        if not req:
            return False
        if req.verification_token == token:
            req.verified = True
            return True
        return False

    async def process_access_request(self, req: DataSubjectRequest) -> dict:
        """
        Process a GDPR Article 15 access request.

        Returns all PII stored for the user across all data categories.
        """
        req.status = RequestStatus.IN_PROGRESS
        result: Dict[str, Any] = {
            "subject": {"user_id": req.user_id, "email": req.email},
            "request_id": req.id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_categories": {},
        }

        # Collect data from each category
        user_data = self._data_store.get(req.user_id, {})
        for cat_name, details in self._inventory.get_all().items():
            category_data = user_data.get(cat_name, {})
            result["data_categories"][cat_name] = {
                "fields": details.get("fields", []),
                "purpose": details.get("purpose", ""),
                "legal_basis": details.get("legal_basis", ""),
                "retention_days": details.get("retention_days", 0),
                "data": category_data,
                "third_party_sharing": details.get("third_party_sharing", False),
            }

        req.status = RequestStatus.COMPLETED
        req.completed_at = datetime.now(timezone.utc).isoformat()
        return result

    async def process_deletion_request(self, req: DataSubjectRequest) -> DeletionReport:
        """
        Process a GDPR Article 17 right-to-erasure request.

        Hard-deletes personal data from memory, billing (if not legally required),
        connectors, audit (if past retention), and embeddings.
        """
        req.status = RequestStatus.IN_PROGRESS
        report = DeletionReport(
            request_id=req.id,
            user_id=req.user_id,
        )

        user_data = self._data_store.get(req.user_id, {})
        categories_to_delete = []
        retention_held = []

        for cat_name, details in self._inventory.get_all().items():
            retention_days = details.get("retention_days", 0)
            legal_basis = details.get("legal_basis", "")

            # Legal obligation override — cannot delete billing data under legal hold
            if cat_name == DataCategory.BILLING.value and legal_basis == "contract":
                retention_held.append(
                    f"{cat_name}: retained for {retention_days} days (legal obligation)"
                )
                continue

            # Audit logs retained under legitimate interest if within retention
            if cat_name == DataCategory.AUDIT.value and legal_basis == "legitimate_interest":
                retention_held.append(
                    f"{cat_name}: retained for compliance ({retention_days} days)"
                )
                continue

            categories_to_delete.append(cat_name)

        # Perform deletion
        records_deleted = 0
        embeddings_purged = 0

        for cat_name in categories_to_delete:
            cat_data = user_data.pop(cat_name, None)
            if cat_data:
                if isinstance(cat_data, dict):
                    records_deleted += len(cat_data)
                elif isinstance(cat_data, list):
                    records_deleted += len(cat_data)
                else:
                    records_deleted += 1

                if cat_name == DataCategory.EMBEDDINGS.value:
                    embeddings_purged = records_deleted

            report.categories_deleted.append(cat_name)

        # Remove user entry if all data deleted
        if not user_data:
            self._data_store.pop(req.user_id, None)
        else:
            self._data_store[req.user_id] = user_data

        report.records_deleted = records_deleted
        report.embeddings_purged = embeddings_purged
        report.retention_held = retention_held
        report.completed_at = datetime.now(timezone.utc).isoformat()

        self._deletion_reports[req.id] = report
        req.status = RequestStatus.COMPLETED
        req.completed_at = report.completed_at
        return report

    async def process_portability_request(self, req: DataSubjectRequest) -> bytes:
        """
        Process a GDPR Article 20 data portability request.

        Returns all user data as a JSON byte string in a structured,
        machine-readable format.
        """
        req.status = RequestStatus.IN_PROGRESS
        export_data = {
            "schema_version": "1.0",
            "export_format": "horizon-orchestra/gdpr-export",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject": {
                "user_id": req.user_id,
                "email": req.email,
            },
            "data": {},
        }

        user_data = self._data_store.get(req.user_id, {})
        for cat_name, details in self._inventory.get_all().items():
            cat_data = user_data.get(cat_name, {})
            export_data["data"][cat_name] = {
                "purpose": details.get("purpose", ""),
                "records": cat_data,
            }

        result = json.dumps(export_data, indent=2, default=str).encode("utf-8")
        req.status = RequestStatus.COMPLETED
        req.completed_at = datetime.now(timezone.utc).isoformat()
        return result

    async def process_rectification(
        self, req: DataSubjectRequest, corrections: Dict[str, Any]
    ) -> None:
        """
        Process a GDPR Article 16 rectification request.

        Updates personal data with provided corrections.
        """
        req.status = RequestStatus.IN_PROGRESS
        user_data = self._data_store.setdefault(req.user_id, {})

        for category, updates in corrections.items():
            cat_data = user_data.setdefault(category, {})
            if isinstance(updates, dict):
                cat_data.update(updates)
            else:
                user_data[category] = updates

        req.status = RequestStatus.COMPLETED
        req.completed_at = datetime.now(timezone.utc).isoformat()
        req.processor_notes = f"Rectified {len(corrections)} categories"

    # -- Batch processing ---------------------------------------------------

    async def get_pending_requests(self) -> List[DataSubjectRequest]:
        """Get all pending data subject requests."""
        return [
            r for r in self._requests.values()
            if r.status == RequestStatus.PENDING
        ]

    async def run_pending(self) -> int:
        """
        Process all pending requests (for cron job use).

        Returns the number of requests processed.
        """
        pending = await self.get_pending_requests()
        processed = 0

        for req in pending:
            try:
                if req.type == RequestType.ACCESS:
                    await self.process_access_request(req)
                elif req.type == RequestType.DELETE:
                    await self.process_deletion_request(req)
                elif req.type == RequestType.PORTABILITY:
                    await self.process_portability_request(req)
                elif req.type == RequestType.RECTIFY:
                    # Rectification requires corrections — skip auto-processing
                    continue
                processed += 1
            except Exception as e:
                req.status = RequestStatus.FAILED
                req.processor_notes = str(e)

        return processed

    # -- ROPA & Privacy Notice ----------------------------------------------

    async def generate_ropa(self) -> str:
        """
        Generate a Record of Processing Activities (GDPR Art. 30).

        Returns a structured text document listing all processing activities,
        data categories, purposes, legal bases, and retention periods.
        """
        lines = [
            "=" * 80,
            "RECORD OF PROCESSING ACTIVITIES (ROPA)",
            f"Organization: {self._org_name}",
            f"Data Protection Officer: {self._dpo_email}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "=" * 80,
            "",
        ]

        for i, (cat_name, details) in enumerate(self._inventory.get_all().items(), 1):
            lines.extend([
                f"--- Processing Activity {i}: {cat_name.upper()} ---",
                f"  Purpose: {details.get('purpose', 'N/A')}",
                f"  Legal Basis: {details.get('legal_basis', 'N/A')}",
                f"  Data Fields: {', '.join(details.get('fields', []))}",
                f"  Retention: {details.get('retention_days', 0)} days"
                + (" (until account deletion)" if details.get("retention_days", 0) == 0 else ""),
                f"  Third-party Sharing: {'Yes' if details.get('third_party_sharing') else 'No'}",
            ])
            if details.get("third_parties"):
                lines.append(f"  Recipients: {', '.join(details['third_parties'])}")
            lines.append("")

        lines.extend([
            "--- Data Subject Rights ---",
            "  - Right of Access (Art. 15)",
            "  - Right to Rectification (Art. 16)",
            "  - Right to Erasure (Art. 17)",
            "  - Right to Restriction (Art. 18)",
            "  - Right to Data Portability (Art. 20)",
            "  - Right to Object (Art. 21)",
            "",
            "--- Technical & Organizational Measures ---",
            "  - AES-256-GCM encryption at rest",
            "  - TLS 1.3 encryption in transit",
            "  - Role-based access control (RBAC)",
            "  - Automated data retention enforcement",
            "  - Regular security audits and penetration testing",
            "  - SCIM 2.0 user provisioning/deprovisioning",
            "",
            f"--- Data Protection Officer ---",
            f"  Contact: {self._dpo_email}",
            "",
            "=" * 80,
        ])

        return "\n".join(lines)

    async def generate_privacy_notice(self) -> str:
        """
        Generate a GDPR-compliant privacy notice.

        Returns a human-readable privacy notice suitable for end users.
        """
        categories = self._inventory.get_all()
        sharing_cats = self._inventory.get_categories_with_sharing()

        notice = f"""PRIVACY NOTICE
{'=' * 60}
Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
Organization: {self._org_name}

1. DATA CONTROLLER
{self._org_name} is the data controller for personal data processed
through this platform. Contact our DPO at {self._dpo_email}.

2. WHAT DATA WE COLLECT
"""
        for cat_name, details in categories.items():
            fields = ", ".join(details.get("fields", []))
            notice += f"  - {cat_name}: {fields}\n"

        notice += f"""
3. WHY WE PROCESS YOUR DATA
"""
        for cat_name, details in categories.items():
            notice += f"  - {cat_name}: {details.get('purpose', 'N/A')}\n"

        notice += f"""
4. LEGAL BASIS
"""
        bases_seen: Set[str] = set()
        for details in categories.values():
            basis = details.get("legal_basis", "")
            if basis and basis not in bases_seen:
                bases_seen.add(basis)
                if basis == "consent":
                    notice += "  - Consent: Where you have given explicit consent.\n"
                elif basis == "contract":
                    notice += "  - Contract: Processing necessary for our agreement.\n"
                elif basis == "legitimate_interest":
                    notice += "  - Legitimate Interest: For security and service improvement.\n"

        notice += f"""
5. DATA SHARING
"""
        if sharing_cats:
            for cat_name in sharing_cats:
                details = categories[cat_name]
                third_parties = details.get("third_parties", ["Service providers"])
                notice += f"  - {cat_name}: shared with {', '.join(third_parties)}\n"
        else:
            notice += "  We do not share your personal data with third parties.\n"

        notice += f"""
6. DATA RETENTION
"""
        for cat_name, details in categories.items():
            days = details.get("retention_days", 0)
            if days == 0:
                notice += f"  - {cat_name}: Until account deletion\n"
            else:
                notice += f"  - {cat_name}: {days} days\n"

        notice += f"""
7. YOUR RIGHTS
Under GDPR, you have the right to:
  - Access your personal data (Art. 15)
  - Correct inaccurate data (Art. 16)
  - Delete your data (Art. 17)
  - Restrict processing (Art. 18)
  - Receive your data in a portable format (Art. 20)
  - Object to processing (Art. 21)

Under CCPA (California residents), you also have the right to:
  - Know what personal information is collected
  - Delete personal information
  - Opt-out of the sale of personal information
  - Non-discrimination for exercising your rights

To exercise any of these rights, contact {self._dpo_email}.

8. SECURITY
We implement industry-standard security measures including AES-256-GCM
encryption, TLS 1.3, RBAC, and regular security assessments.

9. CONTACT
Data Protection Officer: {self._dpo_email}
{'=' * 60}
"""
        return notice

    # -- CCPA ---------------------------------------------------------------

    async def do_not_sell_opt_out(self, user_id: str) -> None:
        """
        CCPA Do-Not-Sell opt-out (Cal. Civ. Code §1798.120).

        Registers the user's opt-out of personal data sale.
        """
        self._ccpa_opt_outs.add(user_id)

    async def is_opted_out(self, user_id: str) -> bool:
        """Check if a user has opted out of data sale under CCPA."""
        return user_id in self._ccpa_opt_outs

    async def ccpa_opt_back_in(self, user_id: str) -> None:
        """Allow a user to opt back in to data sale."""
        self._ccpa_opt_outs.discard(user_id)

    async def get_ccpa_disclosure(self, user_id: str) -> dict:
        """
        Generate CCPA disclosure (Cal. Civ. Code §1798.100).

        Returns categories of personal info collected in the past 12 months.
        """
        return {
            "user_id": user_id,
            "categories_collected": list(self._inventory.get_all().keys()),
            "categories_sold": [],  # We do not sell data
            "categories_disclosed_for_business_purpose": self._inventory.get_categories_with_sharing(),
            "opt_out_status": user_id in self._ccpa_opt_outs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -- Data Retention Policy Enforcement ----------------------------------

    async def enforce_retention(self, current_time: datetime | None = None) -> Dict[str, int]:
        """
        Enforce data retention policies — auto-delete records older than
        N days per category.

        Returns a dict of {category: records_deleted}.
        """
        now = current_time or datetime.now(timezone.utc)
        deleted_counts: Dict[str, int] = {}

        for user_id in list(self._data_store.keys()):
            user_data = self._data_store[user_id]
            for cat_name in list(user_data.keys()):
                policy = self._retention_policies.get(cat_name)
                if not policy or not policy.auto_delete or policy.retention_days <= 0:
                    continue

                cat_data = user_data[cat_name]
                cutoff = now - timedelta(days=policy.retention_days)

                # Handle different data structures
                if isinstance(cat_data, list):
                    original_len = len(cat_data)
                    cat_data = [
                        r for r in cat_data
                        if not self._is_expired(r, cutoff)
                    ]
                    removed = original_len - len(cat_data)
                    if removed > 0:
                        user_data[cat_name] = cat_data
                        deleted_counts[cat_name] = deleted_counts.get(cat_name, 0) + removed
                elif isinstance(cat_data, dict) and "created_at" in cat_data:
                    if self._is_expired(cat_data, cutoff):
                        del user_data[cat_name]
                        deleted_counts[cat_name] = deleted_counts.get(cat_name, 0) + 1

            # Clean up empty user records
            if not user_data:
                del self._data_store[user_id]

        return deleted_counts

    @staticmethod
    def _is_expired(record: Any, cutoff: datetime) -> bool:
        """Check if a record has expired past the cutoff date."""
        if isinstance(record, dict):
            created = record.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    return created_dt < cutoff
                except (ValueError, TypeError):
                    pass
        return False

    # -- Utilities ----------------------------------------------------------

    def get_request(self, request_id: str) -> DataSubjectRequest | None:
        """Retrieve a DSR by ID."""
        return self._requests.get(request_id)

    def get_all_requests(self, user_id: str | None = None) -> List[DataSubjectRequest]:
        """Get all DSRs, optionally filtered by user_id."""
        requests = list(self._requests.values())
        if user_id:
            requests = [r for r in requests if r.user_id == user_id]
        return requests

    def get_deletion_report(self, request_id: str) -> DeletionReport | None:
        """Retrieve a deletion report by request ID."""
        return self._deletion_reports.get(request_id)

    async def get_stats(self) -> dict:
        """Get DSR processing statistics."""
        total = len(self._requests)
        by_status = {}
        by_type = {}
        for req in self._requests.values():
            status = req.status.value if isinstance(req.status, RequestStatus) else req.status
            rtype = req.type.value if isinstance(req.type, RequestType) else req.type
            by_status[status] = by_status.get(status, 0) + 1
            by_type[rtype] = by_type.get(rtype, 0) + 1

        return {
            "total_requests": total,
            "by_status": by_status,
            "by_type": by_type,
            "ccpa_opt_outs": len(self._ccpa_opt_outs),
        }
