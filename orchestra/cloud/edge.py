"""Edge Functions — Lambda@Edge / CloudFront for global low-latency routing.

Routes requests to the nearest region, handles caching for repeated
queries, and provides global CDN for workspace file delivery.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["EdgeRouter", "EdgeConfig"]
log = logging.getLogger("orchestra.cloud.edge")


@dataclass
class EdgeConfig:
    cloudfront_distribution: str = ""
    primary_region: str = "us-east-1"
    replica_regions: list[str] = field(default_factory=lambda: ["us-west-2", "eu-west-1", "ap-northeast-1"])
    cache_ttl: int = 300                  # seconds for cacheable responses
    enable_response_cache: bool = True
    enable_geo_routing: bool = True


class EdgeRouter:
    """Global edge routing and caching layer.

    Sits in front of Lambda/Terafab to provide:
    1. Geo-routing to the nearest region
    2. Response caching for repeated queries
    3. CDN for workspace files and generated assets
    """

    def __init__(self, config: EdgeConfig | None = None) -> None:
        self.config = config or EdgeConfig()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._region_latencies: dict[str, float] = {}

    async def route(self, request: dict[str, Any], source_region: str = "") -> dict[str, Any]:
        """Route a request to the best region/backend."""
        # Check cache first
        if self.config.enable_response_cache:
            cached = self._check_cache(request)
            if cached:
                return {"result": cached, "source": "edge_cache", "region": "edge"}

        # Determine best region
        if self.config.enable_geo_routing and source_region:
            region = self._nearest_region(source_region)
        else:
            region = self.config.primary_region

        return {
            "route_to": region,
            "function": f"horizon-orchestra-{region}",
            "source": "edge_router",
            "cache_key": self._cache_key(request),
        }

    async def cache_response(self, request: dict[str, Any], response: Any) -> None:
        """Cache a response at the edge."""
        if not self.config.enable_response_cache:
            return
        key = self._cache_key(request)
        self._cache[key] = (time.time(), response)
        # Trim cache
        if len(self._cache) > 10000:
            cutoff = time.time() - self.config.cache_ttl
            self._cache = {k: v for k, v in self._cache.items() if v[0] > cutoff}

    def _check_cache(self, request: dict[str, Any]) -> Any | None:
        key = self._cache_key(request)
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self.config.cache_ttl:
                return val
            del self._cache[key]
        return None

    def _cache_key(self, request: dict[str, Any]) -> str:
        payload = json.dumps(request, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _nearest_region(self, source: str) -> str:
        """Pick the nearest AWS region based on geographic proximity."""
        geo_map = {
            "us": "us-east-1", "na": "us-east-1",
            "eu": "eu-west-1", "uk": "eu-west-1",
            "ap": "ap-northeast-1", "as": "ap-northeast-1",
            "sa": "us-east-1", "af": "eu-west-1", "oc": "ap-northeast-1",
        }
        prefix = source[:2].lower()
        return geo_map.get(prefix, self.config.primary_region)

    async def setup_cloudfront(self, lambda_url: str, s3_bucket: str = "") -> dict[str, Any]:
        """Create CloudFront distribution in front of Lambda + S3."""
        try:
            import boto3
            cf = boto3.client("cloudfront")

            origins = [{
                "Id": "lambda-origin",
                "DomainName": lambda_url.replace("https://", "").split("/")[0],
                "CustomOriginConfig": {
                    "HTTPPort": 443, "HTTPSPort": 443,
                    "OriginProtocolPolicy": "https-only",
                },
            }]
            if s3_bucket:
                origins.append({
                    "Id": "s3-origin",
                    "DomainName": f"{s3_bucket}.s3.amazonaws.com",
                    "S3OriginConfig": {"OriginAccessIdentity": ""},
                })

            dist = cf.create_distribution(DistributionConfig={
                "Origins": {"Quantity": len(origins), "Items": origins},
                "DefaultCacheBehavior": {
                    "TargetOriginId": "lambda-origin",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]},
                    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
                    "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",  # AllViewerExceptHostHeader
                },
                "Enabled": True,
                "Comment": "Horizon Orchestra Edge Distribution",
                "CallerReference": str(int(time.time())),
            })

            domain = dist["Distribution"]["DomainName"]
            return {"distribution_id": dist["Distribution"]["Id"], "domain": domain, "url": f"https://{domain}"}
        except Exception as exc:
            return {"error": str(exc)}

    async def invalidate_cache(self, paths: list[str] | None = None) -> dict[str, Any]:
        """Invalidate CloudFront cache."""
        if not self.config.cloudfront_distribution:
            # Local cache only
            if paths:
                for key in list(self._cache):
                    self._cache.pop(key, None)
            else:
                self._cache.clear()
            return {"invalidated": True, "scope": "local"}

        try:
            import boto3
            cf = boto3.client("cloudfront")
            cf.create_invalidation(
                DistributionId=self.config.cloudfront_distribution,
                InvalidationBatch={
                    "Paths": {"Quantity": len(paths or ["/*"]), "Items": paths or ["/*"]},
                    "CallerReference": str(int(time.time())),
                },
            )
            return {"invalidated": True, "scope": "cloudfront"}
        except Exception as exc:
            return {"error": str(exc)}
