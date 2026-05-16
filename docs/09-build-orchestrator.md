# Build Orchestrator — Chromium Build Engine for Horizon Frontier

> **Module:** `src/code_agent/build_orchestrator/` — 73 tests

Enterprise-grade build orchestration for Chromium-based browsers. Manage GN profiles, run builds, track patches, and analyze build output — all from a single dashboard.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Web Dashboard (/build/app)                  │
│  Profiles │ Builds │ Patches │ AI Brain │ Metrics             │
├──────────────────────────────────────────────────────────────┤
│                    Python Build Orchestrator                   │
│  ┌──────────┬──────────────┬────────────┬──────────────────┐  │
│  │Profiles  │ BuildEngine  │ PatchMgr   │ BuildBrain       │  │
│  │(GN args) │ (execution)  │ (patches)  │ (AI analysis)    │  │
│  └────┬─────┴──────┬───────┴──────┬─────┴────────┬─────────┘  │
│       │            │              │              │            │
│  ┌────▼────────────▼──────────────▼──────────────▼─────────┐  │
│  │          REST API — /api/build/ (30+ endpoints)         │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Language Distribution

| Language | Files | Purpose |
|----------|-------|---------|
| Python | 8 | Models, engines, routes, tests, brain |
| HTML/CSS/JS | 2 | Brand page, interactive dashboard |
| Total | 10 | Full module |

---

## Data Models — `models.py`

| Model | Key Fields | Properties |
|-------|-----------|------------|
| `BuildProfile` | name, platform, build_type, gn_args, is_official, symbol_level, use_jumbo, tags | `gn_arg_string`, `gn_command`, `full_label` |
| `BuildTask` | profile_id, status, steps, result, branch, commit_sha | `is_running`, `is_terminal`, `current_step`, `progress_pct` |
| `BuildStep` | name, command, status, output, exit_code, duration_ms | — |
| `BuildResult` | binary_paths, total_size_bytes, compile_time_ms, link_time_ms, errors, warnings | `size_mb` |
| `Patch` | name, target_dir, status, content, author, version, conflict_details | `is_applied` |
| `BuildMetrics` | total_tasks, success_rate, avg_build_time_ms, total_warnings | `success_rate` |

Enums: `BuildStatus`, `BuildType` (debug/release/asan/cfi/tsan/msan/size/coverage), `Platform` (win/linux/mac/android/ios/chromeos/fuchsia), `PatchStatus`

---

## Build Profiles — `profiles.py`

**21 built-in profiles** covering every major Chromium target:

| Profile | Platform | Type | CPU | Use Case |
|---------|----------|------|-----|----------|
| `chromium-debug-win` | Windows | Debug | x64 | Fast iteration, component build |
| `chromium-release-win` | Windows | Release | x64 | Official-quality release |
| `chromium-debug-win-x86` | Windows | Debug | x86 | 32-bit debugging |
| `chromium-debug-linux` | Linux | Debug | x64 | Linux development |
| `chromium-release-linux` | Linux | Release | x64 | Linux release builds |
| `chromium-debug-linux-arm64` | Linux | Debug | arm64 | ARM SBCs |
| `chromium-debug-mac` | macOS | Debug | x64 | macOS development |
| `chromium-release-mac` | macOS | Release | x64 | macOS release |
| `chromium-debug-mac-arm` | macOS | Debug | arm64 | Apple Silicon |
| `chromium-debug-android` | Android | Debug | x64 | Emulator builds |
| `chromium-release-android` | Android | Release | arm64 | Device release |
| `chromium-debug-ios` | iOS | Debug | arm64 | iOS development |
| `chromium-asan` | Linux | ASAN | x64 | Memory bug detection |
| `chromium-cfi` | Linux | CFI | x64 | Exploit mitigation |
| `chromium-headless` | Linux | Release | x64 | Server-side rendering |
| `chromium-webview` | Android | Release | arm64 | Android WebView |
| `chromium-size` | Linux | Size | x64 | Minimal binary size |
| `horizon-frontier-dev` | Windows | Debug | x64 | **Horizon Frontier dev** |
| `horizon-frontier-release` | Windows | Release | x64 | **Horizon Frontier release** |
| `horizon-frontier-linux` | Linux | Debug | x64 | **Horizon Frontier Linux** |

### Custom GN Args

Each profile generates a complete `gn gen` command. Example:

