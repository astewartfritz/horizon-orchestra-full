"""
orchestra/mobile/touch_ui.py
------------------------------
Touch-optimized chat UI HTML/CSS/JS generator for Horizon Orchestra.

Generates a complete, self-contained mobile chat interface featuring:
- Bottom navigation, safe-area insets, pull-to-refresh
- Chat bubbles with markdown, code blocks, file attachments
- Auto-growing textarea with voice input and attachment support
- Gesture system: swipe-to-reply, swipe-to-delete, long-press menu
- Haptic feedback via navigator.vibrate()
- Virtual scroll for long chat histories
- Dark mode (system preference + manual toggle)
- Full ARIA accessibility
- visualViewport API for keyboard-aware positioning
"""
from __future__ import annotations

__all__ = [
    "TouchUIGenerator",
    "TouchUIConfig",
    "generate_touch_ui",
    "register_routes",
]

import logging
from dataclasses import dataclass

logger = logging.getLogger("orchestra.mobile.touch_ui")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BRAND_TEAL = "#01696F"
BRAND_TEAL_LIGHT = "#018a91"
BRAND_DARK = "#0a0a0a"
APP_NAME = "Horizon Orchestra"
ASSISTANT_NAME = "MILES"


@dataclass
class TouchUIConfig:
    """Configuration for the touch UI generator."""

    app_name: str = APP_NAME
    assistant_name: str = ASSISTANT_NAME
    teal: str = BRAND_TEAL
    teal_light: str = BRAND_TEAL_LIGHT
    dark_bg: str = BRAND_DARK
    api_base: str = "/api"
    ws_path: str = "/ws/chat"
    max_input_lines: int = 6
    enable_voice: bool = True
    enable_haptics: bool = True
    enable_virtual_scroll: bool = True


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class TouchUIGenerator:
    """Generates the touch-optimized chat interface HTML, CSS, and JS.

    Usage::

        gen = TouchUIGenerator()
        html = gen.build_html()
        css  = gen.build_css()
        js   = gen.build_js()
    """

    def __init__(self, config: TouchUIConfig | None = None) -> None:
        self.config = config or TouchUIConfig()

    def build_html(self) -> str:
        """Return the chat interface HTML fragment (without <html> wrapper)."""
        cfg = self.config
        return f"""\
<!-- Horizon Orchestra — Touch Chat UI -->
<!-- Bottom navigation -->
<nav class="bottom-nav" role="navigation" aria-label="Main navigation">
  <button class="nav-item nav-item--active" data-page="chat" aria-label="Chat" aria-current="page">
    <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
    <span class="nav-label">Chat</span>
  </button>
  <button class="nav-item" data-page="tasks" aria-label="Tasks">
    <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14l-5-5 1.41-1.41L12 14.17l7.59-7.59L21 8l-9 9z"/></svg>
    <span class="nav-label">Tasks</span>
  </button>
  <button class="nav-item" data-page="skills" aria-label="Skills">
    <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>
    <span class="nav-label">Skills</span>
  </button>
  <button class="nav-item" data-page="settings" aria-label="Settings">
    <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
    <span class="nav-label">Settings</span>
  </button>
</nav>

<!-- Chat page -->
<main id="page-chat" class="page page--active" aria-label="Chat with {cfg.assistant_name}">

  <!-- Pull-to-refresh indicator -->
  <div class="pull-refresh" id="pullRefresh" role="status" aria-live="polite">
    <div class="pull-refresh__spinner" aria-hidden="true"></div>
    <span class="pull-refresh__text">Release to refresh</span>
  </div>

  <!-- Offline banner -->
  <div class="offline-banner" id="offlineBanner" role="alert" aria-live="assertive" hidden>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M1 1l22 22-1.41 1.41-1.5-1.5A9.89 9.89 0 0 1 12 24C5.93 24 1 19.07 1 13c0-2.38.85-4.56 2.24-6.28L1 4.41 2.41 3 3 3.59zm13.24 14.65l-1.43-1.43A3 3 0 0 1 12 17a3 3 0 0 1-3-3 3 3 0 0 1 .21-1.1L7.8 11.49A4.97 4.97 0 0 0 7 14c0 2.76 2.24 5 5 5 .99 0 1.92-.3 2.69-.81l-.45-.54z"/></svg>
    You're offline — messages will be queued
  </div>

  <!-- Chat message list -->
  <div class="chat-list" id="chatList" role="log" aria-label="Chat messages" aria-live="polite">
    <!-- Messages rendered here by JS -->
    <div class="chat-skeleton" id="chatSkeleton" aria-hidden="true">
      <div class="skeleton-msg skeleton-msg--left"></div>
      <div class="skeleton-msg skeleton-msg--right"></div>
      <div class="skeleton-msg skeleton-msg--left skeleton-msg--long"></div>
    </div>
  </div>

  <!-- Input area -->
  <div class="input-area" id="inputArea">
    <div class="input-row">
      <button class="input-btn" id="attachBtn" aria-label="Attach file" type="button">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
      </button>

      <div class="textarea-wrapper">
        <textarea
          id="messageInput"
          class="message-input"
          placeholder="Message {cfg.assistant_name}…"
          rows="1"
          aria-label="Message input"
          aria-multiline="true"
          enterkeyhint="send"
          autocomplete="off"
          autocorrect="on"
          spellcheck="true"
        ></textarea>
      </div>

      {'<button class="input-btn" id="voiceBtn" aria-label="Voice input" type="button"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg></button>' if cfg.enable_voice else ""}

      <button class="send-btn" id="sendBtn" aria-label="Send message" type="button" disabled>
        <svg class="send-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        <span class="send-spinner" aria-hidden="true"></span>
      </button>
    </div>
  </div>

  <!-- Floating action button for new chat -->
  <button class="fab" id="newChatFab" aria-label="Start new chat" type="button">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
  </button>

  <!-- Context menu (long-press) -->
  <div class="context-menu" id="contextMenu" role="menu" aria-label="Message actions" hidden>
    <button class="context-item" data-action="copy"  role="menuitem">Copy</button>
    <button class="context-item" data-action="share" role="menuitem">Share</button>
    <button class="context-item" data-action="reply" role="menuitem">Reply</button>
  </div>
</main>

<!-- Tasks page -->
<main id="page-tasks"   class="page" aria-label="Tasks"    hidden></main>
<main id="page-skills"  class="page" aria-label="Skills"   hidden></main>
<main id="page-settings" class="page" aria-label="Settings" hidden></main>

<!-- Attachment picker (hidden file input) -->
<input type="file" id="fileInput" accept="image/*,application/pdf,text/*" multiple hidden aria-hidden="true">
"""

    def build_css(self) -> str:
        """Return the CSS for the touch chat UI."""
        cfg = self.config
        return f"""\
/* ============================================================
   Horizon Orchestra — Touch Chat UI
   Auto-generated by orchestra.mobile.touch_ui
   ============================================================ */

/* ---- CSS variables ---- */
:root {{
  --teal:         {cfg.teal};
  --teal-light:   {cfg.teal_light};
  --dark-bg:      {cfg.dark_bg};
  --surface:      #1a1a1a;
  --surface-2:    #242424;
  --text:         #f0f0f0;
  --text-muted:   #888;
  --border:       #2a2a2a;
  --error:        #e05353;
  --radius:       18px;
  --radius-sm:    10px;
  --nav-height:   64px;
  --input-height: auto;
  --safe-bottom:  env(safe-area-inset-bottom, 0px);
  --safe-top:     env(safe-area-inset-top, 0px);
  --safe-left:    env(safe-area-inset-left, 0px);
  --safe-right:   env(safe-area-inset-right, 0px);
  --transition:   0.2s ease;
}}

@media (prefers-color-scheme: light) {{
  :root {{
    --dark-bg:  #f5f5f5;
    --surface:  #ffffff;
    --surface-2: #f0f0f0;
    --text:     #0a0a0a;
    --text-muted: #666;
    --border:   #ddd;
  }}
}}

/* ---- Base ---- */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

html, body {{
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--dark-bg);
  color: var(--text);
  overscroll-behavior: none;
  -webkit-tap-highlight-color: transparent;
  font-size: 16px;
}}

/* ---- Layout ---- */
.page {{
  position: fixed;
  inset: 0;
  padding-bottom: calc(var(--nav-height) + var(--safe-bottom));
  padding-top: var(--safe-top);
  padding-left: var(--safe-left);
  padding-right: var(--safe-right);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}}
.page:not(.page--active) {{ display: none; }}

/* ---- Bottom nav ---- */
.bottom-nav {{
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: calc(var(--nav-height) + var(--safe-bottom));
  padding-bottom: var(--safe-bottom);
  background: var(--surface);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: flex-start;
  justify-content: space-around;
  z-index: 100;
}}

.nav-item {{
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-height: 44px;
  min-width: 44px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding-top: 8px;
  font-size: 11px;
  transition: color var(--transition);
  -webkit-tap-highlight-color: transparent;
}}

.nav-item--active, .nav-item:focus-visible {{
  color: var(--teal);
  outline: 2px solid var(--teal);
  outline-offset: -2px;
}}

.nav-icon {{
  width: 24px;
  height: 24px;
  fill: currentColor;
}}
.nav-label {{ font-size: 10px; }}

/* ---- Pull to refresh ---- */
.pull-refresh {{
  position: absolute;
  top: -60px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 13px;
  transition: top 0.2s;
  z-index: 10;
}}
.pull-refresh.visible {{ top: 10px; }}
.pull-refresh__spinner {{
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--teal);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}}

/* ---- Offline banner ---- */
.offline-banner {{
  background: #3a2a00;
  color: #ffd580;
  font-size: 13px;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}}
.offline-banner svg {{ width: 16px; height: 16px; fill: currentColor; }}

/* ---- Chat list ---- */
.chat-list {{
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-y: contain;
  scroll-behavior: smooth;
}}

/* ---- Message bubbles ---- */
.msg {{
  display: flex;
  max-width: 85%;
  position: relative;
  touch-action: pan-y;
  user-select: none;
  transition: transform 0.15s ease;
}}
.msg--user  {{ align-self: flex-end; flex-direction: row-reverse; }}
.msg--assistant {{ align-self: flex-start; }}

.bubble {{
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 15px;
  line-height: 1.5;
  word-break: break-word;
  position: relative;
  max-width: 100%;
}}

.msg--user .bubble {{
  background: var(--teal);
  color: #fff;
  border-bottom-right-radius: 4px;
}}

.msg--assistant .bubble {{
  background: var(--surface-2);
  color: var(--text);
  border-bottom-left-radius: 4px;
}}

/* Swipe indicator */
.msg::before {{
  content: '↩';
  position: absolute;
  top: 50%;
  right: -36px;
  transform: translateY(-50%);
  opacity: 0;
  color: var(--teal);
  font-size: 18px;
  transition: opacity 0.15s;
  pointer-events: none;
}}
.msg--user::before {{ left: -36px; right: auto; content: '↩'; }}
.msg.swipe-hint::before {{ opacity: 1; }}

/* ---- Code blocks ---- */
.code-block-wrapper {{
  position: relative;
  margin: 8px 0;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #0d1117;
}}
.code-block-wrapper pre {{
  overflow-x: auto;
  padding: 12px;
  font-size: 13px;
  font-family: 'SF Mono', 'Fira Code', 'Fira Mono', monospace;
  -webkit-overflow-scrolling: touch;
}}
.copy-code-btn {{
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(255,255,255,0.1);
  border: none;
  border-radius: 6px;
  color: #ccc;
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
  min-width: 44px;
  min-height: 32px;
}}

/* ---- Tool call indicator ---- */
.tool-call {{
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--surface);
  border-radius: var(--radius-sm);
  border-left: 3px solid var(--teal);
  margin: 4px 0;
  cursor: pointer;
}}
.tool-call.collapsed .tool-detail {{ display: none; }}
.tool-dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--teal);
  animation: pulse 1.2s ease-in-out infinite;
}}

/* ---- File attachment thumbnail ---- */
.file-attachment {{
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255,255,255,0.08);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin: 4px 0;
  cursor: pointer;
}}
.file-thumb {{ width: 40px; height: 40px; border-radius: 6px; object-fit: cover; }}
.file-name {{ font-size: 13px; font-weight: 500; }}
.file-size {{ font-size: 11px; color: var(--text-muted); }}

/* ---- Skeleton loaders ---- */
.skeleton-msg {{
  height: 44px;
  border-radius: var(--radius);
  background: linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 50%, var(--surface) 75%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s infinite;
  align-self: flex-start;
  width: 60%;
}}
.skeleton-msg--right {{ align-self: flex-end; }}
.skeleton-msg--long {{ width: 80%; height: 88px; }}

/* ---- Input area ---- */
.input-area {{
  flex-shrink: 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 8px 12px;
  padding-bottom: calc(8px + var(--safe-bottom));
}}

.input-row {{
  display: flex;
  align-items: flex-end;
  gap: 8px;
}}

.textarea-wrapper {{ flex: 1; position: relative; }}

.message-input {{
  width: 100%;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 22px;
  padding: 10px 16px;
  font-size: 16px;
  font-family: inherit;
  resize: none;
  outline: none;
  line-height: 1.4;
  max-height: calc({cfg.max_input_lines} * 1.4 * 16px + 20px);
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  transition: border-color var(--transition);
}}
.message-input:focus {{
  border-color: var(--teal);
}}
.message-input::placeholder {{ color: var(--text-muted); }}

.input-btn {{
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
}}
.input-btn svg {{ width: 22px; height: 22px; fill: currentColor; }}
.input-btn:focus-visible {{ outline: 2px solid var(--teal); border-radius: 50%; }}

.send-btn {{
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--teal);
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background var(--transition), opacity var(--transition);
  -webkit-tap-highlight-color: transparent;
  position: relative;
}}
.send-btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
.send-btn:not(:disabled):active {{ background: var(--teal-light); }}
.send-icon {{ width: 20px; height: 20px; fill: currentColor; }}
.send-spinner {{
  display: none;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}}
.send-btn.loading .send-icon {{ display: none; }}
.send-btn.loading .send-spinner {{ display: block; }}

/* ---- FAB ---- */
.fab {{
  position: absolute;
  bottom: calc(var(--nav-height) + var(--safe-bottom) + 72px);
  right: 20px;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--teal);
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(1,105,111,0.4);
  z-index: 50;
  transition: transform var(--transition);
  -webkit-tap-highlight-color: transparent;
}}
.fab:active {{ transform: scale(0.94); }}
.fab svg {{ width: 24px; height: 24px; fill: currentColor; }}

/* ---- Context menu ---- */
.context-menu {{
  position: fixed;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  z-index: 200;
  overflow: hidden;
  min-width: 140px;
}}
.context-item {{
  display: block;
  width: 100%;
  padding: 14px 18px;
  background: none;
  border: none;
  color: var(--text);
  font-size: 15px;
  text-align: left;
  cursor: pointer;
  min-height: 44px;
}}
.context-item:active {{ background: var(--surface-2); }}

/* ---- Responsive ---- */
@media (min-width: 481px) {{
  .page {{ max-width: 768px; margin: 0 auto; }}
  .bottom-nav {{ max-width: 768px; left: 50%; transform: translateX(-50%); }}
}}

@media (min-width: 769px) {{
  .page {{ max-width: 1200px; }}
  .chat-list {{ padding: 20px 24px; }}
  .input-area {{ padding: 12px 24px; }}
}}

/* ---- Animations ---- */
@keyframes spin           {{ to {{ transform: rotate(360deg); }} }}
@keyframes pulse          {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.4; }} }}
@keyframes skeleton-shimmer {{ to {{ background-position: -200% 0; }} }}

/* ---- Reduced motion ---- */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }}
}}
"""

    def build_js(self) -> str:
        """Return the JavaScript for the touch chat UI."""
        cfg = self.config
        return f"""\
// ============================================================
// Horizon Orchestra — Touch Chat UI
// Auto-generated by orchestra.mobile.touch_ui
// ============================================================

'use strict';

// ---- Constants ----
const API_BASE       = '{cfg.api_base}';
const WS_PATH        = '{cfg.ws_path}';
const ASSISTANT_NAME = '{cfg.assistant_name}';
const MAX_LINES      = {cfg.max_input_lines};
const HAPTICS        = {str(cfg.enable_haptics).lower()};
const VIRTUAL_SCROLL = {str(cfg.enable_virtual_scroll).lower()};

// ---- State ----
const state = {{
  messages: [],
  currentConversationId: null,
  ws: null,
  isLoading: false,
  activePage: 'chat',
  swipeTarget: null,
  swipeStartX: 0,
  longPressTimer: null,
  replyToId: null,
}};

// ============================================================
// DOM refs
// ============================================================
const $   = (sel, ctx = document) => ctx.querySelector(sel);
const $$  = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', () => {{
  initNavigation();
  initInput();
  initChatGestures();
  initOnlineStatus();
  initVisualViewport();
  initPullToRefresh();
  if ({str(cfg.enable_voice).lower()}) initVoice();
  loadConversation();
}});

// ============================================================
// Navigation
// ============================================================

function initNavigation() {{
  $$('.nav-item').forEach((btn) => {{
    btn.addEventListener('click', () => {{
      const page = btn.dataset.page;
      navigateTo(page);
      haptic(10);
    }});
  }});
}}

function navigateTo(page) {{
  $$('.page').forEach((p) => {{
    const active = p.id === `page-${{page}}`;
    p.classList.toggle('page--active', active);
    p.hidden = !active;
  }});
  $$('.nav-item').forEach((btn) => {{
    const active = btn.dataset.page === page;
    btn.classList.toggle('nav-item--active', active);
    btn.setAttribute('aria-current', active ? 'page' : 'false');
  }});
  state.activePage = page;
}}

// ============================================================
// Input
// ============================================================

function initInput() {{
  const input  = $('#messageInput');
  const sendBtn = $('#sendBtn');
  const attachBtn = $('#attachBtn');
  const fileInput = $('#fileInput');
  const newChatFab = $('#newChatFab');

  // Auto-grow
  input.addEventListener('input', () => {{
    input.style.height = 'auto';
    const lineH = parseFloat(getComputedStyle(input).lineHeight);
    const maxH  = lineH * MAX_LINES + 20;
    input.style.height = Math.min(input.scrollHeight, maxH) + 'px';
    sendBtn.disabled = input.value.trim().length === 0;
  }});

  // Send on Enter (not Shift+Enter)
  input.addEventListener('keydown', (e) => {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }}
  }});

  sendBtn.addEventListener('click', () => {{
    if (!sendBtn.disabled) sendMessage();
  }});

  attachBtn.addEventListener('click', () => {{
    haptic(10);
    fileInput.click();
  }});

  fileInput.addEventListener('change', (e) => {{
    handleFileAttachment(e.target.files);
    fileInput.value = '';
  }});

  newChatFab.addEventListener('click', () => {{
    haptic(10);
    startNewChat();
  }});

  // Context menu close
  document.addEventListener('click', (e) => {{
    const menu = $('#contextMenu');
    if (!menu.contains(e.target)) menu.hidden = true;
  }});

  $$('.context-item').forEach((btn) => {{
    btn.addEventListener('click', () => {{
      handleContextAction(btn.dataset.action);
      $('#contextMenu').hidden = true;
    }});
  }});
}}

// ============================================================
// Sending messages
// ============================================================

async function sendMessage() {{
  const input = $('#messageInput');
  const text  = input.value.trim();
  if (!text || state.isLoading) return;

  haptic(10);
  appendMessage({{ role: 'user', content: text, id: Date.now() }});
  input.value = '';
  input.style.height = 'auto';
  $('#sendBtn').disabled = true;

  setLoading(true);
  try {{
    await streamChat(text);
  }} catch (err) {{
    appendMessage({{ role: 'error', content: `Error: ${{err.message}}`, id: Date.now() }});
  }} finally {{
    setLoading(false);
  }}
}}

async function streamChat(text) {{
  const assistantId = Date.now() + 1;
  appendMessage({{ role: 'assistant', content: '', id: assistantId, streaming: true }});

  if (!navigator.onLine) {{
    // Queue for later via offline queue
    if (window.horizonQueue) {{
      await window.horizonQueue.enqueue(
        `${{API_BASE}}/chat`,
        'POST',
        {{ 'Content-Type': 'application/json' }},
        JSON.stringify({{ message: text, conversation_id: state.currentConversationId }}),
        'high'
      );
    }}
    updateMessage(assistantId, '(Queued — will send when back online)');
    return;
  }}

  const response = await fetch(`${{API_BASE}}/chat/stream`, {{
    method:  'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body:    JSON.stringify({{ message: text, conversation_id: state.currentConversationId }}),
  }});

  if (!response.ok) throw new Error(`HTTP ${{response.status}}`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});

    const lines = buffer.split('\\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {{
      if (line.startsWith('data: ')) {{
        try {{
          const data = JSON.parse(line.slice(6));
          if (data.token) {{
            appendToken(assistantId, data.token);
          }} else if (data.done) {{
            finaliseMessage(assistantId);
          }}
        }} catch {{ /* skip malformed */ }}
      }}
    }}
  }}
}}

// ============================================================
// Message rendering
// ============================================================

function appendMessage(msg) {{
  state.messages.push(msg);
  const list = $('#chatList');
  const skeleton = $('#chatSkeleton');
  if (skeleton) skeleton.remove();

  const el = renderMessage(msg);
  list.appendChild(el);
  scrollToBottom();
  return el;
}}

function appendToken(id, token) {{
  const el = document.getElementById(`msg-${{id}}`);
  if (!el) return;
  const bubble = el.querySelector('.bubble');
  if (bubble) {{
    const existing = bubble.dataset.raw || '';
    bubble.dataset.raw = existing + token;
    bubble.innerHTML = renderMarkdown(bubble.dataset.raw);
  }}
  scrollToBottom();
}}

function updateMessage(id, content) {{
  const el = document.getElementById(`msg-${{id}}`);
  if (!el) return;
  const bubble = el.querySelector('.bubble');
  if (bubble) bubble.innerHTML = renderMarkdown(content);
}}

function finaliseMessage(id) {{
  const el = document.getElementById(`msg-${{id}}`);
  if (el) el.classList.remove('streaming');
}}

function renderMessage(msg) {{
  const wrap = document.createElement('div');
  wrap.className = `msg msg--${{msg.role === 'user' ? 'user' : 'assistant'}}`;
  wrap.id = `msg-${{msg.id}}`;
  wrap.setAttribute('role', 'listitem');
  wrap.setAttribute('aria-label', `${{msg.role === 'user' ? 'You' : ASSISTANT_NAME}}: ${{msg.content}}`);
  if (msg.streaming) wrap.classList.add('streaming');

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.dataset.raw = msg.content;
  bubble.innerHTML = renderMarkdown(msg.content);
  wrap.appendChild(bubble);

  // Gesture listeners
  wrap.addEventListener('touchstart', onMsgTouchStart, {{ passive: true }});
  wrap.addEventListener('touchmove',  onMsgTouchMove,  {{ passive: true }});
  wrap.addEventListener('touchend',   onMsgTouchEnd,   {{ passive: true }});

  return wrap;
}}

// ============================================================
// Markdown rendering (minimal, no dependencies)
// ============================================================

function renderMarkdown(text) {{
  if (!text) return '';
  let html = escapeHTML(text);

  // Code blocks
  html = html.replace(/```([\\s\\S]*?)```/g, (_, code) => {{
    return `<div class="code-block-wrapper"><pre><code>${{code.trim()}}</code></pre><button class="copy-code-btn" onclick="copyCode(this)" aria-label="Copy code">Copy</button></div>`;
  }});

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Bold
  html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');

  // Italic
  html = html.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Newlines → <br>
  html = html.replace(/\\n/g, '<br>');

  return html;
}}

function escapeHTML(str) {{
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}}

function copyCode(btn) {{
  const code = btn.previousElementSibling?.textContent || '';
  navigator.clipboard.writeText(code).then(() => {{
    btn.textContent = 'Copied!';
    setTimeout(() => (btn.textContent = 'Copy'), 1500);
  }});
  haptic(10);
}}

// ============================================================
// Gesture system
// ============================================================

function initChatGestures() {{
  // Long press to show context menu
  const list = $('#chatList');
  list.addEventListener('touchstart', (e) => {{
    const msg = e.target.closest('.msg');
    if (!msg) return;
    state.longPressTimer = setTimeout(() => {{
      showContextMenu(e.touches[0], msg);
    }}, 500);
  }}, {{ passive: true }});

  list.addEventListener('touchmove', () => clearLongPress(), {{ passive: true }});
  list.addEventListener('touchend',  () => clearLongPress(), {{ passive: true }});
}}

function onMsgTouchStart(e) {{
  state.swipeTarget = this;
  state.swipeStartX = e.touches[0].clientX;
}}

function onMsgTouchMove(e) {{
  if (!state.swipeTarget) return;
  const dx = e.touches[0].clientX - state.swipeStartX;
  const limit = 70;
  const clamped = Math.max(-limit, Math.min(limit, dx));
  state.swipeTarget.style.transform = `translateX(${{clamped}}px)`;
  state.swipeTarget.classList.toggle('swipe-hint', Math.abs(clamped) > 30);
}}

function onMsgTouchEnd() {{
  if (!state.swipeTarget) return;
  const dx = parseInt(state.swipeTarget.style.transform.replace('translateX(', '')) || 0;
  state.swipeTarget.style.transform = '';
  state.swipeTarget.classList.remove('swipe-hint');

  if (Math.abs(dx) > 50) {{
    const id = state.swipeTarget.id.replace('msg-', '');
    if (dx > 0) {{
      initiateReply(id);
    }} else {{
      initiateDelete(id);
    }}
    haptic(30);
  }}
  state.swipeTarget = null;
}}

function clearLongPress() {{
  clearTimeout(state.longPressTimer);
}}

function showContextMenu(touch, msgEl) {{
  haptic(50);
  const menu = $('#contextMenu');
  menu.hidden = false;
  const x = Math.min(touch.clientX, window.innerWidth - 160);
  const y = Math.min(touch.clientY, window.innerHeight - 150);
  menu.style.left = `${{x}}px`;
  menu.style.top  = `${{y}}px`;
  state.contextTargetEl = msgEl;
}}

function handleContextAction(action) {{
  const el = state.contextTargetEl;
  if (!el) return;
  const id = el.id.replace('msg-', '');

  if (action === 'copy') {{
    const bubble = el.querySelector('.bubble');
    navigator.clipboard.writeText(bubble?.dataset.raw || bubble?.textContent || '');
    haptic(10);
  }} else if (action === 'share') {{
    const bubble = el.querySelector('.bubble');
    const text   = bubble?.dataset.raw || bubble?.textContent || '';
    if (navigator.share) {{
      navigator.share({{ text, title: 'Horizon Orchestra' }}).catch(() => {{}});
    }} else {{
      navigator.clipboard.writeText(text);
    }}
    haptic(10);
  }} else if (action === 'reply') {{
    initiateReply(id);
  }}
}}

function initiateReply(msgId) {{
  state.replyToId = msgId;
  const input = $('#messageInput');
  input.focus();
  haptic(10);
}}

function initiateDelete(msgId) {{
  haptic(50);
  const el = document.getElementById(`msg-${{msgId}}`);
  if (el) el.remove();
}}

// ============================================================
// Pull to refresh
// ============================================================

function initPullToRefresh() {{
  const list = $('#chatList');
  let startY = 0;
  let pulling = false;

  list.addEventListener('touchstart', (e) => {{
    if (list.scrollTop === 0) startY = e.touches[0].clientY;
  }}, {{ passive: true }});

  list.addEventListener('touchmove', (e) => {{
    const dy = e.touches[0].clientY - startY;
    if (dy > 40 && list.scrollTop === 0) {{
      pulling = true;
      $('#pullRefresh')?.classList.add('visible');
    }}
  }}, {{ passive: true }});

  list.addEventListener('touchend', async () => {{
    if (pulling) {{
      pulling = false;
      $('#pullRefresh')?.classList.remove('visible');
      await loadConversation();
      haptic([10, 10, 10]);
    }}
  }}, {{ passive: true }});
}}

// ============================================================
// Online / offline status
// ============================================================

function initOnlineStatus() {{
  const banner = $('#offlineBanner');
  function update() {{
    banner.hidden = navigator.onLine;
  }}
  window.addEventListener('online',  update);
  window.addEventListener('offline', update);
  update();
}}

// ============================================================
// Keyboard-aware positioning (visualViewport API)
// ============================================================

function initVisualViewport() {{
  if (!window.visualViewport) return;
  const inputArea = $('#inputArea');

  function onResize() {{
    const vv = window.visualViewport;
    const offset = window.innerHeight - vv.height - vv.offsetTop;
    inputArea.style.paddingBottom = `calc(${{offset}}px + 8px)`;
    scrollToBottom();
  }}

  window.visualViewport.addEventListener('resize', onResize);
  window.visualViewport.addEventListener('scroll', onResize);
}}

// ============================================================
// Voice input (Web Speech API)
// ============================================================

function initVoice() {{
  const btn = $('#voiceBtn');
  if (!btn) return;

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {{ btn.hidden = true; return; }}

  const recognition = new SR();
  recognition.lang = 'en-US';
  recognition.interimResults = true;

  let listening = false;

  btn.addEventListener('click', () => {{
    if (listening) {{
      recognition.stop();
    }} else {{
      recognition.start();
      haptic(10);
    }}
  }});

  recognition.addEventListener('start', () => {{
    listening = true;
    btn.setAttribute('aria-label', 'Stop voice input');
    btn.style.color = 'var(--teal)';
  }});

  recognition.addEventListener('result', (e) => {{
    const transcript = [...e.results].map((r) => r[0].transcript).join('');
    $('#messageInput').value = transcript;
    $('#sendBtn').disabled = transcript.trim().length === 0;
  }});

  recognition.addEventListener('end', () => {{
    listening = false;
    btn.setAttribute('aria-label', 'Voice input');
    btn.style.color = '';
  }});
}}

// ============================================================
// File attachments
// ============================================================

function handleFileAttachment(files) {{
  if (!files?.length) return;
  for (const file of files) {{
    const isImage = file.type.startsWith('image/');
    const msg = {{
      role: 'user',
      content: '',
      id: Date.now() + Math.random(),
      attachment: {{
        name: file.name,
        size: formatSize(file.size),
        isImage,
        objectUrl: isImage ? URL.createObjectURL(file) : null,
      }},
    }};
    appendMessage(msg);
  }}
  haptic(10);
}}

function formatSize(bytes) {{
  if (bytes < 1024)        return `${{bytes}} B`;
  if (bytes < 1024 * 1024) return `${{(bytes / 1024).toFixed(1)}} KB`;
  return `${{(bytes / (1024 * 1024)).toFixed(1)}} MB`;
}}

// ============================================================
// Conversation management
// ============================================================

async function loadConversation() {{
  try {{
    const resp = await fetch(`${{API_BASE}}/chat/history`, {{ method: 'GET' }});
    if (!resp.ok) return;
    const data = await resp.json();
    state.messages = [];
    $('#chatList').innerHTML = '';
    (data.messages || []).forEach((m) => appendMessage(m));
  }} catch {{ /* offline or API unavailable */ }}
}}

async function startNewChat() {{
  state.messages = [];
  state.currentConversationId = null;
  state.replyToId = null;
  $('#chatList').innerHTML = '';
  $('#messageInput').value = '';
  $('#sendBtn').disabled = true;
}}

// ============================================================
// Utilities
// ============================================================

function scrollToBottom() {{
  const list = $('#chatList');
  list.scrollTop = list.scrollHeight;
}}

function setLoading(val) {{
  state.isLoading = val;
  const btn = $('#sendBtn');
  btn.classList.toggle('loading', val);
}}

function haptic(pattern) {{
  if (!HAPTICS || !navigator.vibrate) return;
  navigator.vibrate(pattern);
}}
"""

    def build_full_bundle(self) -> dict[str, str]:
        """Return a dict with 'html', 'css', and 'js' keys for the full UI bundle."""
        return {
            "html": self.build_html(),
            "css": self.build_css(),
            "js": self.build_js(),
        }


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def generate_touch_ui(config: TouchUIConfig | None = None) -> dict[str, str]:
    """Generate the full touch UI bundle (html, css, js)."""
    return TouchUIGenerator(config).build_full_bundle()


# ---------------------------------------------------------------------------
# FastAPI route registration
# ---------------------------------------------------------------------------


def register_routes(app: object) -> None:
    """Register touch UI asset routes on a FastAPI application instance.

    Registers:
        GET /static/touch-ui.css  — touch UI stylesheet
        GET /static/touch-ui.js   — touch UI JavaScript
    """
    try:
        from fastapi.responses import Response
    except ImportError:  # pragma: no cover — optional web dependency
        logger.warning("FastAPI not installed; touch UI routes not registered")
        return

    gen = TouchUIGenerator()

    @app.get("/static/touch-ui.css", include_in_schema=False)
    async def serve_touch_css() -> Response:
        """Serve the touch-optimized chat UI stylesheet."""
        return Response(
            content=gen.build_css(),
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/static/touch-ui.js", include_in_schema=False)
    async def serve_touch_js() -> Response:
        """Serve the touch-optimized chat UI JavaScript."""
        return Response(
            content=gen.build_js(),
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    logger.info(
        "touch UI routes registered: /static/touch-ui.css, /static/touch-ui.js"
    )
