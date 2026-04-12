"""Horizon Orchestra — External Service Connectors.

Each connector implements the Connector ABC and provides:
1. OAuth2, token, or key-based authentication
2. Action execution via a unified execute() interface
3. OpenAI-format tool definitions for agent integration
"""

from .base import Connector, ConnectorRegistry
from .gmail import GmailConnector
from .github import GitHubConnector
from .slack import SlackConnector
from .notion import NotionConnector
from .linear import LinearConnector
from .snowflake import SnowflakeConnector
from .gcal import GoogleCalendarConnector
from .gdrive import GoogleDriveConnector
from .jira import JiraConnector
from .hubspot import HubSpotConnector
from .airtable import AirtableConnector
from .stripe import StripeConnector
from .aws import AWSConnector
from .monday import MondayConnector
from .mcp_bridge import MCPBridge
from .salesforce import SalesforceConnector
from .google_workspace import GoogleWorkspaceConnector
from .microsoft365 import Microsoft365Connector
from .meta_business import MetaBusinessConnector
from .amazon_business import AmazonBusinessConnector
from .zapier import ZapierConnector
from .n8n import N8nConnector

__all__ = [
    "Connector",
    "ConnectorRegistry",
    "GmailConnector",
    "GitHubConnector",
    "SlackConnector",
    "NotionConnector",
    "LinearConnector",
    "SnowflakeConnector",
    "GoogleCalendarConnector",
    "GoogleDriveConnector",
    "JiraConnector",
    "HubSpotConnector",
    "AirtableConnector",
    "StripeConnector",
    "AWSConnector",
    "MondayConnector",
    "MCPBridge",
    "SalesforceConnector",
    "GoogleWorkspaceConnector",
    "Microsoft365Connector",
    "MetaBusinessConnector",
    "AmazonBusinessConnector",
    "ZapierConnector",
    "N8nConnector",
]
