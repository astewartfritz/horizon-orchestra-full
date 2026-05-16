"""Patch manager — apply, track, and manage patches on Chromium source."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from code_agent.build_orchestrator.models import Patch, PatchStatus


PREDEFINED_PATCHES: list[dict] = [
    dict(
        name="horizon-custom-theme",
        description="Custom brand theme colors and UI tweaks for Horizon Frontier",
        author="Horizon Team",
        target_dir="chrome/browser/themes",
        status=PatchStatus.APPLIED,
        applied_at=datetime.now(timezone.utc).isoformat(),
        tags=["horizon-frontier", "ui"],
        content="""--- a/chrome/browser/themes/theme_service.cc
+++ b/chrome/browser/themes/theme_service.cc
@@ -120,6 +120,10 @@ void ThemeService::SetDefaultTheme() {
 void ThemeService::SetSystemTheme() {
+  // Horizon Frontier: Custom brand colors
+  if (GetID() == "horizon-frontier") {
+    UseTheme(HorizonTheme::Create());
+    return;
+  }
 #if BUILDFLAG(IS_LINUX)
   if (ShouldUseSystemTheme()) {
     UseTheme(SystemTheme::Create());""",
    ),
    dict(
        name="disable-autofill-server",
        description="Disable autofill server communication for privacy",
        author="Horizon Team",
        target_dir="components/autofill",
        status=PatchStatus.APPLIED,
        applied_at=datetime.now(timezone.utc).isoformat(),
        tags=["horizon-frontier", "privacy"],
        content="""--- a/components/autofill/core/common/autofill_features.cc
+++ b/components/autofill/core/common/autofill_features.cc
@@ -45,6 +45,7 @@ BASE_FEATURE(kAutofillServerCommunication,
              "AutofillServerCommunication",
+             base::FEATURE_DISABLED_BY_DEFAULT);
-             base::FEATURE_ENABLED_BY_DEFAULT);
 #endif""",
    ),
    dict(
        name="custom-new-tab-page",
        description="Replace new tab page with custom Horizon Frontier dashboard",
        author="Horizon Team",
        target_dir="chrome/browser/ui/webui/ntp",
        status=PatchStatus.APPLIED,
        applied_at=datetime.now(timezone.utc).isoformat(),
        tags=["horizon-frontier", "ui"],
        content="",
    ),
    dict(
        name="disable-crash-reporting",
        description="Disable crash reporting and metrics upload",
        author="Horizon Team",
        target_dir="components/metrics",
        status=PatchStatus.APPLIED,
        applied_at=datetime.now(timezone.utc).isoformat(),
        tags=["horizon-frontier", "privacy"],
        content="",
    ),
    dict(
        name="enable-vertical-tabs",
        description="Enable vertical tabs by default",
        author="Horizon Team",
        target_dir="chrome/browser/ui",
        status=PatchStatus.UNAPPLIED,
        tags=["horizon-frontier", "ui"],
        content="",
    ),
    dict(
        name="speed-improvements-v8",
        description="V8 JIT tuning for faster JavaScript execution",
        author="Horizon Team",
        target_dir="v8",
        status=PatchStatus.PARTIAL,
        tags=["horizon-frontier", "performance"],
        content="",
    ),
    dict(
        name="manifest-v3-compliance",
        description="Ensure all extensions comply with Manifest V3 requirements",
        author="Horizon Team",
        target_dir="extensions",
        status=PatchStatus.CONFLICT,
        conflict_details="Conflict in extensions/common/extension_features.cc:45 — "
                          "both patches modify kChromeExtensionsManifestV3 feature flag",
        tags=["horizon-frontier", "extensions"],
        content="",
    ),
    dict(
        name="custom-protocol-handler",
        description="Handle custom orbit:// protocol for Horizon apps",
        author="Horizon Team",
        target_dir="chrome/browser/protocol_handler",
        status=PatchStatus.UNAPPLIED,
        tags=["horizon-frontier", "integration"],
        content="",
    ),
]


class PatchManager:
    """Manages patches on the Chromium source tree."""

    def __init__(self):
        self._patches: dict[str, Patch] = {}
        for data in PREDEFINED_PATCHES:
            patch = Patch(**data)
            self._patches[patch.id] = patch

    def create(self, name: str, target_dir: str, description: str = "",
               author: str = "", content: str = "", source_path: str = "",
               tags: list[str] | None = None) -> Patch:
        patch = Patch(
            name=name,
            description=description,
            author=author or "Unknown",
            target_dir=target_dir,
            content=content,
            source_path=source_path,
            tags=tags or [],
        )
        self._patches[patch.id] = patch
        return patch

    def get(self, patch_id: str) -> Patch | None:
        return self._patches.get(patch_id)

    def list(self, status: PatchStatus | None = None,
             tag: str | None = None,
             target_dir: str | None = None) -> list[Patch]:
        results = list(self._patches.values())
        if status:
            results = [p for p in results if p.status == status]
        if tag:
            results = [p for p in results if tag in p.tags]
        if target_dir:
            results = [p for p in results if target_dir in p.target_dir]
        return sorted(results, key=lambda p: p.created_at, reverse=True)

    def apply(self, patch_id: str) -> bool:
        patch = self._patches.get(patch_id)
        if not patch or patch.is_applied:
            return False
        if patch.status == PatchStatus.CONFLICT:
            return False
        patch.status = PatchStatus.APPLIED
        patch.applied_at = datetime.now(timezone.utc).isoformat()
        return True

    def unapply(self, patch_id: str) -> bool:
        patch = self._patches.get(patch_id)
        if not patch or not patch.is_applied:
            return False
        patch.status = PatchStatus.UNAPPLIED
        patch.applied_at = ""
        return True

    def delete(self, patch_id: str) -> bool:
        if patch_id not in self._patches:
            return False
        del self._patches[patch_id]
        return True

    def update(self, patch_id: str, **kwargs) -> bool:
        patch = self._patches.get(patch_id)
        if not patch:
            return False
        for key, value in kwargs.items():
            if hasattr(patch, key) and key not in ("id", "created_at", "status"):
                setattr(patch, key, value)
        patch.version += 1
        return True

    def get_metrics(self) -> dict:
        patches = list(self._patches.values())
        return {
            "total": len(patches),
            "applied": sum(1 for p in patches if p.status == PatchStatus.APPLIED),
            "unapplied": sum(1 for p in patches if p.status == PatchStatus.UNAPPLIED),
            "conflict": sum(1 for p in patches if p.status == PatchStatus.CONFLICT),
            "partial": sum(1 for p in patches if p.status == PatchStatus.PARTIAL),
            "by_tag": {t: sum(1 for p in patches if t in p.tags) for t in
                       sorted(set(t for p in patches for t in p.tags))},
        }

    def detect_conflicts(self, target_patches: list[str]) -> list[dict]:
        conflicts = []
        dir_map: dict[str, list[Patch]] = {}
        for pid in target_patches:
            patch = self._patches.get(pid)
            if patch:
                dir_map.setdefault(patch.target_dir, []).append(patch)
        for d, patches in dir_map.items():
            if len(patches) > 1:
                for i, a in enumerate(patches):
                    for b in patches[i + 1:]:
                        conflicts.append({
                            "directory": d,
                            "a": {"id": a.id, "name": a.name},
                            "b": {"id": b.id, "name": b.name},
                            "severity": random.choice(["low", "medium", "high"]),
                        })
        return conflicts
