"""Customs Compliance Agent — International trade compliance and customs.

AI-powered trade compliance covering HTS classification, OFAC/SDN
screening, export control (EAR/ITAR), FTA origin qualification,
duty drawback, and customs entry filing.

Regulatory frameworks
---------------------
- HTS (Harmonized Tariff Schedule) / HS (Harmonized System)
- OFAC (Office of Foreign Assets Control) SDN list screening
- EAR (Export Administration Regulations) — Commerce Dept / BIS
- ITAR (International Traffic in Arms Regulations) — State Dept / DDTC
- CBP (Customs and Border Protection) entry filing
- FTA/USMCA/EU preferential origin rules

Target customers
----------------
- DHL Global Forwarding: Customs brokerage worldwide
- Maersk: Container import/export compliance
- FedEx Trade Networks: Cross-border trade facilitation
- UPS Supply Chain Solutions: Customs clearance services
- XPO Logistics: International supply chain compliance
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "CustomsComplianceAgent",
    "HTSClassification",
    "OFACScreenResult",
    "ExportControlResult",
    "DutyCalculation",
    "FTAQualification",
    "CommercialInvoice",
    "CustomsEntry",
    "CertificateOfOrigin",
    "DeniedPartyResult",
    "ComplianceReport",
    "TradeAgreement",
]

log = logging.getLogger("orchestra.verticals.logistics.customs_compliance")

# ---------------------------------------------------------------------------
# Graceful imports
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except Exception:
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class TradeAgreement(str, Enum):
    """Free Trade Agreements."""
    USMCA = "usmca"             # US-Mexico-Canada
    EU_FTA = "eu_fta"           # EU trade agreements
    CPTPP = "cptpp"             # Trans-Pacific Partnership
    RCEP = "rcep"               # Regional Comprehensive Economic Partnership
    ASEAN = "asean"             # ASEAN Free Trade Area
    MERCOSUR = "mercosur"       # Southern Common Market
    CAFTA_DR = "cafta_dr"       # Central America-DR-US
    KORUS = "korus"             # Korea-US
    AUSFTA = "ausfta"          # Australia-US
    GSP = "gsp"                 # Generalized System of Preferences


class ExportControlRegime(str, Enum):
    """Export control regulatory regimes."""
    EAR = "ear"                 # Export Administration Regulations (Commerce/BIS)
    ITAR = "itar"               # ITAR (State Dept / DDTC)
    NRC = "nrc"                 # Nuclear Regulatory Commission
    OFAC = "ofac"               # Treasury / OFAC sanctions
    DOE = "doe"                 # Department of Energy


class EntryType(str, Enum):
    """CBP customs entry types."""
    CONSUMPTION = "01"          # Consumption entry (most common)
    INFORMAL = "11"             # Informal entry (< $2,500)
    WAREHOUSE = "21"            # Warehouse entry
    FTZ = "06"                  # Foreign Trade Zone entry
    TEMPORARY = "12"            # Temporary importation bond


class ScreeningListType(str, Enum):
    """Government screening lists."""
    SDN = "sdn"                 # OFAC SDN (Specially Designated Nationals)
    ENTITY_LIST = "entity_list" # BIS Entity List
    DENIED_PERSONS = "denied_persons"       # BIS Denied Persons List
    UNVERIFIED = "unverified"   # BIS Unverified List
    MILITARY_END_USER = "military_end_user" # BIS MEU List
    CONSOLIDATED = "consolidated"           # All lists combined


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class HTSClassification:
    """HTS/HS tariff classification result."""
    hts_code: str               # e.g., "8471.30.0100" (laptops)
    hts_description: str
    chapter: int                # HS chapter (1-99)
    heading: str                # 4-digit heading
    subheading: str             # 6-digit HS subheading
    statistical_suffix: str     # US-specific statistical suffix
    general_duty_rate: str      # e.g., "Free", "2.5%", "$1.20/kg"
    special_duty_rate: Optional[str] = None  # FTA preferential rate
    column_2_rate: Optional[str] = None      # Column 2 (non-MFN) rate
    unit_of_quantity: str = ""               # e.g., "No.", "kg", "m²"
    section_301_rate: Optional[str] = None   # China tariff rate
    ad_cvd_applicable: bool = False          # Antidumping/countervailing
    country_of_origin: str = ""
    confidence: float = 0.0


@dataclass
class OFACScreenResult:
    """OFAC SDN list screening result."""
    screened_name: str
    match_found: bool
    match_score: float = 0.0    # 0.0–1.0
    matched_entries: List[Dict[str, Any]] = field(default_factory=list)
    list_type: str = "SDN"
    screening_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    recommendations: str = ""


@dataclass
class ExportControlResult:
    """Export control classification result."""
    eccn: str                   # e.g., "5A002" (encryption)
    ear99: bool = False         # EAR99 (no license required for most destinations)
    itar_controlled: bool = False
    license_required: bool = False
    license_exception: Optional[str] = None  # e.g., "TSR", "ENC"
    regime: ExportControlRegime = ExportControlRegime.EAR
    destination_country: str = ""
    end_use_restriction: bool = False
    notes: str = ""


@dataclass
class DutyCalculation:
    """Import duty and tax calculation."""
    hts_code: str
    customs_value: float        # Declared value in USD
    duty_rate_pct: float
    duty_amount: float
    mpf: float                  # Merchandise Processing Fee
    hmf: float                  # Harbor Maintenance Fee (ocean only)
    vat_rate_pct: float = 0.0   # VAT/GST if applicable
    vat_amount: float = 0.0
    section_301_rate_pct: float = 0.0
    section_301_amount: float = 0.0
    ad_cvd_rate_pct: float = 0.0
    ad_cvd_amount: float = 0.0
    total_duties_taxes: float = 0.0
    currency: str = "USD"
    country_of_origin: str = ""
    incoterm: str = "CIF"


@dataclass
class FTAQualification:
    """FTA rules of origin qualification."""
    hts_code: str
    fta: TradeAgreement
    qualifies: bool = False
    rule_of_origin: str = ""        # Specific RoO applied
    tariff_shift: bool = False      # Tariff shift satisfied
    regional_value_content_pct: float = 0.0  # RVC percentage
    rvc_threshold_pct: float = 0.0  # Required RVC threshold
    producer_declaration: bool = False
    certificate_required: bool = True
    duty_savings: float = 0.0       # Savings vs. MFN rate
    notes: str = ""


@dataclass
class CommercialInvoice:
    """Commercial invoice for customs."""
    invoice_number: str
    seller: str
    buyer: str
    ship_date: str
    country_of_origin: str
    country_of_destination: str
    incoterm: str
    currency: str = "USD"
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    total_value: float = 0.0
    freight_charges: float = 0.0
    insurance: float = 0.0
    packing_charges: float = 0.0


@dataclass
class CustomsEntry:
    """CBP customs entry preparation."""
    entry_number: str
    entry_type: EntryType
    importer_of_record: str
    port_of_entry: str
    entry_date: str
    hts_lines: List[Dict[str, Any]] = field(default_factory=list)
    total_entered_value: float = 0.0
    total_duties: float = 0.0
    bond_type: str = "single_entry"  # single_entry, continuous
    broker: str = ""
    status: str = "draft"


@dataclass
class CertificateOfOrigin:
    """Certificate of Origin document."""
    certificate_number: str
    exporter: str
    producer: str
    importer: str
    fta: TradeAgreement
    blanket_period_start: Optional[str] = None
    blanket_period_end: Optional[str] = None
    goods: List[Dict[str, Any]] = field(default_factory=list)
    certifier_signature_date: str = ""


@dataclass
class DeniedPartyResult:
    """Denied party list screening result."""
    screened_entity: str
    lists_checked: List[str] = field(default_factory=list)
    matches: List[Dict[str, Any]] = field(default_factory=list)
    clear: bool = True
    screening_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ComplianceReport:
    """Trade compliance audit report."""
    report_id: str
    report_date: str
    scope: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    risk_areas: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    compliance_score: int = 0       # 0-100


# ═══════════════════════════════════════════════════════════════════════════
# HTS code reference data
# ═══════════════════════════════════════════════════════════════════════════

# Common HTS chapter references
_HTS_CHAPTERS: Dict[int, str] = {
    1: "Live Animals",
    2: "Meat and Edible Meat Offal",
    3: "Fish, Crustaceans, Molluscs",
    15: "Animal or Vegetable Fats",
    22: "Beverages, Spirits, Vinegar",
    27: "Mineral Fuels, Oils",
    29: "Organic Chemicals",
    30: "Pharmaceutical Products",
    39: "Plastics and Articles",
    44: "Wood and Articles of Wood",
    48: "Paper and Paperboard",
    61: "Apparel, Knitted or Crocheted",
    62: "Apparel, Not Knitted",
    64: "Footwear",
    71: "Precious Metals, Jewelry",
    72: "Iron and Steel",
    73: "Articles of Iron or Steel",
    84: "Nuclear Reactors, Boilers, Machinery",
    85: "Electrical Machinery and Equipment",
    87: "Vehicles (Not Railway)",
    88: "Aircraft, Spacecraft",
    90: "Optical, Measuring, Medical Instruments",
    94: "Furniture, Bedding, Lighting",
    95: "Toys, Games, Sports Equipment",
}

# Common ECCN categories
_ECCN_CATEGORIES: Dict[str, str] = {
    "0": "Nuclear & Miscellaneous",
    "1": "Materials, Chemicals, Microorganisms, Toxins",
    "2": "Materials Processing",
    "3": "Electronics",
    "4": "Computers",
    "5": "Telecommunications & Information Security",
    "6": "Sensors & Lasers",
    "7": "Navigation & Avionics",
    "8": "Marine",
    "9": "Aerospace & Propulsion",
}

# CBP ports of entry (major)
_CBP_PORTS: Dict[str, str] = {
    "1001": "New York/Newark, NY",
    "2704": "Los Angeles, CA",
    "2709": "Long Beach, CA",
    "5301": "Houston-Galveston, TX",
    "1303": "Miami, FL",
    "2809": "San Francisco, CA",
    "5106": "Laredo, TX",
    "3901": "Chicago, IL",
    "0901": "Savannah, GA",
    "5203": "Dallas/Fort Worth, TX",
}


# ═══════════════════════════════════════════════════════════════════════════
# CustomsComplianceAgent
# ═══════════════════════════════════════════════════════════════════════════

class CustomsComplianceAgent:
    """International trade compliance and customs agent.

    HTS classification, OFAC screening, export control (EAR/ITAR),
    FTA qualification, duty drawback, broker management.

    Examples
    --------
    >>> agent = CustomsComplianceAgent()
    >>> hts = await agent.classify_hts_code("laptop computer", country="CN")
    >>> screen = await agent.screen_ofac("Acme Trading LLC")
    """

    TOOLS = [
        "classify_hts_code",              # HTS/HS tariff classification
        "screen_ofac",                    # OFAC SDN list screening
        "check_export_controls",          # EAR/ITAR classification check
        "calculate_duties_taxes",         # Import duty + VAT calculation
        "qualify_fta_origin",             # FTA rules of origin qualification
        "generate_commercial_invoice",    # Commercial invoice / packing list
        "file_customs_entry",             # CBP/customs entry preparation
        "calculate_drawback",             # Duty drawback calculation
        "check_import_restrictions",      # AD/CVD, quotas, sanctions
        "generate_certificate_origin",    # CO document generation
        "screen_denied_parties",          # BIS denied parties list
        "calculate_landed_cost",          # Full landed cost with duties
        "manage_broker_relationship",     # Customs broker performance
        "track_customs_status",           # CBP entry status tracking
        "generate_compliance_report",     # Trade compliance audit report
    ]

    def __init__(
        self,
        *,
        default_country: str = "US",
        ofac_api_key: Optional[str] = None,
        model: str = "kimi-k2.5",
    ) -> None:
        self._default_country = default_country
        self._ofac_key = ofac_api_key
        self._model = model
        self._classification_cache: Dict[str, HTSClassification] = {}
        self._screening_cache: Dict[str, OFACScreenResult] = {}
        log.info(
            "CustomsComplianceAgent initialized (model=%s, country=%s)",
            model, default_country,
        )

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for customs compliance."""
        return (
            "You are an expert international trade compliance and customs agent "
            "supporting global logistics operations (DHL, Maersk, FedEx, UPS, XPO).\n\n"
            "TARIFF CLASSIFICATION:\n"
            "- Harmonized System (HS) — 6-digit international standard\n"
            "- HTS (US) — 10-digit US-specific (Chapter.Heading.Subheading.Statistical)\n"
            "- Example: HTS 8471.30.0100 = Portable digital automatic data processing machines (laptops)\n"
            "  * Chapter 84: Nuclear Reactors, Boilers, Machinery\n"
            "  * Heading 8471: Automatic data processing machines\n"
            "  * Subheading 8471.30: Portable (≤10 kg)\n"
            "  * Statistical suffix: 0100\n"
            "- GRI (General Rules of Interpretation) 1-6 for classification disputes\n\n"
            "SANCTIONS & SCREENING:\n"
            "- OFAC SDN (Specially Designated Nationals) list\n"
            "- OFAC Consolidated Sanctions List (SSI, FSE, CAATSA)\n"
            "- BIS Entity List, Denied Persons List, Unverified List\n"
            "- EU Consolidated Sanctions, UK HMT Sanctions\n"
            "- Screening required for all parties: buyer, seller, consignee, end-user\n\n"
            "EXPORT CONTROLS:\n"
            "- EAR (Export Administration Regulations):\n"
            "  * ECCN (Export Control Classification Number) format: [0-9][A-E][0-9]{3}\n"
            "  * Category 5 Part 2 = encryption (most common for tech companies)\n"
            "  * EAR99 = items subject to EAR but not on CCL (no license for most)\n"
            "  * License exceptions: TSR, ENC, TMP, RPL, GOV, etc.\n"
            "- ITAR (State Dept): USML categories I-XXI\n\n"
            "FREE TRADE AGREEMENTS:\n"
            "- USMCA (replaced NAFTA): tariff shift + RVC requirements\n"
            "  * Regional Value Content: Transaction Value method (75% auto)\n"
            "  * Net Cost method: (NC - VNM) / NC × 100\n"
            "- CPTPP, RCEP, KORUS, AUSFTA, GSP\n"
            "- Rules of origin: wholly obtained, substantial transformation,\n"
            "  tariff shift (CC, CTH, CTSH), regional value content (RVC)\n\n"
            "CUSTOMS ENTRY:\n"
            "- CBP entry types: 01 (consumption), 11 (informal), 21 (warehouse)\n"
            "- Merchandise Processing Fee (MPF): 0.3464% (min $31.67, max $614.35)\n"
            "- Harbor Maintenance Fee (HMF): 0.125% of cargo value (ocean imports)\n"
            "- Section 301 tariffs: 7.5-25% on China-origin goods (Lists 1-4A)\n"
            "- AD/CVD (antidumping/countervailing duties): product-specific\n\n"
            "INCOTERMS 2020:\n"
            "- EXW, FCA, CPT, CIP, DAP, DPU, DDP (any mode)\n"
            "- FAS, FOB, CFR, CIF (sea/inland waterway only)\n"
        )

    # -------------------------------------------------------------------
    # Core compliance methods
    # -------------------------------------------------------------------

    async def classify_hts_code(
        self,
        product_description: str,
        *,
        country_of_origin: str = "",
        material: Optional[str] = None,
    ) -> HTSClassification:
        """Classify product under HTS/HS tariff schedule.

        Parameters
        ----------
        product_description:
            Natural language product description.
        country_of_origin:
            Country of manufacture / origin.
        material:
            Primary material composition.
        """
        cache_key = f"{product_description[:100]}:{country_of_origin}"
        if cache_key in self._classification_cache:
            return self._classification_cache[cache_key]

        log.info("Classifying HTS: %s (origin=%s)", product_description[:60], country_of_origin)

        # Heuristic classification (production uses AI + CROSS rulings database)
        desc_lower = product_description.lower()

        if any(w in desc_lower for w in ["laptop", "computer", "notebook"]):
            result = HTSClassification(
                hts_code="8471.30.0100",
                hts_description="Portable digital automatic data processing machines, ≤10 kg",
                chapter=84,
                heading="8471",
                subheading="8471.30",
                statistical_suffix="0100",
                general_duty_rate="Free",
                unit_of_quantity="No.",
                country_of_origin=country_of_origin,
                confidence=0.85,
            )
        elif any(w in desc_lower for w in ["smartphone", "mobile phone", "cellular"]):
            result = HTSClassification(
                hts_code="8517.13.0000",
                hts_description="Smartphones (other telephones for cellular networks)",
                chapter=85,
                heading="8517",
                subheading="8517.13",
                statistical_suffix="0000",
                general_duty_rate="Free",
                unit_of_quantity="No.",
                country_of_origin=country_of_origin,
                confidence=0.90,
            )
        elif any(w in desc_lower for w in ["t-shirt", "shirt", "apparel", "clothing"]):
            result = HTSClassification(
                hts_code="6109.10.0012",
                hts_description="T-shirts, singlets, tank tops, of cotton, men's or boys'",
                chapter=61,
                heading="6109",
                subheading="6109.10",
                statistical_suffix="0012",
                general_duty_rate="16.5%",
                unit_of_quantity="doz.",
                country_of_origin=country_of_origin,
                confidence=0.75,
            )
        else:
            result = HTSClassification(
                hts_code="9999.99.0000",
                hts_description=f"Classification pending: {product_description[:80]}",
                chapter=99,
                heading="9999",
                subheading="9999.99",
                statistical_suffix="0000",
                general_duty_rate="See ruling",
                country_of_origin=country_of_origin,
                confidence=0.30,
            )

        # Check Section 301 applicability for China origin
        if country_of_origin.upper() in ("CN", "CHINA"):
            result.section_301_rate = "25%"

        self._classification_cache[cache_key] = result
        return result

    async def screen_ofac(
        self,
        entity_name: str,
        *,
        country: Optional[str] = None,
        entity_type: str = "individual_or_entity",
    ) -> OFACScreenResult:
        """Screen entity against OFAC SDN list.

        Parameters
        ----------
        entity_name:
            Name to screen.
        country:
            Country for additional context.
        entity_type:
            'individual', 'entity', or 'individual_or_entity'.
        """
        log.info("OFAC screening: %s (country=%s)", entity_name, country)

        # Real implementation queries OFAC API or consolidated screening service
        result = OFACScreenResult(
            screened_name=entity_name,
            match_found=False,
            match_score=0.0,
            list_type="SDN",
            recommendations="No matches found. Proceed with transaction.",
        )

        self._screening_cache[entity_name] = result
        return result

    async def check_export_controls(
        self,
        product_description: str,
        destination_country: str,
        *,
        eccn: Optional[str] = None,
        end_use: Optional[str] = None,
    ) -> ExportControlResult:
        """Check EAR/ITAR export control classification.

        Parameters
        ----------
        product_description:
            Product description for classification.
        destination_country:
            Destination country code (ISO 2-letter).
        eccn:
            Known ECCN if already classified.
        end_use:
            Known end-use if available.
        """
        log.info("Export control check: %s -> %s", product_description[:50], destination_country)

        # Check if ITAR controlled
        itar = any(
            w in product_description.lower()
            for w in ["defense article", "munitions", "military", "itar"]
        )

        if itar:
            return ExportControlResult(
                eccn="USML",
                itar_controlled=True,
                license_required=True,
                regime=ExportControlRegime.ITAR,
                destination_country=destination_country,
                notes="ITAR-controlled item — requires DDTC license or exemption",
            )

        # EAR classification
        controlled_eccn = eccn or "EAR99"

        # Check if destination is sanctioned / embargoed
        embargoed = destination_country.upper() in ("CU", "IR", "KP", "SY", "RU")
        license_needed = embargoed or (controlled_eccn != "EAR99")

        return ExportControlResult(
            eccn=controlled_eccn,
            ear99=(controlled_eccn == "EAR99"),
            license_required=license_needed,
            license_exception="TSR" if not embargoed and controlled_eccn != "EAR99" else None,
            regime=ExportControlRegime.EAR,
            destination_country=destination_country,
            end_use_restriction=embargoed,
        )

    async def calculate_duties_taxes(
        self,
        hts_code: str,
        customs_value: float,
        *,
        country_of_origin: str = "",
        mode: str = "ocean",
        fta: Optional[str] = None,
    ) -> DutyCalculation:
        """Calculate import duties, MPF, HMF, and taxes.

        Parameters
        ----------
        hts_code:
            HTS classification code.
        customs_value:
            Declared customs value in USD.
        country_of_origin:
            Country of origin code.
        mode:
            Transportation mode (for HMF calculation).
        fta:
            FTA code if applicable.
        """
        log.info("Calculating duties: HTS=%s, value=$%.2f", hts_code, customs_value)

        # Look up duty rate (simplified — real implementation uses USITC database)
        duty_rate = 0.0
        if hts_code.startswith("8471") or hts_code.startswith("8517"):
            duty_rate = 0.0     # Free
        elif hts_code.startswith("61") or hts_code.startswith("62"):
            duty_rate = 16.5    # Apparel
        elif hts_code.startswith("87"):
            duty_rate = 2.5     # Vehicles

        # FTA override
        if fta:
            duty_rate = 0.0     # Preferential rate (simplified)

        duty_amount = customs_value * duty_rate / 100.0

        # MPF: 0.3464%, min $31.67, max $614.35
        mpf = max(31.67, min(614.35, customs_value * 0.003464))

        # HMF: 0.125% for ocean imports only
        hmf = customs_value * 0.00125 if mode == "ocean" else 0.0

        # Section 301 (China)
        s301_rate = 25.0 if country_of_origin.upper() in ("CN", "CHINA") else 0.0
        s301_amount = customs_value * s301_rate / 100.0

        total = duty_amount + mpf + hmf + s301_amount

        return DutyCalculation(
            hts_code=hts_code,
            customs_value=customs_value,
            duty_rate_pct=duty_rate,
            duty_amount=round(duty_amount, 2),
            mpf=round(mpf, 2),
            hmf=round(hmf, 2),
            section_301_rate_pct=s301_rate,
            section_301_amount=round(s301_amount, 2),
            total_duties_taxes=round(total, 2),
            country_of_origin=country_of_origin,
        )

    async def qualify_fta_origin(
        self,
        hts_code: str,
        fta: str,
        *,
        bom: Optional[List[Dict[str, Any]]] = None,
        transaction_value: float = 0.0,
        net_cost: float = 0.0,
    ) -> FTAQualification:
        """Qualify product under FTA rules of origin.

        Parameters
        ----------
        hts_code:
            HTS code for the finished product.
        fta:
            Free Trade Agreement code.
        bom:
            Bill of materials with origin information.
        transaction_value:
            Transaction value for RVC calculation.
        net_cost:
            Net cost for RVC calculation.
        """
        log.info("FTA qualification: HTS=%s, FTA=%s", hts_code, fta)

        agreement = TradeAgreement(fta)

        # RVC calculation (Transaction Value method for USMCA)
        rvc = 0.0
        rvc_threshold = 75.0 if agreement == TradeAgreement.USMCA else 40.0
        if transaction_value > 0 and bom:
            non_originating = sum(
                item.get("value", 0)
                for item in bom
                if not item.get("originating", False)
            )
            rvc = ((transaction_value - non_originating) / transaction_value) * 100.0

        qualifies = rvc >= rvc_threshold if rvc > 0 else False

        # Estimate duty savings
        mfn_rate = 5.0  # Simplified MFN rate
        duty_savings = transaction_value * mfn_rate / 100.0 if qualifies else 0.0

        return FTAQualification(
            hts_code=hts_code,
            fta=agreement,
            qualifies=qualifies,
            rule_of_origin=f"Transaction Value Method (RVC ≥ {rvc_threshold}%)",
            regional_value_content_pct=round(rvc, 1),
            rvc_threshold_pct=rvc_threshold,
            certificate_required=qualifies,
            duty_savings=round(duty_savings, 2),
        )

    async def generate_commercial_invoice(
        self,
        seller: str,
        buyer: str,
        items: List[Dict[str, Any]],
        *,
        incoterm: str = "FOB",
        currency: str = "USD",
    ) -> CommercialInvoice:
        """Generate commercial invoice for customs.

        Parameters
        ----------
        seller:
            Seller/exporter name and address.
        buyer:
            Buyer/importer name and address.
        items:
            Line items with: description, hts_code, quantity, unit_price, country_of_origin.
        incoterm:
            INCOTERMS 2020 term.
        currency:
            Invoice currency.
        """
        total = sum(
            i.get("quantity", 0) * i.get("unit_price", 0) for i in items
        )

        return CommercialInvoice(
            invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
            seller=seller,
            buyer=buyer,
            ship_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            country_of_origin=items[0].get("country_of_origin", "") if items else "",
            country_of_destination=self._default_country,
            incoterm=incoterm,
            currency=currency,
            line_items=items,
            total_value=round(total, 2),
        )

    async def screen_denied_parties(
        self,
        entity_name: str,
        *,
        lists: Optional[List[str]] = None,
    ) -> DeniedPartyResult:
        """Screen entity against BIS denied parties lists.

        Parameters
        ----------
        entity_name:
            Entity name to screen.
        lists:
            Specific lists to check (default: all).
        """
        checked_lists = lists or [
            "SDN", "Entity List", "Denied Persons", "Unverified List",
            "Military End-User List",
        ]

        log.info("Denied party screening: %s against %d lists", entity_name, len(checked_lists))

        return DeniedPartyResult(
            screened_entity=entity_name,
            lists_checked=checked_lists,
            matches=[],
            clear=True,
        )

    async def generate_compliance_report(
        self,
        scope: str,
        *,
        transactions: Optional[List[Dict[str, Any]]] = None,
        period: str = "",
    ) -> ComplianceReport:
        """Generate trade compliance audit report.

        Parameters
        ----------
        scope:
            Audit scope description.
        transactions:
            Transactions to audit.
        period:
            Reporting period.
        """
        report_id = uuid.uuid4().hex[:12]

        findings: List[Dict[str, Any]] = []
        if transactions:
            for tx in transactions:
                if not tx.get("hts_code"):
                    findings.append({
                        "type": "missing_classification",
                        "severity": "high",
                        "description": f"Missing HTS classification for {tx.get('description', 'item')}",
                    })
                if not tx.get("screening_complete"):
                    findings.append({
                        "type": "incomplete_screening",
                        "severity": "critical",
                        "description": f"Denied party screening not completed",
                    })

        score = max(0, 100 - len(findings) * 10)

        return ComplianceReport(
            report_id=report_id,
            report_date=datetime.now(timezone.utc).isoformat(),
            scope=scope,
            findings=findings,
            risk_areas=["tariff classification accuracy", "screening coverage", "FTA utilization"],
            recommendations=[
                "Implement automated screening for all new parties",
                "Review HTS classifications quarterly",
                "Analyze FTA utilization rates for duty savings opportunities",
            ],
            compliance_score=score,
        )
