"""Horizon Orchestra — Pre-Built Team Templates.

Four production-ready team factories that return fully configured
:class:`~orchestra.teams.team.OrchestraTeam` instances with all
specialists pre-registered and ready to run.

Factories
---------
:func:`enterprise_connect_team`
    Cross-platform enterprise intelligence (Salesforce, Google,
    Microsoft, Meta, Amazon).

:func:`coding_team`
    Software development pipeline (architect, implementer, reviewer,
    tester, deployer).

:func:`research_team`
    Deep research with parallel agents (retriever, analyst, writer,
    verifier).

:func:`sales_team`
    Full sales-intelligence pipeline (prospector, researcher, writer,
    analyst).

Example::

    from orchestra.teams.pre_built_teams import coding_team
    team = coding_team()
    result = await team.run("Implement a REST API for user management")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .team import OrchestraTeam, TeamConfig, Specialist
from .context_bus import ContextBus
from .team_memory import TeamMemory
from .inter_agent_trust import InterAgentTrust, TrustLevel

__all__ = [
    "enterprise_connect_team",
    "coding_team",
    "research_team",
    "sales_team",
]

log = logging.getLogger("orchestra.teams.pre_built_teams")


# ---------------------------------------------------------------------------
# Helper: synchronous specialist addition
# ---------------------------------------------------------------------------

def _add_specialist_sync(
    team: OrchestraTeam,
    name: str,
    capabilities: list[str],
    arch: str = "A",
    model: str = "kimi-k2.5",
    connectors: list[str] | None = None,
    trust_level: str = "team",
    org_id: str = "default",
) -> Specialist:
    """Synchronously create and register a :class:`Specialist`.

    Bypasses the async ``add_specialist`` path so factory functions
    can build teams without an active event loop.
    """
    import uuid
    connectors = connectors or []

    spec = Specialist(
        name=name,
        capabilities=capabilities,
        architecture=arch,
        model=model,
        connectors=connectors,
        trust_level=trust_level,
        org_id=org_id,
    )

    team._specialists[spec.agent_id] = spec
    team._bus.register_agent(spec.agent_id)

    if team._trust is not None:
        team._trust.register_agent(
            spec.agent_id,
            trust_level=TrustLevel.from_string(trust_level),
            org_id=org_id,
        )

    return spec


# ===========================================================================
# 1. Enterprise Connect Team
# ===========================================================================

def enterprise_connect_team(
    name: str = "enterprise-connect",
    coordinator_model: str = "kimi-k2.5",
    enable_cross_org: bool = True,
) -> OrchestraTeam:
    """Build an enterprise cross-platform intelligence team.

    Connects Salesforce, Google Workspace, Microsoft 365, Meta, and
    Amazon services through five specialist agents coordinated by a
    central planner.

    Specialists
    -----------
    - **salesforce-specialist** — SOQL queries, CRM operations, bulk
      data management, opportunity tracking.
    - **google-specialist** — Google Workspace, Drive, Meet, Calendar,
      Gmail, Sheets, Docs integration.
    - **microsoft-specialist** — Teams, SharePoint, Azure AD, OneDrive,
      Outlook, Power Platform.
    - **meta-specialist** — Meta Ads, WhatsApp Business, Instagram
      Graph API, Facebook Pages.
    - **amazon-specialist** — AWS services, Bedrock, S3, DynamoDB,
      Lambda, CloudFormation.

    Parameters
    ----------
    name:
        Team name (default ``"enterprise-connect"``).
    coordinator_model:
        LLM model for the coordinator.
    enable_cross_org:
        Whether agents from different orgs may interact.

    Returns
    -------
    OrchestraTeam
        A fully configured team ready for ``await team.run(…)``.
    """
    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=10,
        max_concurrent_tasks=50,
        enable_cross_org=enable_cross_org,
        architecture="E",
        context_bus_capacity=10_000,
    )
    team = OrchestraTeam(config)

    # -- Salesforce specialist --
    _add_specialist_sync(
        team,
        name="salesforce-specialist",
        capabilities=[
            "salesforce", "soql", "crm", "bulk-ops",
            "opportunity-tracking", "lead-management",
            "salesforce-reports", "apex",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["salesforce", "salesforce-bulk"],
    )

    # -- Google specialist --
    _add_specialist_sync(
        team,
        name="google-specialist",
        capabilities=[
            "google-workspace", "drive", "meet", "calendar",
            "gmail", "sheets", "docs", "slides",
            "google-admin", "gcp",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["google-workspace", "google-drive", "gmail"],
    )

    # -- Microsoft specialist --
    _add_specialist_sync(
        team,
        name="microsoft-specialist",
        capabilities=[
            "teams", "sharepoint", "azure-ad", "onedrive",
            "outlook", "power-platform", "microsoft-365",
            "graph-api", "azure",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["microsoft-graph", "azure-ad", "sharepoint"],
    )

    # -- Meta specialist --
    _add_specialist_sync(
        team,
        name="meta-specialist",
        capabilities=[
            "meta-ads", "whatsapp-business", "instagram",
            "facebook-pages", "graph-api", "messenger",
            "meta-business-suite", "ad-campaigns",
        ],
        arch="C",
        model="kimi-k2.5",
        connectors=["meta-ads", "whatsapp", "instagram"],
    )

    # -- Amazon specialist --
    _add_specialist_sync(
        team,
        name="amazon-specialist",
        capabilities=[
            "aws", "bedrock", "s3", "dynamodb", "lambda",
            "cloudformation", "iam", "sqs", "sns",
            "ec2", "ecs",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["aws", "bedrock", "s3"],
    )

    log.info(
        "Built %s with %d specialists",
        name,
        len(team.specialists),
    )
    return team


# ===========================================================================
# 2. Coding Team
# ===========================================================================

def coding_team(
    name: str = "coding-team",
    coordinator_model: str = "kimi-k2.5",
) -> OrchestraTeam:
    """Build a multi-agent software development team.

    Modelled after collaborative coding workflows: an architect plans
    the design, an implementer writes code, a reviewer checks quality,
    a tester validates correctness, and a deployer handles CI/CD.

    Specialists
    -----------
    - **architect** — System design, API design, database schema,
      architecture decisions.
    - **implementer** — Writing production code in Python, TypeScript,
      Rust, Go, and other languages.
    - **reviewer** — Code review, security audit, performance analysis,
      best-practice enforcement.
    - **tester** — Unit tests, integration tests, end-to-end tests,
      test coverage analysis.
    - **deployer** — CI/CD pipelines, Docker, Kubernetes, deployment
      automation, infrastructure-as-code.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=8,
        max_concurrent_tasks=30,
        architecture="C",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    # -- Architect --
    _add_specialist_sync(
        team,
        name="architect",
        capabilities=[
            "design", "planning", "api-design", "database-schema",
            "architecture", "system-design", "documentation",
            "trade-off-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["github", "notion"],
    )

    # -- Implementer --
    _add_specialist_sync(
        team,
        name="implementer",
        capabilities=[
            "python", "typescript", "rust", "go", "javascript",
            "coding", "implementation", "refactoring",
            "algorithms", "data-structures",
        ],
        arch="C",
        model="kimi-k2.5",
        connectors=["github", "code-sandbox"],
    )

    # -- Reviewer --
    _add_specialist_sync(
        team,
        name="reviewer",
        capabilities=[
            "code-review", "security-audit", "performance-analysis",
            "best-practices", "linting", "static-analysis",
            "vulnerability-scan",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["github"],
    )

    # -- Tester --
    _add_specialist_sync(
        team,
        name="tester",
        capabilities=[
            "testing", "unit-tests", "integration-tests", "e2e-tests",
            "test-coverage", "pytest", "jest", "playwright",
            "load-testing",
        ],
        arch="C",
        model="kimi-k2.5",
        connectors=["github", "code-sandbox"],
    )

    # -- Deployer --
    _add_specialist_sync(
        team,
        name="deployer",
        capabilities=[
            "cicd", "docker", "kubernetes", "deployment",
            "infrastructure", "terraform", "github-actions",
            "monitoring", "observability",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["github", "aws", "docker-hub"],
    )

    log.info(
        "Built %s with %d specialists",
        name,
        len(team.specialists),
    )
    return team


# ===========================================================================
# 3. Research Team
# ===========================================================================

def research_team(
    name: str = "research-team",
    coordinator_model: str = "kimi-k2.5",
) -> OrchestraTeam:
    """Build a deep-research team with parallel specialist agents.

    The retriever gathers sources, the analyst synthesises findings,
    the writer produces the final report, and the verifier checks all
    citations and facts.

    Specialists
    -----------
    - **retriever** — Web search, Sonar integration, RAG pipelines,
      document fetching, knowledge-base queries.
    - **analyst** — Fact-checking, data analysis, cross-reference
      verification, synthesis of multiple sources.
    - **writer** — Report generation, executive summaries, technical
      writing, markdown/PDF output.
    - **verifier** — Citation verification, source validation, bias
      detection, consistency checks.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=6,
        max_concurrent_tasks=20,
        architecture="A",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    # -- Retriever --
    _add_specialist_sync(
        team,
        name="retriever",
        capabilities=[
            "web-search", "sonar", "rag", "document-fetching",
            "knowledge-base", "api-queries", "data-collection",
            "source-gathering",
        ],
        arch="B",
        model="kimi-k2.5",
        connectors=["perplexity", "web-browser", "arxiv"],
    )

    # -- Analyst --
    _add_specialist_sync(
        team,
        name="analyst",
        capabilities=[
            "fact-checking", "data-analysis", "synthesis",
            "cross-reference", "statistics", "comparison",
            "trend-analysis", "critical-thinking",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["python-sandbox"],
    )

    # -- Writer --
    _add_specialist_sync(
        team,
        name="writer",
        capabilities=[
            "report-generation", "executive-summary",
            "technical-writing", "markdown", "pdf-generation",
            "copywriting", "editing", "formatting",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["google-docs", "notion"],
    )

    # -- Verifier --
    _add_specialist_sync(
        team,
        name="verifier",
        capabilities=[
            "citation-verification", "source-validation",
            "bias-detection", "consistency-check",
            "accuracy-audit", "plagiarism-check",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["web-browser", "perplexity"],
    )

    log.info(
        "Built %s with %d specialists",
        name,
        len(team.specialists),
    )
    return team


# ===========================================================================
# 4. Sales Team
# ===========================================================================

def sales_team(
    name: str = "sales-team",
    coordinator_model: str = "kimi-k2.5",
) -> OrchestraTeam:
    """Build a full sales-intelligence pipeline team.

    The prospector identifies leads, the researcher enriches them with
    company and contact data, the writer crafts personalised outreach,
    and the analyst tracks pipeline metrics.

    Specialists
    -----------
    - **prospector** — Lead discovery from Salesforce, LinkedIn, and
      intent-signal databases.
    - **researcher** — Company research, org charts, funding history,
      tech-stack identification.
    - **writer** — Personalised email and message outreach, sequence
      creation, A/B copy variants.
    - **analyst** — Pipeline analytics, conversion funnel analysis,
      forecasting, win/loss patterns.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=6,
        max_concurrent_tasks=30,
        architecture="E",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    # -- Prospector --
    _add_specialist_sync(
        team,
        name="prospector",
        capabilities=[
            "salesforce", "linkedin", "lead-discovery",
            "intent-signals", "icp-matching", "list-building",
            "crm-search", "enrichment",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["salesforce", "linkedin", "clearbit"],
    )

    # -- Researcher --
    _add_specialist_sync(
        team,
        name="researcher",
        capabilities=[
            "company-research", "org-charts", "funding-history",
            "tech-stack", "competitive-intel", "news-monitoring",
            "financial-data", "industry-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["perplexity", "web-browser", "crunchbase"],
    )

    # -- Writer --
    _add_specialist_sync(
        team,
        name="writer",
        capabilities=[
            "email-outreach", "personalisation", "copywriting",
            "sequence-creation", "ab-testing", "messaging",
            "value-propositions", "call-scripts",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["gmail", "outreach", "salesloft"],
    )

    # -- Analyst --
    _add_specialist_sync(
        team,
        name="analyst",
        capabilities=[
            "pipeline-analytics", "conversion-funnel",
            "forecasting", "win-loss-analysis", "kpi-tracking",
            "reporting", "dashboards", "data-visualisation",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["salesforce", "python-sandbox", "tableau"],
    )

    log.info(
        "Built %s with %d specialists",
        name,
        len(team.specialists),
    )
    return team