```
gn gen out/horizon-frontier-dev --args="
  blink_symbol_level=1
  clang_use_chrome_plugins=false
  dcheck_always_on=true
  enable_extensions=true
  enable_plugins=true
  enable_rust=true
  ffmpeg_branding=\"Chrome\"
  is_clang=true
  is_component_build=true
  is_debug=true
  proprietary_codecs=true
  symbol_level=2
  target_cpu=\"x64\"
  treat_warnings_as_errors=false
  use_jumbo_build=true
"
```

### Profile Manager API

| Method | Description |
|--------|-------------|
| `create(name, platform, build_type)` | New profile with auto-ID |
| `get(profile_id)` | Get by ID |
| `get_by_name(name)` | Find by name |
| `update(profile_id, **kwargs)` | Update fields |
| `delete(profile_id)` | Remove profile |
| `list(platform, build_type, tag)` | Filtered list |
| `get_gn_command(profile_id)` | Full `gn gen` command |
| `compare(id_a, id_b)` | Diff two profiles' GN args |

---

## Build Engine — `engine.py`

Manages the Chromium build lifecycle.

### Build Pipeline Steps

| Step | Command | Description |
|------|---------|-------------|
| `depot_tools sync` | `gclient sync --with_branch_heads` | Fetch sources and dependencies |
| `gn gen` | `gn gen out/{profile}` | Generate ninja files |
| `gn args check` | `gn args out/{profile} --list` | Verify GN configuration |
| `ninja build` | `ninja -C out/{profile} -j$(nproc) chrome` | Compile and link |
| `build verify` | Verify output binary exists | Validate build artifacts |

### Key Methods

| Method | Description |
|--------|-------------|
| `create_task(profile)` | Creates a pending build task with step definitions |
| `get_task(task_id)` | Get task by ID |
| `list_tasks(status, profile, platform)` | Filtered task list (default sorted newest first) |
| `cancel_task(task_id)` | Cancel a running or pending build |
| `delete_task(task_id)` | Remove from history |
| `simulate_build(task_id)` | Simulates build execution (for testing/demo) |
| `parse_build_output(output)` | Parse ninja output for errors, warnings, progress |
| `estimate_build_time(profile)` | Time estimate based on platform and config |
| `suggest_parallelism(platform)` | Recommended `-j` values |
| `get_metrics()` | Aggregated build statistics |

### Build Output Parsing

```python
output = """
[185000/310000] Linking chrome.exe
FAILED: obj/base/base/location.o
warning: unused parameter 'callback'
"""
result = engine.parse_build_output(output)
# {
#   "errors": ["obj/base/base/location.o"],
#   "warnings": ["unused parameter 'callback'"],
#   "compile_errors": [...],
#   "link_errors": [],
#   "progress": {"current": 185000, "total": 310000}
# }
```

### Build Time Estimation

Estimates account for:
- Platform base time (Android: 75min, iOS: 83min, macOS: 50min, Windows: 40min, Linux: 35min)
- Component build: 60% reduction (incremental)
- Jumbo build: 30% reduction
- Official build: 80% increase (LTO, PGO)
- High symbol level: 30% increase

---

## Patch Manager — `patches.py`

Manage patches on the Chromium source tree.

### Predefined Horizon Frontier Patches

| Patch | Target Dir | Status | Description |
|-------|-----------|--------|-------------|
| `horizon-custom-theme` | `chrome/browser/themes` | Applied | Custom brand colors and UI |
| `disable-autofill-server` | `components/autofill` | Applied | Disable autofill server |
| `custom-new-tab-page` | `chrome/browser/ui/webui/ntp` | Applied | Horizon dashboard NTP |
| `disable-crash-reporting` | `components/metrics` | Applied | No crash uploads |
| `enable-vertical-tabs` | `chrome/browser/ui` | Unapplied | Vertical tabs by default |
| `speed-improvements-v8` | `v8` | Partial | V8 JIT tuning |
| `manifest-v3-compliance` | `extensions` | Conflict | MV3 compliance |
| `custom-protocol-handler` | `chrome/browser/protocol_handler` | Unapplied | `orbit://` protocol |

### Key Methods

| Method | Description |
|--------|-------------|
| `create(name, target_dir, ...)` | Register a new patch |
| `apply(patch_id)` | Mark as applied |
| `unapply(patch_id)` | Mark as unapplied |
| `get(patch_id)` | Get patch details |
| `list(status, tag, target_dir)` | Filtered list |
| `update(patch_id, **kwargs)` | Update metadata (increments version) |
| `delete(patch_id)` | Remove patch |
| `get_metrics()` | Count by status and tags |
| `detect_conflicts(patch_ids)` | Find patches modifying same directory |

