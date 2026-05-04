"""Meta Business connector — Marketing API, WhatsApp Business, Instagram Graph API.

Covers Facebook/Meta Ads, Page management, WhatsApp Business messaging,
and Instagram content & insights via the Meta Graph API and Marketing API v20.

Requires: pip install requests

Env vars:
    META_APP_ID           — Meta App ID
    META_APP_SECRET       — Meta App Secret
    META_ACCESS_TOKEN     — Long-lived user/system access token
    META_AD_ACCOUNT_ID    — Default ad account ID (act_XXXXX)
    META_PAGE_ID          — Default Facebook Page ID
    META_WHATSAPP_TOKEN   — WhatsApp Cloud API access token
    META_PHONE_NUMBER_ID  — WhatsApp Business phone number ID
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from .base import Connector

__all__ = ["MetaBusinessConnector", "MetaBusinessError"]

log = logging.getLogger("orchestra.connectors.meta_business")

# Optional dependency guard
try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]

try:
    from facebook_business.api import FacebookAdsApi as _FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount as _AdAccount
except ImportError:
    _FacebookAdsApi = None  # type: ignore[assignment]
    _AdAccount = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class MetaBusinessError(Exception):
    """Base error for Meta Business connector."""


class MetaBusinessAuthError(MetaBusinessError):
    """Authentication / token failure."""


class MetaBusinessAPIError(MetaBusinessError):
    """Graph API / Marketing API call failure."""


class MetaBusinessRateLimitError(MetaBusinessError):
    """Rate limit or throttling from Meta APIs."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://graph.facebook.com/v20.0"
