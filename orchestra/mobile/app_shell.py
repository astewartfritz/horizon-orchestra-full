"""
orchestra/mobile/app_shell.py
-------------------------------
App shell HTML generator for Horizon Orchestra PWA.

Generates a complete single-page app shell with:
- Comprehensive mobile meta tags (viewport, theme-color, Apple web app)
- Apple touch icon and splash screen links for all iPhone/iPad sizes
- Web App Manifest link
- Service worker registration with update handling
- Offline detection banner
- Network status indicator
- App update notification ("New version available — tap to update")
- Content Security Policy header helper
- FastAPI route that serves the full shell page
"""
from __future__ import annotations

__all__ = [
    "AppShellGenerator",
    "AppShellConfig",
    "generate_app_shell",
    "get_csp_header",
    "register_routes",
]

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("orchestra.mobile.app_shell")

# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

BRAND_TEAL = "#01696F"
BRAND_DARK = "#0a0a0a"
APP_NAME = "Horizon Orchestra"
ASSISTANT_NAME = "MILES"

# ---------------------------------------------------------------------------
# iOS splash screen sizes
# Device:                  portrait WxH  device-width  device-height  ratio
# ---------------------------------------------------------------------------
_IOS_SPLASH_SIZES: list[dict] = [
    # iPhone SE / iPod touch
    {"w": 640,  "h": 1136, "dw": 320,  "dh": 568,  "ratio": 2},
    # iPhone 8, 7, 6s, 6
    {"w": 750,  "h": 1334, "dw": 375,  "dh": 667,  "ratio": 2},
    # iPhone 8 Plus, 7 Plus, 6s Plus, 6 Plus
    {"w": 1242, "h": 2208, "dw": 414,  "dh": 736,  "ratio": 3},
    # iPhone X, XS, 11 Pro, 12 mini, 13 mini
    {"w": 1125, "h": 2436, "dw": 375,  "dh": 812,  "ratio": 3},
    # iPhone XS Max, XR, 11, 11 Pro Max
    {"w": 1242, "h": 2688, "dw": 414,  "dh": 896,  "ratio": 3},
    # iPhone 12, 12 Pro, 13, 13 Pro, 14
    {"w": 1170, "h": 2532, "dw": 390,  "dh": 844,  "ratio": 3},
    # iPhone 12 Pro Max, 13 Pro Max, 14 Plus
    {"w": 1284, "h": 2778, "dw": 428,  "dh": 926,  "ratio": 3},
    # iPhone 14 Pro
    {"w": 1179, "h": 2556, "dw": 393,  "dh": 852,  "ratio": 3},
    # iPhone 14 Pro Max, 15 Pro Max
    {"w": 1290, "h": 2796, "dw": 430,  "dh": 932,  "ratio": 3},
    # iPad (9th/10th gen)
    {"w": 1536, "h": 2048, "dw": 768,  "dh": 1024, "ratio": 2},
    # iPad Pro 11"
    {"w": 1668, "h": 2388, "dw": 834,  "dh": 1194, "ratio": 2},
    # iPad Pro 12.9"
    {"w": 2048, "h": 2732, "dw": 1024, "dh": 1366, "ratio": 2},
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AppShellConfig:
    """Configuration for the app shell generator."""

    app_name: str = APP_NAME
    assistant_name: str = ASSISTANT_NAME
    theme_color: str = BRAND_TEAL
    background_color: str = BRAND_DARK
    icon_base: str = "/static/icons"
    splash_base: str = "/static/splash"
    manifest_url: str = "/manifest.json"
    sw_url: str = "/sw.js"
    offline_queue_js: str = "/api/mobile/queue/js"
    touch_ui_css: str = "/static/touch-ui.css"
    touch_ui_js: str = "/static/touch-ui.js"
    api_base: str = "/api"
    ws_path: str = "/ws/chat"
    enable_csp: bool = True
    csp_report_uri: str = ""
    extra_head_html: str = ""
    extra_body_html: str = ""
    # Script / style hashes for CSP inline content
    csp_script_nonce: str = ""


# ---------------------------------------------------------------------------
# Content Security Policy helper
# ---------------------------------------------------------------------------


def get_csp_header(config: AppShellConfig) -> str:
    """Build and return a Content-Security-Policy header value.

    Constructs a strict CSP that:
    - Allows same-origin scripts and styles + any nonce provided
    - Allows wss/ws for WebSocket connections
    - Allows push endpoints (unpredictable origin) via connect-src wildcard
    - Blocks all object/frame/embed elements
    """
    cfg = config
    nonce = f"'nonce-{cfg.csp_script_nonce}'" if cfg.csp_script_nonce else ""

    directives = [
        "default-src 'self'",
        f"script-src 'self' {nonce} 'strict-dynamic'".strip(),
        f"style-src 'self' {nonce} 'unsafe-inline'".strip(),
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self' wss: ws: https:",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]

    if cfg.csp_report_uri:
        directives.append(f"report-uri {cfg.csp_report_uri}")

    return "; ".join(directives)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class AppShellGenerator:
    """Generates the full app shell HTML document for Horizon Orchestra.

    Usage::

        gen = AppShellGenerator()
        html = gen.build()
    """

    def __init__(self, config: AppShellConfig | None = None) -> None:
        self.config = config or AppShellConfig()

    def build(self) -> str:
        """Build and return the complete app shell HTML string."""
        cfg = self.config
        meta_tags = self._meta_tags()
        icon_links = self._icon_links()
        splash_links = self._splash_links()
        sw_script = self._sw_registration_script()
        network_script = self._network_status_script()
        update_script = self._update_notification_script()
        extra_head = cfg.extra_head_html
        extra_body = cfg.extra_body_html

        return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
  <meta charset="UTF-8">

  <!-- ================================================================
       Horizon Orchestra — App Shell
       Generated by orchestra.mobile.app_shell
       ================================================================ -->

  <!-- Viewport & mobile optimization -->
{meta_tags}

  <!-- Web App Manifest -->
  <link rel="manifest" href="{cfg.manifest_url}">

  <!-- Icons -->
{icon_links}

  <!-- iOS Splash Screens -->
{splash_links}

  <!-- Stylesheets -->
  <link rel="preload" href="{cfg.touch_ui_css}" as="style">
  <link rel="stylesheet" href="{cfg.touch_ui_css}">

  <!-- Preconnect to API -->
  <link rel="preconnect" href="{cfg.api_base}">

  <!-- Title -->
  <title>{cfg.app_name}</title>

{extra_head}
</head>
<body class="app-shell">

  <!-- ============================================================
       Network status indicators
       ============================================================ -->
  <div id="networkBanner" class="network-banner" role="status" aria-live="polite" hidden>
    <span id="networkBannerText"></span>
  </div>

  <!-- ============================================================
       App update notification
       ============================================================ -->
  <div id="updateNotification" class="update-notification" role="alertdialog"
       aria-label="App update available" aria-live="assertive" hidden>
    <span class="update-notification__text">New version available</span>
    <button class="update-notification__btn" id="updateReloadBtn" type="button">
      Update now
    </button>
    <button class="update-notification__close" id="updateDismissBtn"
            type="button" aria-label="Dismiss update notification">✕</button>
  </div>

  <!-- ============================================================
       App root — touch UI injected here by touch_ui.py
       ============================================================ -->
  <div id="app-root" class="app-root" aria-busy="true">
    <!-- Inline loading state shown before JS hydrates -->
    <div class="app-loader" id="appLoader" aria-label="Loading {cfg.app_name}">
      <div class="app-loader__logo" aria-hidden="true">
        <svg viewBox="0 0 48 48" width="56" height="56">
          <circle cx="24" cy="24" r="22"
                  fill="none" stroke="{cfg.theme_color}" stroke-width="3"
                  stroke-dasharray="100" stroke-dashoffset="30">
            <animateTransform attributeName="transform" type="rotate"
                              from="0 24 24" to="360 24 24" dur="1.2s"
                              repeatCount="indefinite"/>
          </circle>
          <text x="24" y="29" text-anchor="middle"
                font-family="-apple-system,sans-serif" font-size="11"
                font-weight="700" fill="{cfg.theme_color}">
            {cfg.assistant_name}
          </text>
        </svg>
      </div>
      <p class="app-loader__text">Loading {cfg.app_name}…</p>
    </div>
  </div>

{extra_body}

  <!-- ============================================================
       App shell styles (inline critical CSS)
       ============================================================ -->
  <style>
    html, body {{
      margin: 0; padding: 0;
      background: {cfg.background_color};
      color: #f0f0f0;
      height: 100%;
      overflow: hidden;
    }}
    .app-root {{
      position: fixed;
      inset: 0;
      display: flex;
      flex-direction: column;
    }}
    .app-loader {{
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 20px;
    }}
    .app-loader__text {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
      color: #888;
    }}
    .network-banner {{
      position: fixed;
      top: env(safe-area-inset-top, 0);
      left: 0; right: 0;
      z-index: 9999;
      padding: 8px 16px;
      font-size: 13px;
      text-align: center;
      font-family: -apple-system, sans-serif;
      transition: transform 0.3s ease;
    }}
    .network-banner--offline  {{ background: #3a2a00; color: #ffd580; }}
    .network-banner--online   {{ background: #1a3a1a; color: #80ff80; }}
    .update-notification {{
      position: fixed;
      bottom: calc(72px + env(safe-area-inset-bottom, 0));
      left: 12px; right: 12px;
      z-index: 9998;
      background: {cfg.theme_color};
      color: #fff;
      border-radius: 14px;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
      font-family: -apple-system, sans-serif;
      font-size: 14px;
    }}
    .update-notification__text {{ flex: 1; }}
    .update-notification__btn {{
      background: rgba(255,255,255,0.2);
      border: none;
      border-radius: 8px;
      color: #fff;
      padding: 6px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      min-height: 36px;
    }}
    .update-notification__close {{
      background: none;
      border: none;
      color: rgba(255,255,255,0.7);
      font-size: 16px;
      cursor: pointer;
      padding: 4px;
      min-width: 32px;
      min-height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
  </style>

  <!-- ============================================================
       Scripts
       ============================================================ -->

  <!-- Offline queue module -->
  <script type="module" src="{cfg.offline_queue_js}"></script>

  <!-- Touch UI JavaScript -->
  <script type="module" src="{cfg.touch_ui_js}"></script>

  <!-- Service worker registration + update detection -->
  <script>
{sw_script}
  </script>

  <!-- Network status script -->
  <script>
{network_script}
  </script>

  <!-- App update notification script -->
  <script>
{update_script}
  </script>

  <!-- Remove loader once app hydrates -->
  <script>
    document.addEventListener('DOMContentLoaded', () => {{
      requestAnimationFrame(() => {{
        const loader = document.getElementById('appLoader');
        const root   = document.getElementById('app-root');
        if (loader) loader.style.display = 'none';
        if (root)   root.setAttribute('aria-busy', 'false');
      }});
    }});
  </script>

</body>
</html>"""

    # ------------------------------------------------------------------
    # Meta tags
    # ------------------------------------------------------------------

    def _meta_tags(self) -> str:
        cfg = self.config
        lines = [
            '  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=5">',
            f'  <meta name="theme-color" content="{cfg.theme_color}" media="(prefers-color-scheme: dark)">',
            '  <meta name="theme-color" content="#01696F" media="(prefers-color-scheme: light)">',
            f'  <meta name="description" content="Your AI orchestration layer powered by {cfg.assistant_name}">',
            # Apple-specific
            '  <meta name="apple-mobile-web-app-capable" content="yes">',
            '  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
            f'  <meta name="apple-mobile-web-app-title" content="{cfg.app_name}">',
            # Windows / MS
            f'  <meta name="msapplication-TileColor" content="{cfg.theme_color}">',
            f'  <meta name="msapplication-TileImage" content="{cfg.icon_base}/icon-144.png">',
            # OG
            '  <meta property="og:type" content="website">',
            f'  <meta property="og:title" content="{cfg.app_name}">',
            f'  <meta property="og:description" content="Your AI orchestration layer powered by {cfg.assistant_name}">',
            f'  <meta property="og:image" content="{cfg.icon_base}/icon-512.png">',
            # Twitter
            '  <meta name="twitter:card" content="summary">',
            f'  <meta name="twitter:title" content="{cfg.app_name}">',
            # Mobile web
            '  <meta name="mobile-web-app-capable" content="yes">',
            '  <meta name="format-detection" content="telephone=no">',
            '  <meta name="HandheldFriendly" content="True">',
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Icon links
    # ------------------------------------------------------------------

    def _icon_links(self) -> str:
        base = self.config.icon_base
        lines = [
            f'  <link rel="icon" href="{base}/icon-32.png" sizes="32x32" type="image/png">',
            f'  <link rel="icon" href="{base}/icon-96.png" sizes="96x96" type="image/png">',
            f'  <link rel="icon" href="{base}/icon.svg" type="image/svg+xml">',
            f'  <link rel="apple-touch-icon" href="{base}/icon-180.png">',
            f'  <link rel="apple-touch-icon" sizes="152x152" href="{base}/icon-152.png">',
            f'  <link rel="apple-touch-icon" sizes="167x167" href="{base}/icon-167.png">',
            f'  <link rel="apple-touch-icon" sizes="180x180" href="{base}/icon-180.png">',
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # iOS splash screen links
    # ------------------------------------------------------------------

    def _splash_links(self) -> str:
        base = self.config.splash_base
        lines: list[str] = []
        for s in _IOS_SPLASH_SIZES:
            media = (
                f"(device-width: {s['dw']}px) and (device-height: {s['dh']}px)"
                f" and (-webkit-device-pixel-ratio: {s['ratio']})"
                f" and (orientation: portrait)"
            )
            href = f"{base}/splash-{s['w']}x{s['h']}.png"
            lines.append(
                f'  <link rel="apple-touch-startup-image" href="{href}" media="{media}">'
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Service worker registration
    # ------------------------------------------------------------------

    def _sw_registration_script(self) -> str:
        cfg = self.config
        return f"""\
    (async function registerServiceWorker() {{
      if (!('serviceWorker' in navigator)) {{
        console.log('[App] Service workers not supported');
        return;
      }}

      try {{
        const registration = await navigator.serviceWorker.register(
          '{cfg.sw_url}',
          {{ scope: '/' }}
        );
        console.log('[App] Service worker registered:', registration.scope);

        // Detect updates
        registration.addEventListener('updatefound', () => {{
          const newWorker = registration.installing;
          if (!newWorker) return;

          newWorker.addEventListener('statechange', () => {{
            if (
              newWorker.state === 'installed' &&
              navigator.serviceWorker.controller
            ) {{
              // New version available — show update notification
              window.dispatchEvent(new CustomEvent('swUpdateReady', {{
                detail: {{ registration }}
              }}));
            }}
          }});
        }});

        // Register periodic sync if supported
        if ('periodicSync' in registration) {{
          try {{
            await registration.periodicSync.register('horizon-periodic-refresh', {{
              minInterval: 6 * 60 * 60 * 1000, // 6 hours
            }});
            console.log('[App] Periodic sync registered');
          }} catch (e) {{
            console.log('[App] Periodic sync not permitted:', e.message);
          }}
        }}

      }} catch (err) {{
        console.error('[App] Service worker registration failed:', err);
      }}
    }})();"""

    # ------------------------------------------------------------------
    # Network status script
    # ------------------------------------------------------------------

    def _network_status_script(self) -> str:
        return """\
    (function initNetworkStatus() {
      const banner = document.getElementById('networkBanner');
      const bannerText = document.getElementById('networkBannerText');

      function show(message, type) {
        if (!banner || !bannerText) return;
        bannerText.textContent = message;
        banner.className = `network-banner network-banner--${type}`;
        banner.hidden = false;
        if (type === 'online') {
          setTimeout(() => { banner.hidden = true; }, 3000);
        }
      }

      window.addEventListener('offline', () => {
        show('You\\'re offline — messages will be queued', 'offline');
      });

      window.addEventListener('online', () => {
        show('Back online — syncing queued messages…', 'online');
      });

      if (!navigator.onLine) {
        show('You\\'re offline — messages will be queued', 'offline');
      }
    })();"""

    # ------------------------------------------------------------------
    # App update notification script
    # ------------------------------------------------------------------

    def _update_notification_script(self) -> str:
        return """\
    (function initUpdateNotification() {
      const notification = document.getElementById('updateNotification');
      const reloadBtn    = document.getElementById('updateReloadBtn');
      const dismissBtn   = document.getElementById('updateDismissBtn');

      window.addEventListener('swUpdateReady', (e) => {
        if (notification) notification.hidden = false;

        reloadBtn?.addEventListener('click', () => {
          const registration = e.detail?.registration;
          if (registration?.waiting) {
            registration.waiting.postMessage({ type: 'SKIP_WAITING' });
          }
          window.location.reload();
        });
      });

      dismissBtn?.addEventListener('click', () => {
        if (notification) notification.hidden = true;
      });

      // Handle controller change (new SW took over)
      navigator.serviceWorker?.addEventListener('controllerchange', () => {
        window.location.reload();
      });
    })();"""


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def generate_app_shell(config: AppShellConfig | None = None) -> str:
    """Generate and return the full app shell HTML string."""
    return AppShellGenerator(config).build()


# ---------------------------------------------------------------------------
# FastAPI route registration
# ---------------------------------------------------------------------------


def register_routes(app: object) -> None:
    """Register app shell routes on a FastAPI application instance.

    Registers:
        GET /           — serves the app shell HTML (SPA entry point)
        GET /offline    — serves an offline fallback page
    """
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, Response
    except ImportError:  # pragma: no cover — optional web dependency
        logger.warning("FastAPI not installed; app shell routes not registered")
        return

    generator = AppShellGenerator()

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def serve_app_shell(request: Request) -> HTMLResponse:
        """Serve the Progressive Web App shell."""
        config = AppShellConfig()
        # Adjust absolute URLs based on request host
        base = str(request.base_url).rstrip("/")
        config.api_base = f"{base}/api"

        html = AppShellGenerator(config).build()

        headers: dict[str, str] = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }

        csp = get_csp_header(config)
        if csp:
            headers["Content-Security-Policy"] = csp

        return HTMLResponse(content=html, headers=headers)

    @app.get("/offline", include_in_schema=False, response_class=HTMLResponse)
    async def serve_offline_page() -> HTMLResponse:
        """Serve the offline fallback page (cached by the service worker)."""
        html = _build_offline_page()
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    logger.info("app shell routes registered: GET /, GET /offline")


def _build_offline_page() -> str:
    """Build a minimal offline fallback page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{APP_NAME} — Offline</title>
  <style>
    html, body {{
      margin: 0; padding: 0; height: 100%;
      background: {BRAND_DARK}; color: #f0f0f0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; align-items: center; justify-content: center;
    }}
    .container {{
      text-align: center;
      padding: 40px 24px;
      max-width: 360px;
    }}
    .icon {{
      font-size: 64px;
      margin-bottom: 24px;
    }}
    h1 {{
      font-size: 22px;
      font-weight: 600;
      color: {BRAND_TEAL};
      margin-bottom: 12px;
    }}
    p {{
      font-size: 15px;
      color: #888;
      line-height: 1.6;
      margin-bottom: 28px;
    }}
    button {{
      background: {BRAND_TEAL};
      color: #fff;
      border: none;
      border-radius: 12px;
      padding: 14px 28px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      min-height: 48px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="icon" aria-hidden="true">📡</div>
    <h1>You're offline</h1>
    <p>
      {APP_NAME} requires an internet connection.<br>
      Your messages are saved and will be sent when you reconnect.
    </p>
    <button onclick="window.location.reload()">Try again</button>
  </div>
</body>
</html>"""
