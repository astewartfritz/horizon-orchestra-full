"""Build profile manager — GN arg presets for Chromium targets."""
from __future__ import annotations

from code_agent.build_orchestrator.models import BuildProfile, BuildType, Platform


BUILTIN_PROFILES: list[dict] = [
    # ── Windows ──
    dict(name="chromium-debug-win", label="Chromium Debug x64 (Win)",
         description="Debug build for Windows x64 with component build for fast iteration",
         platform=Platform.WINDOWS, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=2, component_build=True, use_jumbo=True,
         treat_warnings_as_errors=False,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      is_clang="true", clang_use_chrome_plugins="false")),
    dict(name="chromium-release-win", label="Chromium Release x64 (Win)",
         description="Official-quality release build for Windows x64",
         platform=Platform.WINDOWS, build_type=BuildType.RELEASE, target_cpu="x64",
         is_official=True, symbol_level=0, component_build=False,
         gn_args=dict(dcheck_always_on="false", is_official_build="true",
                      fieldtrial_testing_like_official_build="true")),
    dict(name="chromium-debug-win-x86", label="Chromium Debug x86 (Win)",
         description="Debug build for Windows x86 (32-bit)",
         platform=Platform.WINDOWS, build_type=BuildType.DEBUG, target_cpu="x86",
         symbol_level=2, component_build=True,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1")),
    # ── Linux ──
    dict(name="chromium-debug-linux", label="Chromium Debug x64 (Linux)",
         description="Debug build for Linux x64",
         platform=Platform.LINUX, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=2, component_build=True, use_jumbo=True,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      is_clang="true", clang_use_chrome_plugins="false",
                      use_sysroot="true")),
    dict(name="chromium-release-linux", label="Chromium Release x64 (Linux)",
         description="Official-quality release build for Linux x64",
         platform=Platform.LINUX, build_type=BuildType.RELEASE, target_cpu="x64",
         is_official=True, symbol_level=0,
         gn_args=dict(dcheck_always_on="false", fieldtrial_testing_like_official_build="true")),
    dict(name="chromium-debug-linux-arm64", label="Chromium Debug arm64 (Linux)",
         description="Debug build for Linux arm64 (e.g. Raspberry Pi)",
         platform=Platform.LINUX, build_type=BuildType.DEBUG, target_cpu="arm64",
         symbol_level=1, component_build=True,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="0")),
    # ── macOS ──
    dict(name="chromium-debug-mac", label="Chromium Debug x64 (macOS)",
         description="Debug build for macOS x64",
         platform=Platform.MAC, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=2, component_build=True,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      mac_deployment_target="10.15")),
    dict(name="chromium-release-mac", label="Chromium Release x64 (macOS)",
         description="Release build for macOS x64",
         platform=Platform.MAC, build_type=BuildType.RELEASE, target_cpu="x64",
         is_official=True, symbol_level=0,
         gn_args=dict(dcheck_always_on="false")),
    dict(name="chromium-debug-mac-arm", label="Chromium Debug arm64 (macOS)",
         description="Debug build for Apple Silicon Macs",
         platform=Platform.MAC, build_type=BuildType.DEBUG, target_cpu="arm64",
         symbol_level=2, component_build=True,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1")),
    # ── Android ──
    dict(name="chromium-debug-android", label="Chromium Debug x64 (Android)",
         description="Debug build for Android x64 emulator",
         platform=Platform.ANDROID, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=1, component_build=False,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="0",
                      is_java_debug="true", android_full_debug="true")),
    dict(name="chromium-release-android", label="Chromium Release arm64 (Android)",
         description="Release build for Android arm64 devices",
         platform=Platform.ANDROID, build_type=BuildType.RELEASE, target_cpu="arm64",
         is_official=True, symbol_level=0,
         gn_args=dict(dcheck_always_on="false", is_official_build="true",
                      fieldtrial_testing_like_official_build="true")),
    # ── iOS ──
    dict(name="chromium-debug-ios", label="Chromium Debug arm64 (iOS)",
         description="Debug build for iOS arm64 devices",
         platform=Platform.IOS, build_type=BuildType.DEBUG, target_cpu="arm64",
         symbol_level=2, component_build=False,
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      ios_enable_code_signing="false")),
    # ── Sanitizers ──
    dict(name="chromium-asan", label="Chromium ASAN x64 (Linux)",
         description="AddressSanitizer build for finding memory bugs",
         platform=Platform.LINUX, build_type=BuildType.ASAN, target_cpu="x64",
         symbol_level=1, component_build=False, is_official=False,
         gn_args=dict(is_asan="true", is_debug="false", dcheck_always_on="true",
                      treat_warnings_as_errors="false",
                      clang_use_chrome_plugins="false")),
    dict(name="chromium-cfi", label="Chromium CFI x64 (Linux)",
         description="Control Flow Integrity build for exploit mitigation",
         platform=Platform.LINUX, build_type=BuildType.CFI, target_cpu="x64",
         symbol_level=0, component_build=False,
         gn_args=dict(is_cfi="true", is_official_build="true", dcheck_always_on="false",
                      use_cfi_diag="false", is_debug="false")),
    # ── Specialized ──
    dict(name="chromium-headless", label="Chromium Headless Shell (Linux)",
         description="Minimal headless shell build for server-side rendering",
         platform=Platform.LINUX, build_type=BuildType.RELEASE, target_cpu="x64",
         symbol_level=0, component_build=False,
         gn_args=dict(is_debug="false", use_ozone="true", ozone_auto_platforms="false",
                      ozone_platform_headless="true", use_xkbcommon="true",
                      use_glib="true", use_pango="true")),
    dict(name="chromium-webview", label="Chromium WebView arm64 (Android)",
         description="Android WebView production build",
         platform=Platform.ANDROID, build_type=BuildType.RELEASE, target_cpu="arm64",
         symbol_level=0, is_official=True, component_build=False,
         gn_args=dict(is_official_build="true", symbol_level="0",
                      dcheck_always_on="false", fieldtrial_testing_like_official_build="true")),
    dict(name="chromium-size", label="Chromium Size Optimized (Linux)",
         description="Minimal binary size release build",
         platform=Platform.LINUX, build_type=BuildType.SIZE, target_cpu="x64",
         symbol_level=0, component_build=False,
         gn_args=dict(is_debug="false", is_official_build="true", symbol_level="0",
                      blink_symbol_level="0", optimize_for_size="true",
                      enable_nacl="false", enable_printing="false",
                      enable_plugins="false", enable_extensions="false")),
    # ── Horizon Frontier ──
    dict(name="horizon-frontier-dev", label="Horizon Frontier Dev (Win)",
         description=("Development profile for Horizon Frontier fork — "
                       "debug with component build for fast iteration"),
         platform=Platform.WINDOWS, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=2, component_build=True, use_jumbo=True,
         enable_rust=True,
         tags=["horizon-frontier"],
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      is_clang="true", clang_use_chrome_plugins="false",
                      enable_plugins="true", enable_extensions="true")),
    dict(name="horizon-frontier-release", label="Horizon Frontier Release (Win)",
         description="Release profile for Horizon Frontier fork — official build quality",
         platform=Platform.WINDOWS, build_type=BuildType.RELEASE, target_cpu="x64",
         is_official=True, symbol_level=0, enable_rust=True,
         tags=["horizon-frontier"],
         gn_args=dict(dcheck_always_on="false", is_official_build="true",
                      fieldtrial_testing_like_official_build="true",
                      enable_plugins="true", enable_extensions="true")),
    dict(name="horizon-frontier-linux", label="Horizon Frontier Dev (Linux)",
         description="Development profile for Horizon Frontier on Linux",
         platform=Platform.LINUX, build_type=BuildType.DEBUG, target_cpu="x64",
         symbol_level=2, component_build=True, enable_rust=True,
         tags=["horizon-frontier"],
         gn_args=dict(dcheck_always_on="true", blink_symbol_level="1",
                      is_clang="true", clang_use_chrome_plugins="false")),
]