---

## Build Brain — `brain.py`

AI-native build analysis.

### Known Error Fix Patterns

| Pattern | Suggestion |
|---------|-----------|
| `undefined symbol` | Add missing target to `deps` in BUILD.gn |
| `Assertion failed` | Check BUILD.gn condition or patch application |
| `file not found` | Run `gclient sync`, check BUILD.gn sources |
| `android_sdk_root` | Set `android_sdk_root` in GN args |
| `ld.lld` | Check .o files, libraries, dependencies |
| `ASAN` | Memory error — use-after-free, buffer overflow, etc. |

### Key Methods

| Method | Description |
|--------|-------------|
| `analyze_errors(task_id)` | Match errors against known patterns with fixes |
| `suggest_optimizations(profile_id)` | Recommend GN arg changes for faster builds |
| `analyze_build_config(profile_id)` | Full analysis: time estimate + optimizations + parallelism |
| `get_summary()` | High-level stats: builds, patches, profiles |
| `llm_analyze(prompt, context)` | LLM-powered copilot with offline fallback |

### Optimization Suggestions

| Setting | Current → Recommended | Savings |
|---------|----------------------|---------|
| `symbol_level` | 2 → 1 | ~20% link time |
| `is_component_build` | false → true (debug only) | ~60% incremental time |
| `use_jumbo_build` | false → true | ~30% full build |
| `treat_warnings_as_errors` | true → false | Fewer breaks |

---

## REST API — `/api/build/`

**30+ endpoints** across 7 resource groups:

| Group | Endpoints | Description |
|-------|-----------|-------------|
| Health | `GET /health` | Service status |
| Profiles | `GET/POST /profiles`, `GET/PUT/DELETE /profiles/{id}`, `GET /profiles/{id}/gn-command`, `GET /profiles/{id}/estimate`, `GET /profiles/{id}/optimize`, `GET /profiles/{id}/analyze`, `POST /profiles/compare` | CRUD + analysis |
| Tasks | `GET/POST /tasks`, `GET/DELETE /tasks/{id}`, `POST /tasks/{id}/build`, `POST /tasks/{id}/cancel`, `GET /tasks/{id}/analyze`, `GET /tasks/{id}/output` | Build lifecycle |
| Patches | `GET/POST /patches`, `GET/PUT/DELETE /patches/{id}`, `POST /patches/{id}/apply`, `POST /patches/{id}/unapply`, `GET /patches/conflicts` | Patch management |
| Brain | `GET /brain/summary`, `POST /brain/query`, `GET /brain/parallelism`, `GET /brain/fixes` | AI analysis |
| Metrics | `GET /metrics` | Full build stats |
| Enums | `GET /platforms`, `GET /types` | Available platforms and build types |

---

## Dashboard — `/build/app`

5-tab interactive dashboard:

| Tab | Content |
|-----|---------|
| **Profiles** | KPI cards (total/platforms/types), profiles table with tags, profile detail with GN command/args/estimates/optimizations |
| **Builds** | KPI cards (total/success/failed/running), builds table with progress bars, "New Build" form with profile picker, build detail with steps/results/errors |
| **Patches** | KPI cards (total/applied/conflicts), patches table with apply/unapply, patch detail with metadata/conflict info |
| **AI Brain** | Build copilot chat, known error fix patterns list, parallelism suggestions by platform |
| **Metrics** | KPI cards (builds/time/size/patches/errors), full JSON metrics dump |

---

## Test Coverage (73 tests)

| Class | Tests | Coverage |
|-------|-------|----------|
| BuildProfile | 5 | Auto-ID, full_label, GN string/command, official label |
| BuildStep | 1 | Auto-timestamp |
| BuildResult | 2 | Size MB calculation |
| BuildTask | 8 | Auto-ID, is_running, is_terminal, progress, current_step |
| Patch | 3 | Auto-ID, is_applied |
| BuildMetrics | 2 | Success rate |
| BuildProfileManager | 14 | CRUD, filtering, platforms/types, GN command, compare |
| BuildEngine | 17 | CRUD, listing, cancel, parse output, estimate, simulate, metrics |
| PatchManager | 12 | CRUD, apply/unapply, filters, metrics, conflict detection |
| **Total** | **73** | |