WHATSAPP_BASE = "https://graph.facebook.com/v20.0"
MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retry_with_backoff(coro_factory, *, max_retries: int = MAX_RETRIES):
    """Retry with exponential backoff on transient errors."""
    delay = INITIAL_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except MetaBusinessRateLimitError:
            if attempt < max_retries:
                log.warning("Meta API rate limited, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
        except (MetaBusinessAPIError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                log.warning(
                    "Meta API request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def _require_requests() -> Any:
    if _requests is None:
        raise MetaBusinessError("Meta Business connector requires: pip install requests")
    return _requests


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class MetaBusinessConnector(Connector):
    """Full Meta Business integration — Marketing API, WhatsApp, Instagram.

    Provides 18 tools covering ad management, page content, WhatsApp
    messaging, Instagram publishing, audience insights, and pixel events.
    """

    name = "meta_business"
    description = (
        "Manage Meta/Facebook Ads, Pages, WhatsApp Business messaging, "
        "and Instagram content via the Meta Graph API."
    )

    TOOLS: list[str] = [
        "meta_get_ad_accounts",
        "meta_get_campaigns",
        "meta_create_campaign",
        "meta_get_adsets",
        "meta_get_ads",
        "meta_get_insights",
        "meta_get_page_posts",
        "meta_create_page_post",
        "meta_get_page_insights",
        "meta_send_whatsapp_message",
        "meta_send_whatsapp_template",
        "meta_get_whatsapp_conversations",
        "meta_get_instagram_media",
        "meta_get_instagram_insights",
        "meta_create_instagram_post",
        "meta_get_audience_insights",
        "meta_get_pixel_events",
        "meta_upload_custom_audience",
    ]

    def __init__(self) -> None:
        self._access_token: str = ""
        self._app_id: str = ""
        self._app_secret: str = ""
        self._ad_account_id: str = ""
        self._page_id: str = ""
        self._whatsapp_token: str = ""
        self._phone_number_id: str = ""
        self._session: Any = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return bool(self._access_token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Meta Graph API.

        Credential keys:
            - access_token — long-lived user or system user token
            - app_id, app_secret — for token exchange / validation
            - ad_account_id — default ad account (act_XXXXX)
            - page_id — default Facebook Page ID
            - whatsapp_token — WhatsApp Cloud API token
            - phone_number_id — WhatsApp phone number ID
        """
        requests = _require_requests()

        self._access_token = credentials.get(
            "access_token", os.getenv("META_ACCESS_TOKEN", "")
        )
        self._app_id = credentials.get("app_id", os.getenv("META_APP_ID", ""))
        self._app_secret = credentials.get("app_secret", os.getenv("META_APP_SECRET", ""))
        self._ad_account_id = credentials.get(
            "ad_account_id", os.getenv("META_AD_ACCOUNT_ID", "")
        )
        self._page_id = credentials.get("page_id", os.getenv("META_PAGE_ID", ""))
        self._whatsapp_token = credentials.get(
            "whatsapp_token", os.getenv("META_WHATSAPP_TOKEN", "")
        )
        self._phone_number_id = credentials.get(
            "phone_number_id", os.getenv("META_PHONE_NUMBER_ID", "")
        )

        if not self._access_token:
            log.error("Meta Business: access_token is required")
            return False

        # Validate token
        try:
            resp = requests.get(
                f"{GRAPH_BASE}/me",
                params={"access_token": self._access_token},
                timeout=15,
            )
            if resp.status_code != 200:
                raise MetaBusinessAuthError(f"Token validation failed: {resp.text[:300]}")
        except MetaBusinessAuthError:
            raise
        except Exception as exc:
            raise MetaBusinessAuthError(f"Token validation error: {exc}") from exc

        # Initialize Facebook Business SDK if available
        if _FacebookAdsApi and self._app_id and self._app_secret:
            try:
                _FacebookAdsApi.init(self._app_id, self._app_secret, self._access_token)
            except Exception:
                log.debug("Facebook Business SDK init skipped")

        self._session = requests.Session()
        log.info("Meta Business connected")
        return True

    async def disconnect(self) -> None:
        """Clear authentication state."""
        self._access_token = ""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        log.info("Meta Business disconnected")

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _graph_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET from Meta Graph API."""
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        p = dict(params or {})
        p["access_token"] = self._access_token
        resp = self._session.get(url, params=p, timeout=30)
        if resp.status_code == 429 or (resp.status_code == 400 and "rate" in resp.text.lower()):
            raise MetaBusinessRateLimitError("Meta API rate limited")
        if resp.status_code >= 400:
            raise MetaBusinessAPIError(f"GET {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _graph_post(self, path: str, data: dict[str, Any] | None = None, json_data: Any = None) -> Any:
        """POST to Meta Graph API."""
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        params = {"access_token": self._access_token}
        if json_data is not None:
            resp = self._session.post(url, params=params, json=json_data, timeout=30)
        else:
            resp = self._session.post(url, params=params, data=data, timeout=30)
        if resp.status_code == 429 or (resp.status_code == 400 and "rate" in resp.text.lower()):
            raise MetaBusinessRateLimitError("Meta API rate limited")
        if resp.status_code >= 400:
            raise MetaBusinessAPIError(f"POST {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _whatsapp_post(self, path: str, json_data: Any) -> Any:
        """POST to WhatsApp Cloud API."""
        token = self._whatsapp_token or self._access_token
        url = f"{WHATSAPP_BASE}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = self._session.post(url, json=json_data, headers=headers, timeout=30)
        if resp.status_code >= 400:
            raise MetaBusinessAPIError(f"WhatsApp POST {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _whatsapp_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET from WhatsApp Cloud API."""
        token = self._whatsapp_token or self._access_token
        url = f"{WHATSAPP_BASE}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = self._session.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code >= 400:
            raise MetaBusinessAPIError(f"WhatsApp GET {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action to its handler with retry/backoff."""
        if not self.connected:
            return {"error": "Meta Business not connected. Call connect() first."}

        dispatch: dict[str, Any] = {
            "meta_get_ad_accounts": self._get_ad_accounts,
            "meta_get_campaigns": self._get_campaigns,
            "meta_create_campaign": self._create_campaign,
            "meta_get_adsets": self._get_adsets,
            "meta_get_ads": self._get_ads,
            "meta_get_insights": self._get_insights,
            "meta_get_page_posts": self._get_page_posts,
            "meta_create_page_post": self._create_page_post,
            "meta_get_page_insights": self._get_page_insights,
            "meta_send_whatsapp_message": self._send_whatsapp_message,
            "meta_send_whatsapp_template": self._send_whatsapp_template,
            "meta_get_whatsapp_conversations": self._get_whatsapp_conversations,
            "meta_get_instagram_media": self._get_instagram_media,
            "meta_get_instagram_insights": self._get_instagram_insights,
            "meta_create_instagram_post": self._create_instagram_post,
            "meta_get_audience_insights": self._get_audience_insights,
            "meta_get_pixel_events": self._get_pixel_events,
            "meta_upload_custom_audience": self._upload_custom_audience,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown Meta Business action: {action}"}
        try:
            return await _retry_with_backoff(lambda: handler(params))
        except MetaBusinessError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            log.exception("Unexpected error in Meta Business action %s", action)
            return {"error": f"Internal error: {exc}"}

    # ------------------------------------------------------------------
    # Tool implementations (18 tools)
    # ------------------------------------------------------------------

    # ---- Ad Management ----

    async def _get_ad_accounts(self, params: dict[str, Any]) -> dict[str, Any]:
        """List ad accounts accessible by the current token."""
        data = self._graph_get("me/adaccounts", params={
            "fields": "id,name,account_status,currency,timezone_name,amount_spent",
        })
        accounts = [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "status": a.get("account_status"),
                "currency": a.get("currency"),
                "timezone": a.get("timezone_name"),
                "amount_spent": a.get("amount_spent"),
            }
            for a in data.get("data", [])
        ]
        return {"count": len(accounts), "accounts": accounts}

    async def _get_campaigns(self, params: dict[str, Any]) -> dict[str, Any]:
        """List campaigns for an ad account."""
        account_id = params.get("account_id", self._ad_account_id)
        status = params.get("status", "")
        if not account_id:
            return {"error": "account_id is required"}
        fields = "id,name,objective,status,daily_budget,lifetime_budget,start_time,stop_time"
        p: dict[str, Any] = {"fields": fields}
        if status:
            p["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{status}"]}}]'
        data = self._graph_get(f"{account_id}/campaigns", params=p)
        return {"campaigns": data.get("data", [])}

    async def _create_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new ad campaign."""
        account_id = params.get("account_id", self._ad_account_id)
        name = params.get("name", "")
        objective = params.get("objective", "OUTCOME_AWARENESS")
        budget = params.get("budget", "")
        status_val = params.get("status", "PAUSED")
        if not account_id or not name:
            return {"error": "account_id and name are required"}
        body: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": status_val,
            "special_ad_categories": [],
        }
        if budget:
            body["daily_budget"] = str(budget)
        result = self._graph_post(f"{account_id}/campaigns", data=body)
        return {"campaign_id": result.get("id"), "created": True}

    async def _get_adsets(self, params: dict[str, Any]) -> dict[str, Any]:
        """List ad sets in a campaign."""
        campaign_id = params.get("campaign_id", "")
        if not campaign_id:
            return {"error": "campaign_id is required"}
        fields = "id,name,status,targeting,daily_budget,start_time,end_time,bid_amount"
        data = self._graph_get(f"{campaign_id}/adsets", params={"fields": fields})
        return {"adsets": data.get("data", [])}

    async def _get_ads(self, params: dict[str, Any]) -> dict[str, Any]:
        """List individual ads in an ad set."""
        adset_id = params.get("adset_id", "")
        if not adset_id:
            return {"error": "adset_id is required"}
        fields = "id,name,status,creative,tracking_specs"
        data = self._graph_get(f"{adset_id}/ads", params={"fields": fields})
        return {"ads": data.get("data", [])}

    async def _get_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get performance insights for any ad object (account, campaign, adset, ad)."""
        object_id = params.get("object_id", self._ad_account_id)
        metrics = params.get("metrics", "impressions,clicks,spend,ctr,cpc,cpm")
        date_range = params.get("date_range", {})
        if not object_id:
            return {"error": "object_id is required"}
        p: dict[str, Any] = {"fields": metrics}
        if date_range:
            p["time_range"] = date_range
        data = self._graph_get(f"{object_id}/insights", params=p)
        return {"insights": data.get("data", [])}

    # ---- Facebook Pages ----

    async def _get_page_posts(self, params: dict[str, Any]) -> dict[str, Any]:
        """List recent posts on a Facebook Page."""
        page_id = params.get("page_id", self._page_id)
        limit = params.get("limit", 25)
        if not page_id:
            return {"error": "page_id is required"}
        data = self._graph_get(f"{page_id}/posts", params={
            "fields": "id,message,created_time,type,permalink_url",
            "limit": limit,
        })
        return {"posts": data.get("data", [])}

    async def _create_page_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Publish a post to a Facebook Page."""
        page_id = params.get("page_id", self._page_id)
        message = params.get("message", "")
        media_url = params.get("media_url", "")
        if not page_id or not message:
            return {"error": "page_id and message are required"}
        body: dict[str, Any] = {"message": message}
        if media_url:
            body["link"] = media_url
        result = self._graph_post(f"{page_id}/feed", data=body)
        return {"post_id": result.get("id"), "published": True}

    async def _get_page_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get Page-level insights/analytics."""
        page_id = params.get("page_id", self._page_id)
        metrics = params.get("metrics", "page_impressions,page_engaged_users,page_fans")
        period = params.get("period", "day")
        if not page_id:
            return {"error": "page_id is required"}
        data = self._graph_get(f"{page_id}/insights", params={
            "metric": metrics,
            "period": period,
        })
        return {"insights": data.get("data", [])}

    # ---- WhatsApp Business ----

    async def _send_whatsapp_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a text message via WhatsApp Business Cloud API."""
        to = params.get("to", "")
        text = params.get("text", "")
        phone_id = params.get("phone_number_id", self._phone_number_id)
        if not to or not text or not phone_id:
            return {"error": "to, text, and phone_number_id are required"}
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        result = self._whatsapp_post(f"{phone_id}/messages", json_data=body)
        return {
            "message_id": result.get("messages", [{}])[0].get("id"),
            "sent": True,
        }

    async def _send_whatsapp_template(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a WhatsApp template message."""
        to = params.get("to", "")
        template = params.get("template", "")
        template_params: list[dict[str, Any]] = params.get("params", [])
        phone_id = params.get("phone_number_id", self._phone_number_id)
        if not to or not template or not phone_id:
            return {"error": "to, template, and phone_number_id are required"}
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": params.get("language", "en_US")},
            },
        }
        if template_params:
            body["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": template_params,
                }
            ]
        result = self._whatsapp_post(f"{phone_id}/messages", json_data=body)
        return {
            "message_id": result.get("messages", [{}])[0].get("id"),
            "template": template,
            "sent": True,
        }

    async def _get_whatsapp_conversations(self, params: dict[str, Any]) -> dict[str, Any]:
        """List recent WhatsApp conversations / analytics."""
        limit = params.get("limit", 25)
        phone_id = params.get("phone_number_id", self._phone_number_id)
        if not phone_id:
            return {"error": "phone_number_id is required"}
        # WhatsApp conversation analytics endpoint
        try:
            data = self._whatsapp_get(
                f"{phone_id}/conversation_analytics",
                params={"granularity": "DAILY", "limit": limit},
            )
            return {"conversations": data.get("data", data)}
        except MetaBusinessAPIError:
            # Fallback: phone number info
            data = self._whatsapp_get(phone_id)
            return {"phone_info": data, "note": "Conversation analytics may require specific permissions"}

    # ---- Instagram ----

    async def _get_instagram_media(self, params: dict[str, Any]) -> dict[str, Any]:
        """List recent Instagram media/posts."""
        user_id = params.get("user_id", "me")
        limit = params.get("limit", 25)
        data = self._graph_get(f"{user_id}/media", params={
            "fields": "id,caption,media_type,media_url,thumbnail_url,timestamp,permalink,like_count,comments_count",
            "limit": limit,
        })
        return {"media": data.get("data", [])}

    async def _get_instagram_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get insights for a specific Instagram media post."""
        media_id = params.get("media_id", "")
        metrics = params.get("metrics", "impressions,reach,engagement,saved")
        if not media_id:
            return {"error": "media_id is required"}
        data = self._graph_get(f"{media_id}/insights", params={"metric": metrics})
        return {"media_id": media_id, "insights": data.get("data", [])}

    async def _create_instagram_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create and publish an Instagram post (requires business account)."""
        image_url = params.get("image_url", "")
        caption = params.get("caption", "")
        user_id = params.get("user_id", "me")
        if not image_url:
            return {"error": "image_url is required"}
        # Step 1: Create media container
        container = self._graph_post(f"{user_id}/media", data={
            "image_url": image_url,
            "caption": caption,
        })
        container_id = container.get("id", "")
        if not container_id:
            return {"error": "Failed to create media container"}
        # Step 2: Publish
        result = self._graph_post(f"{user_id}/media_publish", data={
            "creation_id": container_id,
        })
        return {"post_id": result.get("id"), "published": True}

    # ---- Audience & Pixel ----

    async def _get_audience_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get audience insights for targeting analysis."""
        account_id = params.get("account_id", self._ad_account_id)
        targeting = params.get("targeting", {})
        if not account_id:
            return {"error": "account_id is required"}
        p: dict[str, Any] = {
            "fields": "id,name,approximate_count",
        }
        if targeting:
            import json
            p["targeting_spec"] = json.dumps(targeting)
        try:
            data = self._graph_get(f"{account_id}/reachestimate", params=p)
            return {"audience": data.get("data", data)}
        except MetaBusinessAPIError:
            # Fallback to custom audiences list
            data = self._graph_get(f"{account_id}/customaudiences", params={
                "fields": "id,name,approximate_count,data_source",
            })
            return {"custom_audiences": data.get("data", [])}

    async def _get_pixel_events(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get events from a Meta Pixel."""
        pixel_id = params.get("pixel_id", "")
        event_name = params.get("event_name", "")
        date_range = params.get("date_range", {})
        if not pixel_id:
            return {"error": "pixel_id is required"}
        p: dict[str, Any] = {
            "fields": "data",
        }
        if event_name:
            p["event"] = event_name
        if date_range:
            import json
            p["time_range"] = json.dumps(date_range)
        data = self._graph_get(f"{pixel_id}/stats", params=p)
        return {"pixel_id": pixel_id, "events": data.get("data", [])}

    async def _upload_custom_audience(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create/update a custom audience from email hashes."""
        account_id = params.get("account_id", self._ad_account_id)
        emails: list[str] = params.get("emails", [])
        if not account_id or not emails:
            return {"error": "account_id and emails are required"}
        import hashlib
        hashed = [hashlib.sha256(e.strip().lower().encode()).hexdigest() for e in emails]
        # Create audience
        audience = self._graph_post(f"{account_id}/customaudiences", data={
            "name": params.get("name", "Custom Audience Upload"),
            "subtype": "CUSTOM",
            "description": "Uploaded via Horizon Orchestra",
            "customer_file_source": "USER_PROVIDED_ONLY",
        })
        audience_id = audience.get("id", "")
        if not audience_id:
            return {"error": "Failed to create custom audience"}
        # Add users in batches
        batch_size = 10000
        total_added = 0
        for i in range(0, len(hashed), batch_size):
            batch = hashed[i:i + batch_size]
            import json
            payload = {
                "schema": "EMAIL_SHA256",
                "data": json.dumps(batch),
            }
            self._graph_post(f"{audience_id}/users", data=payload)
            total_added += len(batch)
        return {
            "audience_id": audience_id,
            "emails_uploaded": total_added,
            "created": True,
        }

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all 18 Meta Business tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "meta_get_ad_accounts",
                    "description": "List Meta/Facebook ad accounts accessible by the current token.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_campaigns",
                    "description": "List ad campaigns for a Meta ad account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string", "description": "Ad account ID (act_XXXXX)"},
                            "status": {"type": "string", "description": "Filter by campaign status"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_create_campaign",
                    "description": "Create a new Meta/Facebook ad campaign.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Campaign name"},
                            "objective": {"type": "string", "description": "Campaign objective (e.g. OUTCOME_AWARENESS)"},
                            "budget": {"type": "string", "description": "Daily budget in cents"},
                            "status": {"type": "string", "description": "Campaign status (PAUSED, ACTIVE)"},
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_adsets",
                    "description": "List ad sets within a campaign.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "campaign_id": {"type": "string", "description": "Campaign ID"},
                        },
                        "required": ["campaign_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_ads",
                    "description": "List individual ads within an ad set.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "adset_id": {"type": "string", "description": "Ad set ID"},
                        },
                        "required": ["adset_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_insights",
                    "description": "Get performance insights (impressions, clicks, spend) for any ad object.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_id": {"type": "string", "description": "Ad object ID (account, campaign, adset, or ad)"},
                            "metrics": {"type": "string", "description": "Comma-separated metric names"},
                            "date_range": {"type": "object", "description": "Time range {since, until} in YYYY-MM-DD"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_page_posts",
                    "description": "List recent posts on a Facebook Page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Facebook Page ID"},
                            "limit": {"type": "integer", "description": "Max posts (default 25)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_create_page_post",
                    "description": "Publish a post to a Facebook Page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Facebook Page ID"},
                            "message": {"type": "string", "description": "Post message text"},
                            "media_url": {"type": "string", "description": "Optional media/link URL"},
                        },
                        "required": ["message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_page_insights",
                    "description": "Get Facebook Page insights and analytics.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Facebook Page ID"},
                            "metrics": {"type": "string", "description": "Comma-separated metrics"},
                            "period": {"type": "string", "description": "Aggregation period (day, week, month)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_send_whatsapp_message",
                    "description": "Send a text message via WhatsApp Business Cloud API.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient phone number (E.164 format)"},
                            "text": {"type": "string", "description": "Message text"},
                        },
                        "required": ["to", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_send_whatsapp_template",
                    "description": "Send a WhatsApp template message with parameters.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient phone number"},
                            "template": {"type": "string", "description": "Template name"},
                            "params": {
                                "type": "array", "items": {"type": "object"},
                                "description": "Template parameter values",
                            },
                        },
                        "required": ["to", "template"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_whatsapp_conversations",
                    "description": "List recent WhatsApp conversations / analytics.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max conversations (default 25)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_instagram_media",
                    "description": "List recent Instagram media/posts for a user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string", "description": "Instagram user ID (default: me)"},
                            "limit": {"type": "integer", "description": "Max posts (default 25)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_instagram_insights",
                    "description": "Get insights for a specific Instagram media post.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "media_id": {"type": "string", "description": "Instagram media ID"},
                            "metrics": {"type": "string", "description": "Comma-separated metrics"},
                        },
                        "required": ["media_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_create_instagram_post",
                    "description": "Create and publish an Instagram post (business account required).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_url": {"type": "string", "description": "Public URL of the image"},
                            "caption": {"type": "string", "description": "Post caption text"},
                        },
                        "required": ["image_url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_audience_insights",
                    "description": "Get audience insights and reach estimates for targeting.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string", "description": "Ad account ID"},
                            "targeting": {"type": "object", "description": "Targeting spec object"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_get_pixel_events",
                    "description": "Get events from a Meta Pixel for tracking analysis.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                            "event_name": {"type": "string", "description": "Filter by event name"},
                            "date_range": {"type": "object", "description": "Time range filter"},
                        },
                        "required": ["pixel_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "meta_upload_custom_audience",
                    "description": "Create a custom audience from email addresses (hashed automatically).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string", "description": "Ad account ID"},
                            "emails": {
                                "type": "array", "items": {"type": "string"},
                                "description": "List of email addresses to upload",
                            },
                        },
                        "required": ["emails"],
                    },
                },
            },
        ]