class BuildProfileManager:
    """Manages build profiles (GN arg presets) for Chromium builds."""

    def __init__(self):
        self._profiles: dict[str, BuildProfile] = {}
        for data in BUILTIN_PROFILES:
            profile = BuildProfile(**data)
            self._profiles[profile.id] = profile

    def create(self, name: str, platform: Platform = Platform.WINDOWS,
               build_type: BuildType = BuildType.DEBUG, **kwargs) -> BuildProfile:
        profile = BuildProfile(name=name, platform=platform, build_type=build_type, **kwargs)
        self._profiles[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> BuildProfile | None:
        return self._profiles.get(profile_id)

    def get_by_name(self, name: str) -> BuildProfile | None:
        for p in self._profiles.values():
            if p.name == name:
                return p
        return None

    def update(self, profile_id: str, **kwargs) -> bool:
        profile = self._profiles.get(profile_id)
        if not profile:
            return False
        for key, value in kwargs.items():
            if hasattr(profile, key) and key not in ("id", "created_at"):
                setattr(profile, key, value)
        return True

    def delete(self, profile_id: str) -> bool:
        if profile_id not in self._profiles:
            return False
        del self._profiles[profile_id]
        return True

    def list(self, platform: Platform | None = None,
             build_type: BuildType | None = None,
             tag: str | None = None) -> list[BuildProfile]:
        results = list(self._profiles.values())
        if platform:
            results = [p for p in results if p.platform == platform]
        if build_type:
            results = [p for p in results if p.build_type == build_type]
        if tag:
            results = [p for p in results if tag in p.tags]
        return sorted(results, key=lambda p: p.name)

    def list_platforms(self) -> list[str]:
        return sorted(set(p.platform.value for p in self._profiles.values()))

    def list_types(self) -> list[str]:
        return sorted(set(p.build_type.value for p in self._profiles.values()))

    def count(self) -> int:
        return len(self._profiles)

    def get_gn_command(self, profile_id: str) -> str:
        profile = self._profiles.get(profile_id)
        if not profile:
            return ""
        return profile.gn_command

    def compare(self, id_a: str, id_b: str) -> dict:
        a = self._profiles.get(id_a)
        b = self._profiles.get(id_b)
        if not a or not b:
            return {}
        return {
            "a_only": {k: v for k, v in a.gn_args.items() if k not in b.gn_args or b.gn_args[k] != v},
            "b_only": {k: v for k, v in b.gn_args.items() if k not in a.gn_args or a.gn_args[k] != v},
            "common": {k: v for k, v in a.gn_args.items() if k in b.gn_args and b.gn_args[k] == v},
        }
