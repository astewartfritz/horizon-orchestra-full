from __future__ import annotations

from typing import Any


UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Orchestra">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<link rel="apple-touch-startup-image" href="/icon-512.png" media="(device-width: 375px) and (device-height: 812px)">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<title>Orchestra</title>
<script>
// Pre-paint theme — runs before CSS renders to prevent flash
(function(){try{var t=localStorage.getItem('orchestra-theme')||'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
</script>
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/highlight.min.js"></script>
<style>
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #1c2128;
  --bg-elevated: #1c2333;
  --border: #30363d;
  --border-subtle: #21262d;
  --border-accent: #58a6ff33;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --text-link: #58a6ff;
  --accent-blue: #1f6feb;
  --accent-blue-hover: #388bfd;
  --accent-green: #238636;
  --accent-green-hover: #2ea043;
  --accent-red: #da3633;
  --accent-red-hover: #f85149;
  --accent-orange: #d29922;
  --accent-purple: #8957e5;
  --gradient-blue: linear-gradient(135deg, #58a6ff, #1f6feb);
  --gradient-green: linear-gradient(135deg, #3fb950, #238636);
  --gradient-accent: linear-gradient(135deg, #58a6ff, #3fb950);
  --glass-bg: rgba(22, 27, 34, 0.8);
  --glass-border: rgba(48, 54, 61, 0.5);
  --msg-user-bg: rgba(31, 111, 235, 0.12);
  --msg-user-border: rgba(31, 111, 235, 0.25);
  --msg-assistant-bg: rgba(22, 27, 34, 0.6);
  --msg-assistant-border: rgba(48, 54, 61, 0.5);
  --msg-error-bg: rgba(255, 80, 80, 0.12);
  --msg-error-border: rgba(255, 80, 80, 0.25);
  --msg-error-text: #ff5050;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.5);
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --transition-fast: 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-normal: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
}
html[data-theme="light"], html.light-theme {
  --bg-primary: #f6f8fa;
  --bg-secondary: #ffffff;
  --bg-tertiary: #eaeef2;
  --bg-elevated: #ffffff;
  --border: #d0d7de;
  --border-subtle: #d8dee4;
  --border-accent: #0969da33;
  --text-primary: #1f2328;
  --text-secondary: #656d76;
  --text-link: #0969da;
  --accent-blue: #0969da;
  --accent-blue-hover: #0550ae;
  --accent-green: #1a7f37;
  --accent-green-hover: #2da44e;
  --accent-red: #d1242f;
  --accent-red-hover: #cf222e;
  --accent-orange: #9a6700;
  --accent-purple: #8250df;
  --glass-bg: rgba(246,248,250,0.88);
  --glass-border: rgba(208,215,222,0.6);
  --msg-user-bg: rgba(9,105,218,0.07);
  --msg-user-border: rgba(9,105,218,0.2);
  --msg-assistant-bg: rgba(255,255,255,0.8);
  --msg-assistant-border: rgba(208,215,222,0.6);
  --msg-error-bg: rgba(255,129,130,0.12);
  --msg-error-border: rgba(255,129,130,0.3);
  --msg-error-text: #cf222e;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.1);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.14);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.18);
}
.theme-transitioning, .theme-transitioning *, .theme-transitioning *::before, .theme-transitioning *::after {
  transition: background-color 260ms ease, border-color 260ms ease, color 260ms ease, box-shadow 260ms ease !important;
}
.theme-pill { display: inline-flex; align-items: center; background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 20px; padding: 2px; gap: 2px; }
.theme-pill__seg { background: none; border: none; border-radius: 16px; padding: 4px 11px; font-size: 11px; cursor: pointer; color: var(--text-secondary); font-family: inherit; transition: all 0.15s; line-height: 1; touch-action: manipulation; user-select: none; -webkit-user-select: none; }
.theme-pill__seg:hover { color: var(--text-primary); }
.theme-pill__seg.active { background: var(--bg-elevated); color: var(--text-primary); box-shadow: var(--shadow-sm); }
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { background: var(--bg-primary); }
body { font-family: var(--font-sans); background: var(--bg-primary); color: var(--text-primary); height: 100vh; display: flex; flex-direction: column; overflow: hidden; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
header { background: var(--glass-bg); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid var(--glass-border); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; position: relative; z-index: 50; }
header h1 { font-size: 16px; background: var(--gradient-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; font-weight: 700; letter-spacing: -0.3px; }
header .sub { font-size: 11px; color: var(--text-secondary); }
.header-btn { background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); padding: 5px 12px; font-size: 12px; border-radius: var(--radius-sm); cursor: pointer; font-family: inherit; transition: all var(--transition-fast); }
.header-btn:hover { background: var(--border); color: var(--text-primary); border-color: var(--text-link); box-shadow: var(--shadow-sm); }
.header-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
.miles-btn { display: inline-flex; align-items: center; gap: 6px; padding: 5px 13px; border-radius: var(--radius-sm); background: linear-gradient(135deg,#4040c8,#008f82); color: #fff; font-size: 12px; font-weight: 600; border: none; cursor: pointer; box-shadow: 0 2px 10px rgba(64,64,200,.3); transition: opacity .15s, transform .15s, box-shadow .15s; white-space: nowrap; }
.miles-btn:hover { opacity: .9; transform: translateY(-1px); box-shadow: 0 3px 16px rgba(64,64,200,.4); }
.miles-btn:active { transform: scale(.97); }
.miles-btn__m { font-size: 11px; font-weight: 800; width: 18px; height: 18px; border-radius: 4px; background: rgba(255,255,255,.2); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
#body { display: flex; flex: 1; overflow: hidden; }
#sidebar { width: 260px; background: var(--bg-secondary); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
#sidebar-header { padding: 12px 14px 10px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-subtle); gap: 8px; }
#sidebar-header h3 { font-size: 11px; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 1px; font-weight: 700; flex: 1; }
#sidebar-header .count { font-size: 10px; color: var(--accent-blue); background: rgba(31, 111, 235, 0.12); border: 1px solid rgba(31, 111, 235, 0.2); padding: 1px 7px; border-radius: 10px; font-weight: 700; }
#session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-item { padding: 8px 10px 8px 12px; border-radius: var(--radius-md); cursor: pointer; margin-bottom: 2px; border: 1px solid transparent; transition: all var(--transition-fast); background: transparent; position: relative; }
.session-item:hover { background: var(--bg-tertiary); border-color: var(--border-subtle); }
.session-item.active { background: rgba(31, 111, 235, 0.09); border-color: rgba(31, 111, 235, 0.22); }
.session-item .task { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; font-weight: 500; color: var(--text-primary); line-height: 1.4; padding-right: 16px; }
.session-item .session-meta { font-size: 10px; color: var(--text-secondary); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-item.in-progress .task::after { content: ' ●'; color: var(--accent-orange); animation: pulse 1.5s ease-in-out infinite; font-size: 8px; vertical-align: middle; }
.session-del { position: absolute; top: 50%; right: 6px; transform: translateY(-50%); background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 12px; line-height: 1; padding: 3px 5px; border-radius: var(--radius-sm); opacity: 0; transition: all var(--transition-fast); }
.session-item:hover .session-del { opacity: 0.5; }
.session-del:hover { opacity: 1 !important; color: var(--accent-red); background: rgba(218, 54, 51, 0.1); }
#sidebar-nav { display: flex; border-bottom: 1px solid var(--border); padding: 8px 8px 0; gap: 2px; background: var(--bg-secondary); }
.nav-btn { flex: 1; background: none; border: none; border-bottom: 2px solid transparent; color: var(--text-secondary); padding: 7px 4px; font-size: 11px; cursor: pointer; border-radius: var(--radius-sm) var(--radius-sm) 0 0; font-family: inherit; transition: all var(--transition-fast); font-weight: 500; white-space: nowrap; margin-bottom: -1px; letter-spacing: 0.1px; }
.nav-btn:hover { color: var(--text-primary); background: rgba(255,255,255,0.04); }
.nav-btn.active { color: var(--text-link); border-bottom-color: var(--accent-blue); background: rgba(31, 111, 235, 0.07); }
#sidebar-footer { padding: 10px 14px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--bg-secondary); }
#sidebar-footer .footer-label { display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
/* Toggle switch */
.toggle-switch { position: relative; width: 28px; height: 16px; flex-shrink: 0; }
.toggle-switch input { opacity: 0; width: 0; height: 0; position: absolute; }
.toggle-track { position: absolute; inset: 0; background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; transition: background var(--transition-fast), border-color var(--transition-fast); }
.toggle-track::after { content: ''; position: absolute; left: 2px; top: 50%; transform: translateY(-50%); width: 10px; height: 10px; border-radius: 50%; background: var(--text-secondary); transition: left var(--transition-fast), background var(--transition-fast); }
.toggle-switch input:checked + .toggle-track { background: rgba(31, 111, 235, 0.25); border-color: var(--accent-blue); }
.toggle-switch input:checked + .toggle-track::after { left: 14px; background: var(--accent-blue); }
#stop-btn { display: none; background: var(--accent-red); color: #fff; border: none; border-radius: var(--radius-md); padding: 10px 16px; font-size: 12px; cursor: pointer; font-weight: 600; height: 42px; }
.sidebar-view { flex: 1; display: none; flex-direction: column; overflow: hidden; }
.sidebar-view.active { display: flex; }
.ctx-tab { flex: 1; background: none; border: none; color: var(--text-secondary); padding: 8px; font-size: 11px; cursor: pointer; border-bottom: 2px solid transparent; font-family: inherit; transition: all var(--transition-fast); }
.ctx-tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.ctx-tab.active { color: var(--text-link); border-bottom-color: var(--accent-blue); }
#search-history:focus { outline: none; border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(31,111,235,0.12); }
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
#chat { flex: 1; display: flex; flex-direction: column; position: relative; min-height: 0; }
#welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; flex: 1; padding: 40px 20px; text-align: center; }
#welcome.hidden { display: none; }
#welcome h2 { font-size: 24px; font-weight: 700; margin-bottom: 8px; background: var(--gradient-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
#welcome p { color: var(--text-secondary); font-size: 14px; margin-bottom: 28px; max-width: 480px; line-height: 1.6; }
.example-tasks { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-width: 520px; }
.example-btn { background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); padding: 8px 16px; border-radius: var(--radius-md); font-size: 12px; cursor: pointer; transition: all var(--transition-fast); font-family: inherit; }
.example-btn:hover { background: var(--border); color: var(--text-primary); border-color: var(--text-link); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
#messages { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 16px 20px; scroll-behavior: smooth; }
#messages:empty + #welcome { display: flex; }
.msg { animation: msgSlideIn 0.3s ease-out; }
@keyframes msgSlideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.msg.assistant .msg-content { white-space: pre-wrap; word-break: break-word; overflow-x: auto; line-height: 1.6; }
.msg.assistant .msg-content p { margin-bottom: 10px; }
.msg.assistant .msg-content p:last-child { margin-bottom: 0; }
.msg.assistant .msg-content ul, .msg.assistant .msg-content ol { margin: 10px 0; padding-left: 24px; }
.msg.assistant .msg-content li { margin-bottom: 6px; line-height: 1.5; }
.msg.assistant .msg-content code { background: rgba(88, 166, 255, 0.1); padding: 2px 8px; border-radius: 4px; font-size: 13px; font-family: var(--font-mono); color: var(--text-link); }
.msg.assistant .msg-content pre { background: var(--bg-elevated); padding: 16px; border-radius: var(--radius-md); overflow-x: auto; margin: 12px 0; border: 1px solid var(--border-subtle); position: relative; }
.msg.assistant .msg-content pre code { background: none; padding: 0; font-size: 13px; line-height: 1.6; color: var(--text-primary); }
.msg.assistant .msg-content pre .copy-btn { position: absolute; top: 8px; right: 8px; background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); padding: 3px 10px; border-radius: 4px; font-size: 10px; cursor: pointer; opacity: 0; transition: opacity var(--transition-fast); font-family: inherit; }
.msg.assistant .msg-content pre:hover .copy-btn { opacity: 1; }
.msg.assistant .msg-content pre .copy-btn:hover { background: var(--border); color: var(--text-primary); }
.section-plan { margin: 12px 0; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; background: var(--bg-elevated); box-shadow: var(--shadow-sm); }
.section-plan-header { background: var(--gradient-blue); color: #fff; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; padding: 6px 12px; display: flex; align-items: center; gap: 6px; }
.section-plan-body { padding: 10px 12px; }
.section-plan-body ol { margin: 0; padding-left: 24px; }
.section-plan-body li { margin-bottom: 6px; line-height: 1.6; }
.section-plan-body li::marker { color: var(--accent-blue); font-weight: 700; }
.section-thought { margin: 10px 0; padding: 10px 14px; background: var(--bg-primary); border-left: 3px solid var(--accent-orange); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.section-thought-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--accent-orange); margin-bottom: 4px; }
.section-thought-body { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
.section-done { margin: 12px 0; padding: 10px 16px; background: rgba(35, 134, 54, 0.08); border: 1px solid rgba(35, 134, 54, 0.25); border-radius: var(--radius-md); display: flex; align-items: center; gap: 10px; }
.section-done-icon { width: 22px; height: 22px; border-radius: 50%; background: var(--gradient-green); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.section-done-text { font-size: 14px; font-weight: 600; color: var(--accent-green-hover); }
.msg.assistant .msg-content h1, .msg.assistant .msg-content h2, .msg.assistant .msg-content h3 { margin: 16px 0 8px; font-weight: 600; letter-spacing: -0.02em; }
.msg.assistant .msg-content h1 { font-size: 20px; }
.msg.assistant .msg-content h2 { font-size: 17px; }
.msg.assistant .msg-content h3 { font-size: 15px; }
.msg.assistant .msg-content blockquote { border-left: 3px solid var(--border); padding-left: 14px; color: var(--text-secondary); margin: 10px 0; font-style: italic; }
.msg.assistant .msg-content table { border-collapse: collapse; margin: 10px 0; font-size: 13px; width: 100%; }
.msg.assistant .msg-content th, .msg.assistant .msg-content td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
.msg.assistant .msg-content th { background: var(--bg-tertiary); font-weight: 600; }
.msg.assistant .msg-content a { color: var(--text-link); text-decoration: none; }
.msg.assistant .msg-content a:hover { text-decoration: underline; }
.msg.assistant .msg-content hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
.msg.assistant .thinking-details { margin-top: 10px; border-top: 1px solid var(--border-subtle); padding-top: 10px; }
.msg.assistant .thinking-details summary { font-size: 12px; color: var(--text-secondary); cursor: pointer; user-select: none; padding: 4px 0; font-weight: 500; }
.msg.assistant .thinking-details summary:hover { color: var(--text-link); }
.msg.assistant .thinking-details .thinking-text { font-size: 12px; color: var(--text-secondary); font-style: italic; padding: 8px 0 0; line-height: 1.6; white-space: pre-wrap; }
.streaming-cursor { display: inline-block; width: 2px; height: 18px; background: var(--text-link); margin-left: 2px; vertical-align: text-bottom; animation: blink 0.8s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
.msg .msg-time { font-size: 10px; color: var(--text-secondary); margin-top: 8px; opacity: 0.6; }
.msg.tool { background: var(--bg-primary); border: 1px solid var(--border-subtle); font-size: 13px; padding: 0; overflow: hidden; max-width: 100%; border-radius: var(--radius-sm); }
.msg.tool details { padding: 0; }
.msg.tool summary { padding: 10px 14px; cursor: pointer; color: var(--text-link); font-family: var(--font-sans); font-size: 13px; user-select: none; display: flex; align-items: center; gap: 8px; transition: background var(--transition-fast); }
.msg.tool summary:hover { background: var(--bg-tertiary); }
.msg.tool .tool-body { padding: 0 14px 12px; }
.msg.tool .tool-args { font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; font-family: var(--font-mono); white-space: pre-wrap; background: var(--bg-elevated); padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border-subtle); }
.msg.tool .tool-status { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.msg.tool .tool-status.running { background: rgba(88, 166, 255, 0.15); color: #58a6ff; }
.msg.tool .tool-status.done { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
.msg.tool .tool-status.error { background: rgba(255, 80, 80, 0.15); color: var(--msg-error-text); }
.msg.tool .tool-result { background: var(--bg-elevated); padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; max-height: 250px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; border: 1px solid var(--border-subtle); font-family: var(--font-mono); }
.msg.tool .tool-result.error { color: var(--msg-error-text); border-color: var(--msg-error-border); }
.msg.error { background: var(--msg-error-bg); border: 1px solid var(--msg-error-border); color: var(--msg-error-text); font-size: 13px; border-radius: var(--radius-sm); padding: 10px 14px; }
.msg.error .msg-label { font-size: 11px; font-weight: 600; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
#input-area { border-top: 1px solid var(--border); padding: 12px 20px 16px; background: var(--bg-secondary); flex-shrink: 0; }
#input-form { display: flex; gap: 8px; align-items: flex-end; }
#task-input { flex: 1; background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 16px; color: var(--text-primary); font-size: 14px; resize: none; font-family: inherit; line-height: 1.5; min-height: 42px; max-height: 130px; transition: all var(--transition-fast); }
#task-input:focus { outline: none; border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.15); }
#task-input:disabled { opacity: 0.4; }
#task-input::placeholder { color: var(--text-secondary); }
#send-btn { background: var(--gradient-green); color: #fff; border: none; border-radius: var(--radius-md); padding: 10px 20px; font-size: 13px; cursor: pointer; font-weight: 600; transition: all var(--transition-fast); white-space: nowrap; height: 42px; display: flex; align-items: center; gap: 6px; box-shadow: var(--shadow-sm); }
#send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--shadow-md); }
#send-btn:active:not(:disabled) { transform: translateY(0); }
#send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
#send-btn.stop { background: linear-gradient(135deg, #da3633, #f85149); }
#send-btn.stop:hover:not(:disabled) { background: linear-gradient(135deg, #f85149, #da3633); }
.tab-bar { display: flex; border-bottom: 1px solid var(--border); background: var(--bg-secondary); flex-shrink: 0; padding: 0 4px; }
.tab-btn { background: none; border: none; color: var(--text-secondary); padding: 10px 16px; font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; font-family: inherit; transition: all var(--transition-fast); font-weight: 500; }
.tab-btn:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.tab-btn.active { color: var(--text-link); border-bottom-color: var(--accent-blue); }
.tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.config-bar { padding: 6px 20px; background: var(--bg-secondary); border-bottom: 1px solid var(--border); display: flex; gap: 10px; font-size: 12px; align-items: center; flex-shrink: 0; flex-wrap: wrap; }
.config-bar select, .config-bar input { background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 4px 10px; color: var(--text-primary); font-size: 12px; font-family: inherit; transition: all var(--transition-fast); }
#engine { border-color: var(--accent-blue); font-weight: 600; color: var(--accent-blue); }
.config-bar select:focus, .config-bar input:focus { outline: none; border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.12); }
.config-bar label { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.config-bar input[type="checkbox"] { accent-color: var(--accent-green); }
.config-toggle { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 11px; padding: 4px 8px; border-radius: var(--radius-sm); display: flex; align-items: center; gap: 4px; transition: all var(--transition-fast); }
.config-toggle:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.overflow-item { display: block; width: 100%; background: none; border: none; color: var(--text-secondary); font-family: inherit; font-size: 12px; padding: 6px 12px; text-align: left; border-radius: var(--radius-sm); cursor: pointer; transition: all var(--transition-fast); white-space: nowrap; }
.overflow-item:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.config-fields { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.config-fields.collapsed { display: none; }
.model-presets { display: flex; gap: 4px; align-items: center; }
.preset-btn { display: inline-block; padding: 3px 10px; font-size: 10px; border-radius: var(--radius-sm); cursor: pointer; background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); font-family: inherit; transition: all var(--transition-fast); white-space: nowrap; }
.preset-btn:hover { background: var(--accent-blue); border-color: var(--accent-blue); color: #fff; }
.preset-btn.active { background: var(--accent-blue); border-color: var(--accent-blue); color: #fff; }
.preset-btn.active:hover { background: var(--bg-tertiary); border-color: var(--border); color: var(--text-secondary); }
.input-btn { background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 16px; line-height:1; height:40px; display:flex;align-items:center; justify-content:center; transition:all .15s; }
.input-btn:hover { background: var(--border); color: var(--text-primary); }
.input-btn.mic-btn.listening { background: var(--accent-orange); border-color: var(--accent-orange); color: #fff; animation: pulseGlow 1s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
@keyframes pulseGlow { 0%,100%{box-shadow:0 0 0 0 rgba(210,153,34,.4)} 50%{box-shadow:0 0 0 6px rgba(210,153,34,0)} }
.msg.assistant .msg-content .jarvis-highlight { background: linear-gradient(90deg, #58a6ff22, #3fb95022); border-radius:4px; padding:0 4px; }
.jarvis-active .msg.assistant { border-left: 3px solid var(--accent-blue); }
.jarvis-active header h1 { background: linear-gradient(90deg, #58a6ff, #3fb950); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.jarvis-active .preset-btn.active { background: linear-gradient(90deg, #1f6feb, #238636); border-color: transparent; }
.msg.move { border-left: 3px solid var(--accent-green); background: var(--bg-primary); padding: 6px 10px; margin: 2px 0; font-size: 12px; border-radius: 0 4px 4px 0; display: flex; align-items: center; gap: 6px; }
.msg.move .move-icon { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.msg.move .move-icon.plan { background: #58a6ff; }
.msg.move .move-icon.prompt { background: #d2a8ff; }
.msg.move .move-icon.response { background: #3fb950; }
.msg.move .move-icon.tool { background: #f0883e; }
.msg.move .move-label { font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.3px; flex-shrink: 0; }
.msg.move .move-text { color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.action-badge { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; }
.action-badge.edit { background: #23863644; color: #3fb950; }
.action-badge.read { background: #1f6feb44; color: #58a6ff; }
.action-badge.search { background: #8957e544; color: #a371f7; }
.action-badge.command { background: #d2992244; color: #d29922; }
.action-badge.git { background: #8957e544; color: #a371f7; }
.action-badge.web { background: #1f6feb44; color: #58a6ff; }
.action-badge.tool { background: #30363d44; color: var(--text-secondary); }
.action-badge.agent { background: #23863644; color: #3fb950; }
.action-badge.knowledge { background: #f0883e44; color: #f0883e; }
.msg.result { border: 1px solid #238636; background: #23863611; border-radius: 6px; padding: 10px 12px; margin: 6px 0; }
.msg.result .msg-label { color: #3fb950; }
.msg.error-llm { border: 2px solid #da3633; background: #da363311; border-radius: 6px; padding: 10px 12px; margin: 8px 0; }
.msg.error-llm .msg-label { color: #f85149; font-weight: 700; }
.msg.system { border-left: 3px solid var(--accent-green); background: var(--bg-primary); padding: 8px 12px; margin: 4px 0; border-radius: 0 6px 6px 0; }
.msg.system .msg-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--accent-green); font-weight: 700; }
.prince-btn { border-color: var(--accent-green) !important; color: var(--accent-green) !important; }
.sources-section { margin: 8px 0 12px; }
.sources-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); margin-bottom: 6px; }
.sources-list { display: flex; gap: 6px; flex-wrap: wrap; }
.source-card { display: flex; align-items: center; gap: 6px; padding: 6px 8px; background: var(--bg-primary); border: 1px solid var(--border-subtle); border-radius: 6px; text-decoration: none; font-size: 11px; min-width: 0; max-width: 200px; transition: border-color 0.15s; }
.source-card:hover { border-color: var(--text-link); }
.source-num { flex-shrink: 0; width: 18px; height: 18px; border-radius: 50%; background: var(--bg-tertiary); color: var(--text-secondary); display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; }
.source-body { display: flex; flex-direction: column; min-width: 0; gap: 1px; }
.source-favicon { width: 14px; height: 14px; flex-shrink: 0; }
.source-title { color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-url { color: var(--text-secondary); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
sup.citation { color: var(--text-link); font-weight: 700; cursor: pointer; font-size: 11px; padding: 0 1px; }
sup.citation:hover { text-decoration: underline; }
.msg.tool .tool-action { float: right; }
#ctx-panel { width: 340px; overflow: hidden; background: var(--bg-secondary); border-left: 1px solid var(--border); transition: width 0.25s ease; flex-shrink: 0; display: flex; flex-direction: column; }
#ctx-panel.closed { width: 0; }
#ctx-inner { padding: 14px; min-width: 320px; overflow-y: auto; flex: 1; }
#ctx-inner h3 { font-size: 12px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 10px; letter-spacing: 0.3px; display: flex; align-items: center; gap: 8px; }
#ctx-inner h3 .ctx-header-actions { margin-left: auto; display: flex; gap: 4px; }
#ctx-inner h3 .ctx-header-actions button { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 12px; padding: 2px 6px; border-radius: 4px; }
#ctx-inner h3 .ctx-header-actions button:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.ctx-section { margin-bottom: 14px; }
.ctx-section h4 { font-size: 10px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 6px; letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px; }
.ctx-section h4 .ctx-section-count { font-size: 9px; color: var(--text-secondary); background: var(--bg-tertiary); padding: 0 6px; border-radius: 8px; }
.ctx-gauge { height: 16px; background: var(--bg-primary); border-radius: 4px; overflow: hidden; display: flex; margin-bottom: 6px; }
.ctx-gauge-block { height: 100%; transition: width 0.4s ease; }
.ctx-gauge-free { height: 100%; background: var(--bg-tertiary); }
.ctx-gauge-reserve { height: 100%; background: var(--border); }
.ctx-stat-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.ctx-stat-row .lbl { color: var(--text-secondary); }
.ctx-stat-row .val { color: var(--text-primary); font-weight: 600; }
.ctx-tier { display: flex; align-items: center; padding: 3px 0; font-size: 11px; }
.ctx-dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }
.ctx-tier-count { margin-left: auto; color: var(--text-secondary); font-size: 10px; }
.ctx-tier-tokens { margin-left: 6px; color: var(--text-primary); font-size: 10px; min-width: 40px; text-align: right; }
.ctx-badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 700; text-transform: uppercase; }
.ctx-badge.critical { background: #ff505044; color: #ff5050; }
.ctx-badge.high { background: #ffb43244; color: #ffb432; }
.ctx-badge.moderate { background: #50a0ff44; color: #50a0ff; }
.ctx-badge.low { background: #23863644; color: #3fb950; }
.ctx-badge.empty { background: #30363d44; color: var(--text-secondary); }
.ctx-source-tag { display: inline-block; padding: 0 5px; border-radius: 4px; font-size: 9px; font-weight: 600; background: var(--bg-tertiary); color: var(--text-secondary); text-transform: lowercase; }
.ctx-actions { margin-top: 10px; display: flex; gap: 6px; }
.ctx-actions button { padding: 3px 8px; font-size: 10px; background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); border-radius: 4px; cursor: pointer; font-family: inherit; }
.ctx-actions button:hover { background: var(--border); color: var(--text-primary); }
.ctx-entries { max-height: 300px; overflow-y: auto; margin-top: 4px; border-top: 1px solid var(--border); padding-top: 6px; }
.ctx-entry { display: flex; align-items: flex-start; gap: 6px; padding: 5px 4px; border-radius: 4px; font-size: 11px; line-height: 1.3; cursor: default; transition: background 0.15s; }
.ctx-entry:hover { background: var(--bg-tertiary); }
.ctx-entry .ctx-entry-dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 4px; flex-shrink: 0; }
.ctx-entry .ctx-entry-body { flex: 1; min-width: 0; }
.ctx-entry .ctx-entry-head { display: flex; align-items: center; gap: 4px; margin-bottom: 1px; }
.ctx-entry .ctx-entry-source { font-size: 9px; color: var(--text-secondary); background: var(--bg-tertiary); padding: 0 4px; border-radius: 3px; text-transform: lowercase; }
.ctx-entry .ctx-entry-tokens { font-size: 9px; color: var(--text-secondary); margin-left: auto; white-space: nowrap; }
.ctx-entry .ctx-entry-text { color: var(--text-primary); word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.ctx-entry .ctx-entry-text.expanded { display: block; -webkit-line-clamp: unset; }
.ctx-entry .ctx-entry-expand { font-size: 9px; color: var(--text-link); cursor: pointer; background: none; border: none; padding: 0; font-family: inherit; }
.ctx-entry .ctx-entry-expand:hover { text-decoration: underline; }
@keyframes ctxEntryIn { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: translateX(0); } }
.ctx-entry.pending { animation: ctxEntryIn 0.25s ease-out; }
.ctx-entry.pending .ctx-entry-dot { animation: pulse 1s ease-in-out; }
#spinner { display: none; align-items: center; gap: 10px; padding: 12px 0; color: var(--text-secondary); font-size: 13px; flex-shrink: 0; justify-content: center; }
#spinner.active { display: flex; }
.spinner-icon { width: 16px; height: 16px; border: 2px solid rgba(88, 166, 255, 0.2); border-top-color: var(--text-link); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
#toast-container { position: fixed; bottom: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { padding: 10px 16px; border-radius: var(--radius-md); font-size: 12px; line-height: 1.4; max-width: 360px; box-shadow: var(--shadow-lg); animation: toastIn 0.3s ease-out; pointer-events: auto; backdrop-filter: blur(8px); }
.toast.info { background: rgba(31, 111, 235, 0.9); color: #fff; border: 1px solid rgba(88, 166, 255, 0.3); }
.toast.success { background: rgba(35, 134, 54, 0.9); color: #fff; border: 1px solid rgba(63, 185, 80, 0.3); }
.toast.error { background: rgba(218, 54, 51, 0.9); color: #fff; border: 1px solid rgba(248, 81, 73, 0.3); }
.toast.warning { background: rgba(210, 153, 34, 0.9); color: #fff; border: 1px solid rgba(210, 153, 34, 0.3); }
@keyframes toastIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastOut { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(20px); } }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; border: 2px solid transparent; background-clip: content-box; }
::-webkit-scrollbar-thumb:hover { background: var(--text-secondary); border: 2px solid transparent; background-clip: content-box; }
* { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
::selection { background: rgba(88, 166, 255, 0.3); color: var(--text-primary); }
@supports (padding: max(0px)) {
  body { padding-left: min(0px, env(safe-area-inset-left)); padding-right: min(0px, env(safe-area-inset-right)); }
  header { padding-left: max(10px, env(safe-area-inset-left)); padding-right: max(10px, env(safe-area-inset-right)); }
  #input-area { padding-bottom: max(14px, env(safe-area-inset-bottom)); }
}

@media (max-width: 1024px) {
  #ctx-panel { width: 280px; }
  #ctx-panel.closed { width: 0; }
  #ctx-inner { min-width: 260px; }
}

@media (max-width: 820px) {
  #sidebar { width: 220px; }
  .msg { max-width: 95%; }
  .config-bar { padding: 6px 12px; }
  #input-area { padding: 8px 12px 12px; }
  #messages { padding: 12px; }
  header .sub { display: none; }
  .header-btn { font-size: 11px; padding: 4px 8px; }
  .config-fields { gap: 6px; }
  .model-presets { gap: 3px; }
  .preset-btn { font-size: 9px; padding: 1px 6px; }
}

@media (max-width: 640px) {
  #sidebar { width: 200px; }
  #sidebar.collapsed { width: 0; border-right: none; }
  .msg { max-width: 98%; font-size: 13px; padding: 8px 10px; }
  #messages { padding: 8px; }
  .config-bar { padding: 4px 8px; gap: 6px; flex-wrap: nowrap; overflow-x: auto; }
  .config-fields { flex-wrap: nowrap; overflow-x: auto; gap: 4px; }
  .config-fields select { font-size: 11px; padding: 2px 4px; max-width: 100px; }
  #input-area { padding: 6px 8px 10px; }
  #input-form { gap: 4px; }
  #task-input { font-size: 13px; padding: 8px 10px; min-height: 36px; }
  #send-btn { font-size: 12px; padding: 8px 12px; height: 36px; }
  .input-btn { font-size: 14px; height: 36px; padding: 2px 8px; }
  .header-btn { font-size: 10px; padding: 3px 6px; white-space: nowrap; }
  header { padding: 6px 10px; flex-wrap: wrap; gap: 4px; }
  header h1 { font-size: 14px; }
  #status { font-size: 10px; padding: 1px 6px; }
  .section-plan-body { padding: 6px 8px; font-size: 12px; }
  .section-thought { padding: 6px 8px; font-size: 12px; }
  #input-extras { flex-wrap: wrap; gap: 4px; }
  #input-extras > span { display: none; }
  #img-name, #mic-status, #lang-badge { display: none !important; }
  .msg.tool .tool-args { font-size: 10px; }
  .msg.tool .tool-result { font-size: 11px; max-height: 150px; }
  #spinner { font-size: 11px; padding: 4px 0; }
  #tab-skills { font-size: 12px; }
  .llm-table { font-size: 10px; }
  .llm-table th, .llm-table td { padding: 3px 4px; }
}

@media (max-width: 480px) {
  #sidebar { display: none; }
  header .sub { display: none; }
  .config-bar select, .config-bar option { font-size: 10px; }
  .config-fields select { max-width: 80px; }
  #model { max-width: 120px; }
  .msg { padding: 6px 8px; margin-bottom: 8px; border-radius: 6px; }
  .msg.assistant .msg-content { font-size: 13px; }
  .msg.assistant .msg-content pre { font-size: 11px; padding: 8px; }
  .section-plan { margin: 6px 0; }
  .section-thought { margin: 4px 0; padding: 4px 8px; }
  .section-done { padding: 6px 10px; margin: 6px 0; }
  #task-input { font-size: 16px; }  /* prevents iOS zoom on focus */
  .header-btn { font-size: 9px; padding: 2px 5px; }
  .input-btn { font-size: 13px; height: 34px; padding: 2px 6px; }
  #send-btn { font-size: 11px; padding: 6px 10px; height: 34px; }
  #welcome h2 { font-size: 18px; }
  #welcome p { font-size: 13px; }
  .example-btn { font-size: 11px; padding: 6px 10px; }
  #ctx-panel { width: 100%; position: fixed; top: 0; right: 0; bottom: 0; z-index: 100; }
  #ctx-panel.closed { width: 0; }
  #ctx-inner { min-width: auto; padding: 10px; }
}

/* iPhone SE / small devices */
@media (max-width: 375px) {
  header h1 { font-size: 13px; }
  .header-btn { font-size: 8px; padding: 2px 4px; }
  #model { max-width: 100px; }
  #task-input { font-size: 16px; padding: 6px 8px; }
}

/* ── Mobile-first improvements ──────────────────────────────────────────── */

/* Collapse header buttons on small screens — show only essentials */
@media (max-width: 540px) {
  /* Hide secondary header buttons — keep only Run/Stop/Settings/Billing */
  #billing-btn, header a[href="/settings"] { display: none !important; }
  /* Header: single row that doesn't wrap, scrollable if needed */
  header { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding: 6px 10px; gap: 6px; }
  header::-webkit-scrollbar { display: none; }
  header h1 { white-space: nowrap; }
  /* Config bar: horizontal scroll, no wrap */
  .config-bar { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding: 4px 10px; gap: 8px; }
  .config-bar::-webkit-scrollbar { display: none; }
  /* Input area sits flush at bottom */
  #input-area { position: sticky; bottom: 0; background: var(--bg-secondary); }
  /* Diff panel full-screen on mobile */
  .diff-panel { width: 100%; right: -100%; }
  .diff-panel.open { right: 0; }
  /* Onboarding: full-screen */
  .ob-card { border-radius: 0; max-width: 100%; height: 100dvh; display: flex; flex-direction: column; }
  .ob-body { flex: 1; overflow-y: auto; }
  .ob-provider-grid { grid-template-columns: 1fr; }
  .ob-prompt-grid { grid-template-columns: 1fr; }
}

/* Sidebar toggle button — visible only on mobile */
#mobile-sidebar-toggle { display: none; }
@media (max-width: 480px) {
  #mobile-sidebar-toggle {
    display: flex; align-items: center; justify-content: center;
    background: var(--bg-tertiary); border: 1px solid var(--border);
    color: var(--text-secondary); width: 28px; height: 28px;
    border-radius: 6px; cursor: pointer; flex-shrink: 0; font-size: 14px;
  }
  /* Sidebar overlays on mobile */
  #sidebar {
    position: fixed; top: 0; left: 0; bottom: 0; z-index: 500;
    transform: translateX(-100%); transition: transform .25s ease;
    box-shadow: 4px 0 20px rgba(0,0,0,.5);
  }
  #sidebar.mobile-open {
    transform: translateX(0); display: flex !important;
  }
  /* Semi-transparent backdrop */
  #sidebar-backdrop {
    display: none; position: fixed; inset: 0; z-index: 499;
    background: rgba(0,0,0,.5);
  }
  #sidebar-backdrop.visible { display: block; }
}
.qa-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 14px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
  flex-shrink: 0;
}
.weather-btn {
  background: linear-gradient(135deg, #0d1f3c, #1f4e8c);
  border-color: #1f6feb;
  color: #58a6ff;
}
.weather-btn:hover {
  background: linear-gradient(135deg, #1f3d6e, #2563b0);
  box-shadow: 0 0 10px rgba(88,166,255,0.3);
}
.news-btn {
  background: linear-gradient(135deg, #0d2618, #1a4d2e);
  border-color: #238636;
  color: #3fb950;
}
.news-btn:hover {
  background: linear-gradient(135deg, #1a3d25, #256b3e);
  box-shadow: 0 0 10px rgba(63,185,80,0.3);
}
.ld-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 12px;
  padding: 5px 10px;
  border-radius: 16px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
  white-space: nowrap;
}
.ld-item:hover { background: var(--bg-elevated,#161b22); border-color: var(--accent-blue); }
</style>
</head>
<body>
<header>
  <div><h1>Orchestra</h1><div class="sub">Autonomous AI In Your Control</div></div>
  <div id="top-bar" style="display:flex;gap:8px;align-items:center;flex:1;margin:0 12px">
    <input id="search-history" type="search" placeholder="Search conversations..." style="flex:1;background:var(--bg-primary);border:1px solid var(--border);border-radius:6px;padding:5px 10px;color:var(--text-primary);font-size:12px;font-family:inherit;max-width:240px" oninput="searchHistory(this.value)">
    <div id="live-data-wrap" style="position:relative">
      <button class="qa-btn" id="live-data-btn" onclick="toggleLivePanel()" style="background:linear-gradient(135deg,#0d1f3c,#1a2d50);border-color:#1f6feb;color:#58a6ff;gap:5px">
        ⚡ Live Data ▾
      </button>
      <div id="live-panel" style="display:none;position:absolute;top:calc(100% + 6px);left:0;background:var(--bg-elevated,#161b22);border:1px solid var(--border);border-radius:10px;padding:6px 8px;z-index:999;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none;flex-direction:row;gap:4px;white-space:nowrap">
        <button class="ld-item" onclick="closeLivePanel();showWeather()">&#x26C5; Weather</button>
        <button class="ld-item" onclick="closeLivePanel();showNews()">&#x1F4F0; News</button>
        <button class="ld-item" onclick="closeLivePanel();showCrypto()">&#x20BF; Crypto</button>
        <button class="ld-item" onclick="closeLivePanel();showCurrency()">&#x1F4B1; Currency</button>
        <button class="ld-item" onclick="closeLivePanel();showWikipedia()">&#x1F4D6; Wikipedia</button>
        <button class="ld-item" onclick="closeLivePanel();showGitHub()">&#x1F5B1; GitHub</button>
        <button class="ld-item" onclick="closeLivePanel();showNASA()">&#x1F30C; NASA</button>
      </div>
    </div>
  </div>
  <!-- Theme toggle — centered absolutely in header -->
  <div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:10">
    <div class="theme-pill" id="theme-pill-wrap" title="Toggle light / dark mode">
      <button class="theme-pill__seg" id="theme-dark-btn" type="button">🌙 Dark</button>
      <button class="theme-pill__seg" id="theme-light-btn" type="button">☀️ Light</button>
    </div>
  </div>
  <div style="display:flex;gap:6px;align-items:center">
    <button id="mobile-sidebar-toggle" onclick="toggleMobileSidebar()" title="Menu">&#x2630;</button>
    <span id="status" style="font-size:12px;color:var(--text-secondary);padding:2px 8px;background:var(--bg-tertiary);border-radius:8px">Idle</span>
    <button class="header-btn" onclick="toggleContext()">Context</button>
    <button class="header-btn" onclick="newSession()">+ New</button>
    <a href="/healthcare/app" target="_blank" style="text-decoration:none"><button class="header-btn" style="color:#10b981;border-color:#10b981;font-weight:600">&#x1FA7A; Health</button></a>
    <a href="/legal/app" target="_blank" style="text-decoration:none"><button class="header-btn" style="color:#a78bfa;border-color:#a78bfa;font-weight:600">&#x2696; Legal</button></a>
    <a href="/finance/app" target="_blank" style="text-decoration:none"><button class="header-btn" style="color:#34d399;border-color:#34d399;font-weight:600">&#x1F4C8; Finance</button></a>
    <button class="header-btn" id="billing-btn" onclick="window.open('/billing','_blank')" style="font-weight:600" title="Billing &amp; plan"></button>
    <button class="header-btn" onclick="openSelfImprove()" title="Analyze Orchestra and surface improvements" style="color:#a78bfa;border-color:#a78bfa;font-weight:600">&#x1F9E0; Improve</button>
    <button class="header-btn" onclick="openLogsPanel()" title="Logs &amp; errors" id="logs-btn" style="color:#58a6ff;border-color:#58a6ff;font-weight:600;position:relative">&#x1F4CB; Logs<span id="logs-err-badge" style="display:none;position:absolute;top:-4px;right:-4px;background:#f85149;color:#fff;border-radius:50%;font-size:9px;font-weight:700;width:14px;height:14px;display:none;align-items:center;justify-content:center;line-height:1">!</span></button>
    <a href="/settings" target="_blank" style="text-decoration:none"><button class="header-btn" title="Settings">&#x2699;&#xFE0F;</button></a>
    <!-- Power-user overflow menu -->
    <div style="position:relative">
      <button class="header-btn" id="overflow-btn" onclick="toggleOverflow()" title="Developer tools" style="padding:5px 8px;font-size:13px">&#x22EF;</button>
      <div id="overflow-menu" style="display:none;position:absolute;top:calc(100%+6px);right:0;background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius-md);padding:4px;z-index:200;box-shadow:var(--shadow-md);min-width:150px;flex-direction:column;gap:2px">
        <button class="overflow-item" onclick="toggleJarvis();toggleOverflow()" id="jarvis-item">J.A.R.V.I.S mode</button>
        <button class="overflow-item" onclick="openSelfImprove();toggleOverflow()">&#x1F527; Self-Improve</button>
        <button class="overflow-item" onclick="openLogsPanel();toggleOverflow()">&#x1F4CB; Logs &amp; Errors</button>
        <button class="overflow-item" onclick="openMCPPanel();toggleOverflow()">&#x1F50C; MCP Servers</button>
        <button class="overflow-item" onclick="window.open('/observability','_blank');toggleOverflow()">Metrics</button>
        <button class="overflow-item" onclick="window.open('/api/langfuse','_blank');toggleOverflow()">LangFuse</button>
      </div>
    </div>
    <button class="miles-btn" onclick="window.location.href='/miles/'" title="Open M.I.L.E.S — your enterprise AI assistant">
      <span class="miles-btn__m">M</span>
      <span>M.I.L.E.S</span>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    </button>
  </div>
</header>
<div id="sidebar-backdrop" onclick="toggleMobileSidebar()"></div>
<div id="body">
  <!-- Left Sidebar: Navigation + Spaces + Sessions -->
  <div id="sidebar">
    <div id="sidebar-nav">
      <button class="nav-btn active" data-view="sessions" onclick="switchSidebar('sessions')">&#x1F4AC; Chats</button>
      <button class="nav-btn" data-view="files" onclick="switchSidebar('files')">&#x1F4C1; Files</button>
      <button class="nav-btn" data-view="github" onclick="switchSidebar('github')">&#x1F419; GitHub</button>
      <button class="nav-btn" data-view="history" onclick="switchSidebar('history')">&#x1F4DC; History</button>
      <button class="nav-btn" data-view="spaces" onclick="switchSidebar('spaces')">&#x1F4E6; Spaces</button>
    </div>
    <div id="sidebar-header">
      <h3 id="sidebar-title">Sessions</h3>
      <span class="count" id="session-count">0</span>
    </div>
    <!-- Sessions list (default view) -->
    <div id="session-list" class="sidebar-view active" hx-get="/api/sessions" hx-trigger="every:5s" hx-swap="innerHTML">
      <div style="color:var(--text-secondary);font-size:13px;padding:8px">Loading...</div>
    </div>
    <!-- Spaces list -->
    <div id="spaces-list" class="sidebar-view" style="display:none;overflow-y:auto;flex:1;padding:6px 8px"></div>
    <!-- Artifacts list -->
    <div id="artifacts-list" class="sidebar-view" style="display:none;overflow-y:auto;flex:1;padding:6px 8px"></div>
    <!-- File browser -->
    <div id="files-view" class="sidebar-view" style="display:none;flex-direction:column;overflow:hidden;flex:1">
      <div id="file-toolbar" style="padding:6px 8px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:4px;flex-shrink:0">
        <button id="file-up-btn" onclick="fileBrowseUp()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary);padding:2px 8px;border-radius:4px;font-size:11px;cursor:pointer;font-family:inherit" title="Up one level">↑</button>
        <div id="file-path-display" style="flex:1;font-size:10px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0"></div>
      </div>
      <div id="file-set-workspace" style="display:none;padding:4px 8px;background:rgba(31,111,235,0.08);border-bottom:1px solid rgba(31,111,235,0.2);flex-shrink:0">
        <button onclick="setWorkspaceHere()" style="width:100%;background:var(--accent-blue);border:none;color:#fff;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:600;cursor:pointer;font-family:inherit">&#x1F4CC; Set as Agent Workspace</button>
      </div>
      <div id="file-list" style="flex:1;overflow-y:auto;padding:4px 6px"></div>
      <div id="file-preview" style="display:none;border-top:1px solid var(--border);background:var(--bg-primary);padding:8px;flex-shrink:0;max-height:180px;overflow-y:auto">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span id="file-preview-name" style="font-size:11px;font-weight:600;color:var(--text-link)"></span>
          <button onclick="document.getElementById('file-preview').style.display='none'" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:12px">✕</button>
        </div>
        <pre id="file-preview-content" style="font-size:10px;line-height:1.4;color:var(--text-secondary);white-space:pre-wrap;word-break:break-all;font-family:var(--font-mono)"></pre>
      </div>
    </div>
    <!-- History view -->
    <div id="history-view" class="sidebar-view" style="display:none;flex-direction:column;overflow:hidden;flex:1">
      <div style="padding:6px 8px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px;flex-shrink:0">
        <span style="font-size:11px;color:var(--text-secondary);flex:1">Recent runs</span>
        <button onclick="loadRunHistory()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:11px">&#x21BB;</button>
        <button onclick="clearRunHistory()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:11px">Clear</button>
      </div>
      <div id="run-list" style="flex:1;overflow-y:auto;padding:4px 6px">
        <div style="color:var(--text-secondary);font-size:11px;padding:8px">No runs yet.</div>
      </div>
    </div>
    <!-- GitHub view -->
    <div id="github-view" class="sidebar-view" style="display:none;flex-direction:column;overflow:hidden;flex:1">
      <div id="gh-connect-prompt" style="padding:12px 10px">
        <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px">&#x1F419; Connect GitHub</div>
        <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;line-height:1.5">Paste a GitHub personal access token to browse and clone repos.</div>
        <input id="gh-token-input" type="password" placeholder="ghp_xxxxxxxxxxxx" style="width:100%;background:var(--bg-primary);border:1px solid var(--border);color:var(--text-primary);padding:6px 8px;border-radius:6px;font-size:11px;font-family:inherit;outline:none;margin-bottom:6px">
        <button onclick="ghConnect()" style="width:100%;background:var(--accent-blue);border:none;color:#fff;padding:5px 0;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit">Connect</button>
        <div style="font-size:10px;color:var(--text-secondary);margin-top:6px;text-align:center">Or set <code style="background:var(--bg-tertiary);padding:1px 4px;border-radius:3px">GITHUB_TOKEN</code> env var</div>
      </div>
      <div id="gh-user-bar" style="display:none;padding:8px 10px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px">
        <img id="gh-avatar" src="" width="24" height="24" style="border-radius:50%;flex-shrink:0">
        <div style="flex:1;min-width:0">
          <div id="gh-username" style="font-size:12px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
          <div id="gh-repo-count" style="font-size:10px;color:var(--text-secondary)"></div>
        </div>
        <button onclick="ghDisconnect()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:11px;flex-shrink:0">&#x2715;</button>
      </div>
      <div id="gh-search-bar" style="display:none;padding:6px 8px;border-bottom:1px solid var(--border)">
        <input id="gh-search" type="text" placeholder="Filter repos&#x2026;" oninput="ghFilterRepos(this.value)" style="width:100%;background:var(--bg-primary);border:1px solid var(--border);color:var(--text-primary);padding:5px 8px;border-radius:6px;font-size:11px;font-family:inherit;outline:none">
      </div>
      <div id="gh-repo-list" style="flex:1;overflow-y:auto;padding:4px 6px"></div>
      <div id="gh-tree-view" style="display:none;flex-direction:column;overflow:hidden;height:100%">
        <div style="padding:6px 8px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px;flex-shrink:0">
          <button onclick="ghShowRepos()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:12px">&#x2190;</button>
          <span id="gh-tree-name" style="font-size:12px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1"></span>
        </div>
        <div id="gh-branch-bar" style="padding:4px 8px;border-bottom:1px solid var(--border);flex-shrink:0">
          <select id="gh-branch-select" onchange="ghLoadTree()" style="width:100%;background:var(--bg-primary);border:1px solid var(--border);color:var(--text-primary);padding:3px 6px;border-radius:4px;font-size:11px;font-family:inherit"></select>
        </div>
        <div id="gh-tree-list" style="flex:1;overflow-y:auto;padding:4px 6px;font-size:11px"></div>
        <div style="padding:8px 10px;border-top:1px solid var(--border);flex-shrink:0;display:flex;flex-direction:column;gap:6px">
          <button onclick="ghClone()" style="width:100%;background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.3);color:#3fb950;padding:5px 0;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit">&#x1F4E5; Clone &amp; set workspace</button>
          <button onclick="ghUseAsTask()" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary);padding:5px 0;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit">Ask about this repo &#x2192;</button>
        </div>
      </div>
    </div>
    <!-- Memory toggle -->
    <div id="sidebar-footer">
      <label class="footer-label" for="memory-toggle">
        <label class="toggle-switch">
          <input type="checkbox" id="memory-toggle" onchange="toggleMemory()" checked>
          <span class="toggle-track"></span>
        </label>
        <span>Cross-chat memory</span>
      </label>
    </div>
  </div>
  <!-- Main Chat Area -->
  <div id="main">
    <div id="chat">
      <div class="config-bar">
        <button class="config-toggle" onclick="toggleConfig()" title="Advanced settings" style="gap:4px;font-size:11px;color:var(--text-secondary)">&#x2699; Advanced</button>
        <div class="config-fields collapsed" id="config-fields">
          <select id="engine" title="Compute engine — who actually runs the task">
            <option value="claude_code">Claude Code</option>
            <option value="opencode">OpenCode</option>
            <option value="codex">Codex</option>
            <option value="openclaw">OpenClaw</option>
            <option value="auto">Auto (Nemotron)</option>
            <option value="direct">Direct LLM</option>
          </select>
          <select id="provider"><option value="anthropic">Anthropic</option><option value="ollama">Ollama</option><option value="openai">OpenAI</option><option value="vllm">vLLM</option></select>
          <select id="model">
            <optgroup label="Anthropic">
              <option value="claude-opus-4-7">claude-opus-4-7 (best)</option>
              <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
              <option value="claude-sonnet-4-20250514">claude-sonnet-4</option>
              <option value="claude-3-opus">claude-3-opus</option>
            </optgroup>
            <optgroup label="Ollama">
              <option value="nemotron-mini">nemotron-mini</option>
              <option value="qwen2.5:7b">qwen2.5:7b</option>
              <option value="deepseek-r1:8b">deepseek-r1:8b</option>
              <option value="gemma3:4b">gemma3:4b</option>
              <option value="gemma4:31b">gemma4:31b</option>
              <option value="llama3.1">llama3.1</option>
              <option value="llama3">llama3</option>
              <option value="mistral">mistral</option>
              <option value="llava">llava (vision)</option>
              <option value="bakllava">bakllava (vision)</option>
            </optgroup>
            <optgroup label="OpenAI">
              <option value="gpt-4o">gpt-4o</option>
              <option value="gpt-4o-mini">gpt-4o-mini</option>
            </optgroup>
            <optgroup label="vLLM">
              <option value="Qwen/Qwen2.5-7B-Instruct">Qwen2.5-7B</option>
              <option value="Qwen/Qwen2.5-32B-Instruct">Qwen2.5-32B</option>
              <option value="meta-llama/Llama-3.1-8B-Instruct">Llama-3.1-8B</option>
              <option value="mistralai/Mistral-7B-Instruct-v0.3">Mistral-7B</option>
            </optgroup>
          </select>
          <div class="model-presets">
            <span class="preset-btn active" data-engine="claude_code" data-provider="anthropic" data-model="claude-opus-4-7" title="Claude Code CLI — full agentic mode" onclick="togglePreset(this)">Claude Code</span>
            <span class="preset-btn" data-engine="opencode" data-provider="anthropic" data-model="claude-sonnet-4-6" title="OpenCode — open-source agentic coding CLI" onclick="togglePreset(this)">OpenCode</span>
            <span class="preset-btn" data-engine="auto" data-provider="anthropic" data-model="claude-sonnet-4-6" title="Nemotron auto-routes to best agent" onclick="togglePreset(this)">Auto</span>
            <span class="preset-btn" data-engine="direct" data-provider="ollama" data-model="nemotron-mini" title="Ollama + nemotron-mini direct" onclick="togglePreset(this)">Nemotron</span>
            <span class="preset-btn" data-engine="direct" data-provider="ollama" data-model="qwen2.5:7b" title="Ollama + qwen2.5:7b direct" onclick="togglePreset(this)">Qwen</span>
            <span class="preset-btn" data-engine="direct" data-provider="ollama" data-model="deepseek-r1:8b" title="Ollama + deepseek-r1:8b direct" onclick="togglePreset(this)">DeepSeek</span>
          </div>
          <input id="api-key" type="password" placeholder="API key" style="width:170px">
          <label><input type="checkbox" id="use-cache" checked> Cache</label>
          <label style="margin-left:4px" title="Allow the agent to search the web in real time"><input type="checkbox" id="allow-web" checked> <span style="color:#58a6ff">🌐 Web</span></label>
          <label style="margin-left:4px"><input type="checkbox" id="prince-mode" title="Ask with web search + citations"> Prince</label>
          <span id="workspace-badge" title="Agent working directory — change via Files tab" style="display:none;font-size:10px;color:var(--accent-green);background:rgba(35,134,54,.12);border:1px solid rgba(35,134,54,.3);padding:2px 8px;border-radius:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;cursor:pointer" onclick="switchSidebar('files');switchTab && document.querySelector('.nav-btn[data-view=files]') && document.querySelector('.nav-btn[data-view=files]').click()">📌 …</span>
          <span id="session-badge" title="Claude Code session active — follow-up messages continue the same conversation. Click to clear." style="display:none;font-size:10px;color:#a371f7;background:rgba(163,113,247,.12);border:1px solid rgba(163,113,247,.3);padding:2px 8px;border-radius:8px;white-space:nowrap;cursor:pointer" onclick="clearClaudeSession()">⛓ session</span>
        </div>
      </div>
      <div class="tab-bar">
        <button class="tab-btn active" onclick="switchTab('chat')">Chat</button>
        <button class="tab-btn" onclick="switchTab('skills')">Skills</button>
      </div>
      <div id="tab-chat" class="tab-content">
        <div id="messages"></div>
        <div id="welcome">
          <h2>What can I help you build?</h2>
          <p>Describe anything — I'll write the code, run it, fix it, and explain what I did.</p>
          <div class="example-tasks">
            <button class="example-btn" onclick="setTask('Build a REST API with authentication and a SQLite database')">Build a REST API</button>
            <button class="example-btn" onclick="setTask('Create a React dashboard with real-time charts')">React Dashboard</button>
            <button class="example-btn" onclick="setTask('Review this codebase and list the top 5 improvements')">Review my code</button>
            <button class="example-btn" onclick="setTask('Write and run unit tests for the main module')">Write tests</button>
            <button class="example-btn" onclick="setTask('Debug this error and explain the root cause')">Debug an error</button>
            <button class="example-btn" onclick="setTask('Refactor this code to be cleaner and more maintainable')">Refactor code</button>
          </div>
          <p style="margin-top:24px;margin-bottom:0;font-size:12px;color:var(--text-secondary);opacity:.7">
            Need enterprise features, integrations, or autonomous scheduling?
            <button onclick="window.location.href='/miles/'" style="background:none;border:none;color:var(--text-link);font-size:12px;cursor:pointer;font-family:inherit;text-decoration:underline;padding:0">Open M.I.L.E.S</button>
          </p>
        </div>
        <div id="spinner"><div class="spinner-icon"></div><span>Agent is working...</span></div>
        <div id="input-area">
          <div id="input-form">
            <textarea id="task-input" rows="1" placeholder="Describe a task for the agent..." disabled></textarea>
            <button class="input-btn" id="img-btn" onclick="document.getElementById('img-input').click()" title="Attach image" disabled>&#x1F5BC;</button>
            <input type="file" id="img-input" accept="image/*" style="display:none" onchange="attachImage(this)">
            <button class="input-btn mic-btn" id="mic-btn" onclick="toggleMic()" title="Voice input" disabled>&#x1F3A4;</button>
            <button id="send-btn" onclick="sendTask()" disabled>Run</button>
            <button id="preview-btn" onclick="runPreview()" title="Preview what the agent would change (free)" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary);padding:8px 12px;font-size:12px;border-radius:var(--radius-sm);cursor:pointer;font-family:inherit;display:none">Preview</button>
            <button id="stop-btn" class="header-btn" style="display:none;background:var(--accent-red);color:#fff;border:none" onclick="cancelTask()">Stop</button>
          </div>
          <div id="input-extras" style="display:flex;gap:6px;margin-top:4px;font-size:10px;color:var(--text-secondary);align-items:center">
            <span id="lang-badge" style="display:none;background:var(--bg-tertiary);padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600"></span>
            <span>Enter to send &middot; Shift+Enter for newline</span>
            <span id="img-name" style="display:none;color:var(--accent-blue)"></span>
            <span id="mic-status" style="display:none;color:var(--accent-orange)">Listening...</span>
            <label style="margin-left:auto;display:flex;align-items:center;gap:4px;cursor:pointer">
              <input type="checkbox" id="tts-toggle" onchange="toggleTts()"> Speak
            </label>
          </div>
          <!-- Auto-suggestions -->
          <div id="suggestions" style="display:none;margin-top:6px;gap:4px;flex-wrap:wrap"></div>
        </div>
      </div>
      <div id="tab-skills" class="tab-content" style="display:none">
        <div id="skills-panel" style="padding:14px 16px;overflow-y:auto;flex:1">

          <!-- Tools -->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-secondary)">Tools <span id="tools-count" style="font-weight:400;opacity:.7"></span></div>
            <button class="example-btn" onclick="refreshSkills()" style="font-size:10px;padding:2px 8px">Refresh</button>
          </div>
          <div id="tools-grid" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
            <span style="color:var(--text-secondary);font-size:12px">Loading…</span>
          </div>
          <div id="tool-detail" style="display:none;background:var(--bg-primary);border:1px solid var(--accent-blue);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
              <span id="tool-detail-name" style="font-weight:700;font-size:13px;color:#58a6ff"></span>
              <button onclick="document.getElementById('tool-detail').style.display='none'" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:14px;line-height:1">✕</button>
            </div>
            <div id="tool-detail-desc" style="color:var(--text-primary);line-height:1.5;margin-bottom:8px"></div>
            <div id="tool-detail-params" style="color:var(--text-secondary)"></div>
            <button id="tool-detail-use" style="margin-top:8px;background:var(--accent-blue);border:none;color:#fff;padding:4px 12px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit">Use this tool →</button>
          </div>

          <!-- Active Agents -->
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-secondary);margin-bottom:10px">Active Agents</div>
          <div id="agents-grid" style="display:flex;flex-direction:column;gap:6px;margin-bottom:18px">
            <span style="color:var(--text-secondary);font-size:12px">Loading…</span>
          </div>

          <!-- Learned Skills -->
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-secondary);margin-bottom:10px">
            Learned Skills <span id="skills-stats" style="font-weight:400;opacity:.7"></span>
          </div>
          <div id="skills-list" style="font-size:12px;color:var(--text-secondary)">Loading…</div>

        </div>
      </div>
    </div>
  </div>
  <!-- Right Panel: Context + Artifacts -->
  <div id="ctx-panel" class="">
    <div id="ctx-tabs" style="display:flex;border-bottom:1px solid var(--border);background:var(--bg-secondary)">
      <button class="ctx-tab active" onclick="switchCtxTab('context')">Context</button>
      <button class="ctx-tab" onclick="switchCtxTab('artifacts')">Artifacts</button>
    </div>
    <div id="ctx-inner" hx-get="/api/context" hx-trigger="every:2s, contextUpdated from:body" hx-swap="innerHTML">
      <div style="color:var(--text-secondary);font-size:13px;padding:8px">Context window info...</div>
    </div>
    <div id="artifacts-inner" style="display:none;padding:10px;overflow-y:auto;flex:1">
      <div style="color:var(--text-secondary);font-size:12px;padding:8px">No artifacts yet. Generated outputs will appear here.</div>
    </div>
  </div>
</div>
<script>
(function() {
'use strict';

let currentSession = null;
let activeTaskId = null;
let currentEventSource = null;
let ctxOpen = true;
let _isRunning = false;
let _configOpen = false;
let _reconnectAttempts = 0;
let _workspace = '';  // current working directory passed to agents
let _fileBrowsePath = '';  // current path in file browser
let _claudeSessionId = '';  // Claude Code session ID for conversation continuity

function saveConfig() {
  try {
    localStorage.setItem('ca_engine', document.getElementById('engine').value);
    localStorage.setItem('ca_provider', document.getElementById('provider').value);
    localStorage.setItem('ca_model', document.getElementById('model').value.toLowerCase());
    localStorage.setItem('ca_api_key', document.getElementById('api-key').value);
    localStorage.setItem('ca_cache', document.getElementById('use-cache').checked ? '1' : '0');
    localStorage.setItem('ca_prince', document.getElementById('prince-mode').checked ? '1' : '0');
    localStorage.setItem('ca_ctx_open', ctxOpen ? '1' : '0');
  } catch(e) {}
}

function loadConfig() {
  try {
    var eg = localStorage.getItem('ca_engine');
    var p = localStorage.getItem('ca_provider');
    var m = localStorage.getItem('ca_model');
    var k = localStorage.getItem('ca_api_key');
    var c = localStorage.getItem('ca_cache');
    var pp = localStorage.getItem('ca_prince');
    var co = localStorage.getItem('ca_ctx_open');
    if (eg) document.getElementById('engine').value = eg;
    if (p) document.getElementById('provider').value = p;
    if (m) document.getElementById('model').value = m.toLowerCase();
    if (k) document.getElementById('api-key').value = k;
    if (c) document.getElementById('use-cache').checked = c === '1';
    if (pp) document.getElementById('prince-mode').checked = pp === '1';
    if (co) ctxOpen = co === '1';
  } catch(e) {}
}

function getRelativeTime(ts) {
  var diff = Date.now() - ts;
  var sec = Math.floor(diff / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return sec + 's ago';
  var min = Math.floor(sec / 60);
  if (min < 60) return min + 'm ago';
  var hr = Math.floor(min / 60);
  if (hr < 24) return hr + 'h ago';
  return new Date(ts).toLocaleDateString();
}

function escapeHtml(str) {
  var d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function scrollToBottom() {
  var msgs = document.getElementById('messages');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function addMessage(role, content) {
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = content;
  msgs.appendChild(div);
  scrollToBottom();
  return div;
}

function createAssistantDiv() {
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = '<div class="msg-label">Assistant</div><div class="msg-content"></div>';
  msgs.appendChild(div);
  scrollToBottom();
  return { container: div, content: div.querySelector('.msg-content') };
}

function addTimestamp(div) {
  var t = document.createElement('div');
  t.className = 'msg-time';
  t.textContent = getRelativeTime(Date.now());
  div.appendChild(t);
}

function showThinking(text) {
  var trimmed = (text || '').trim();
  if (!trimmed) return;
  trimmed = trimmed.slice(0, 600);
  var msgs = document.getElementById('messages');
  var assistants = msgs.querySelectorAll('.msg.assistant');
  var lastAssistant = assistants[assistants.length - 1];
  if (lastAssistant) {
    var existing = lastAssistant.querySelector('.thinking-details');
    if (existing) {
      existing.querySelector('.thinking-text').textContent = trimmed;
      return;
    }
  }
  // Only add a "Planning" move on the first thinking block, not on incremental updates
  showMove('plan', 'Planning', trimmed.slice(0, 120));
  if (lastAssistant) {
    var details = document.createElement('details');
    details.className = 'thinking-details';
    details.open = true;
    details.innerHTML = '<summary>Reasoning</summary><div class="thinking-text">' + escapeHtml(trimmed) + '</div>';
    lastAssistant.appendChild(details);
  } else {
    addMessage('assistant', '<div class="msg-label">Assistant</div><div class="msg-content"></div>' +
      '<details class="thinking-details" open><summary>Reasoning</summary><div class="thinking-text">' + escapeHtml(trimmed) + '</div></details>');
  }
}

function showMove(type, label, description) {
  if (!description) return;
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg move';
  var iconClass = type === 'plan' ? 'plan' : type === 'prompt' ? 'prompt' : type === 'response' ? 'response' : 'tool';
  div.innerHTML = '<div class="move-icon ' + iconClass + '"></div>'
    + '<span class="move-label">' + escapeHtml(label) + '</span>'
    + '<span class="move-text">' + escapeHtml(description.slice(0, 200)) + '</span>';
  msgs.appendChild(div);
  scrollToBottom();
}

function showLLMError(message, iteration) {
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg error-llm';
  div.innerHTML = '<div class="msg-label">LLM Error' + (iteration ? ' (iteration ' + iteration + ')' : '') + '</div>'
    + '<div style="font-size:13px;margin-top:4px">' + escapeHtml(message) + '</div>';
  msgs.appendChild(div);
  scrollToBottom();
}

function showResult(content) {
  if (!content) return;
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg result';
  div.innerHTML = '<div class="msg-label">Result</div><div style="font-size:13px;margin-top:4px">' + escapeHtml(content.slice(0, 500)) + '</div>';
  msgs.appendChild(div);
  addTimestamp(div);
  scrollToBottom();
}

function addCursor(div) {
  var cursor = document.createElement('span');
  cursor.className = 'streaming-cursor';
  div.appendChild(cursor);
  return cursor;
}

function removeCursor(cursor) {
  if (cursor && cursor.parentNode) cursor.parentNode.removeChild(cursor);
}

function createToolPanel(name, args, actionType, toolId) {
  actionType = actionType || 'tool';
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg tool';
  if (toolId) div.setAttribute('data-tool-id', toolId);
  var argStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
  // Trim very long args for display
  if (argStr.length > 2000) argStr = argStr.slice(0, 2000) + '\n… (truncated)';
  var badgeHtml = '<span class="action-badge ' + actionType + '">' + actionType + '</span>';
  div.innerHTML = '<details open><summary><span class="tool-status running">RUN</span> '
    + badgeHtml + ' '
    + escapeHtml(name) + '</summary>'
    + '<div class="tool-body">'
    + '<div class="tool-args">' + escapeHtml(argStr) + '</div>'
    + '<div class="tool-result">Running...</div>'
    + '</div></details>';
  msgs.appendChild(div);
  scrollToBottom();
  return div;
}

function updateToolPanel(div, output, error) {
  var summary = div.querySelector('summary');
  var status = summary ? summary.querySelector('.tool-status') : null;
  var resultDiv = div.querySelector('.tool-result');
  if (status) {
    if (error) {
      status.className = 'tool-status error';
      status.textContent = 'ERR';
    } else {
      status.className = 'tool-status done';
      status.textContent = 'DONE';
    }
  }
  if (resultDiv) {
    if (error) {
      resultDiv.className = 'tool-result error';
      resultDiv.textContent = 'Error: ' + error;
    } else {
      resultDiv.textContent = output && output.trim ? output.trim() : '(no output)';
    }
  }
  scrollToBottom();
}

function sectionHtml(type, body) {
  var icons = { plan: '\u{1F4CB}', thought: '\u{1F4AD}', done: '\u{2705}' };
  if (type === 'plan') {
    return '<div class="section-plan"><div class="section-plan-header">' + (icons.plan || '') + ' Plan</div><div class="section-plan-body">' + body + '</div></div>';
  }
  if (type === 'thought') {
    return '<div class="section-thought"><div class="section-thought-label">' + (icons.thought || '') + ' Thought</div><div class="section-thought-body">' + body + '</div></div>';
  }
  if (type === 'done') {
    return '<div class="section-done"><div class="section-done-icon">' + (icons.done || '') + '</div><div class="section-done-text">' + body + '</div></div>';
  }
  return body;
}

function preprocessContent(raw) {
  var parts = [];
  var buffer = '';
  var lines = raw.split('\n');
  var i = 0;
  var sectionRe = /^#{0,2}\s*(Plan|Thought|Done)\s*[:：]?\s*$/i;

  function flush() {
    if (buffer.trim()) {
      parts.push({ type: 'md', body: buffer.trim() });
    }
    buffer = '';
  }

  function collectSection() {
    var bodyLines = [];
    while (i < lines.length && !sectionRe.test(lines[i])) {
      bodyLines.push(lines[i]);
      i++;
    }
    return bodyLines.join('\n').trim();
  }

  while (i < lines.length) {
    var line = lines[i];
    var m = line.match(sectionRe);
    if (m) {
      var sectionType = m[1].toLowerCase();
      flush();
      i++;
      if (sectionType === 'done') {
        var body = collectSection() || 'Task complete.';
        try { body = marked.parse(body); } catch(e) {}
        parts.push({ type: 'done', body: body });
      } else {
        var body = collectSection();
        if (body) {
          try { body = marked.parse(body); } catch(e) {}
          parts.push({ type: sectionType, body: body });
        }
      }
      continue;
    }
    buffer += line + '\n';
    i++;
  }
  flush();

  var html = '';
  for (var j = 0; j < parts.length; j++) {
    html += sectionHtml(parts[j].type, parts[j].body);
  }
  return html;
}

function renderMarkdown(div) {
  var raw = div.textContent;
  if (!raw || !raw.trim()) { div.innerHTML = ''; return; }
  try {
    div.innerHTML = preprocessContent(raw);
    div.querySelectorAll('pre code').forEach(function(block) {
      try { hljs.highlightElement(block); } catch(e) {}
    });
    div.querySelectorAll('pre').forEach(function(pre) {
      if (pre.querySelector('.copy-btn')) return;
      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'Copy';
      btn.onclick = function() {
        var code = pre.querySelector('code');
        var text = code ? code.textContent : pre.textContent;
        navigator.clipboard.writeText(text).then(function() {
          btn.textContent = 'Copied!';
          setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
        });
      };
      pre.appendChild(btn);
    });
  } catch(e) {
    div.textContent = raw;
  }
}

var _taskStartTime = 0;
var _lastTaskText = '';

function setRunning(running) {
  _isRunning = running;
  document.getElementById('spinner').classList.toggle('active', running);
  document.getElementById('status').textContent = running ? 'Running' : 'Idle';
  document.getElementById('task-input').disabled = running;
  var sendBtn = document.getElementById('send-btn');
  var stopBtn = document.getElementById('stop-btn');
  sendBtn.disabled = running;
  sendBtn.style.display = running ? 'none' : '';
  stopBtn.style.display = running ? '' : 'none';
  if (running) {
    stopBtn.onclick = cancelTask;
    _taskStartTime = Date.now();
    _lastTaskText = (document.getElementById('task-input').value || '').substring(0,80);
  } else {
    sendBtn.onclick = sendTask;
    document.getElementById('task-input').focus();
    // Fire browser notification if tab is not focused and task took > 5s
    var elapsed = Date.now() - _taskStartTime;
    if (elapsed > 5000 && document.hidden) { _notifyDone(_lastTaskText); }
    // Refresh run history if open
    var histView = document.getElementById('history-view');
    if (histView && histView.style.display !== 'none') { loadRunHistory(); }
  }
}

function _notifyDone(taskText) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Orchestra — Task complete', {
        body: taskText || 'Your agent finished.',
        icon: '/icon.svg',
        tag: 'orchestra-done',
      });
    }
  } catch(e) {}
}

function cancelTask() {
  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  if (activeTaskId) {
    fetch('/api/chat/' + activeTaskId + '/cancel', { method: 'POST' }).catch(function(){});
  }
    showToast('Task cancelled', 'warning');
  cleanupAfterTask();
}

function cleanupAfterTask() {
  activeTaskId = null;
  _reconnectAttempts = 0;
  setRunning(false);
  document.getElementById('stop-btn').style.display = 'none';
  if (ctxOpen) {
    htmx.trigger('body', 'contextUpdated');
  }
  htmx.ajax('GET', '/api/sessions', '#session-list');
  loadArtifacts();
}

async function sendTask() {
  var input = document.getElementById('task-input');
  var task = input.value.trim();
  if (!task || _isRunning) return;
  var princeMode = document.getElementById('prince-mode') && document.getElementById('prince-mode').checked;
  if (princeMode) { askPrince(); return; }
  document.getElementById('welcome').classList.add('hidden');
  var imgHtml = '';
  if (_attachedImage) {
    imgHtml = '<div style="margin-top:6px"><img src="' + _attachedImage + '" style="max-width:200px;max-height:150px;border-radius:6px;border:1px solid var(--border)"></div>';
  }
  var userMsg = '<div class="msg-label">You</div>' + escapeHtml(task) + imgHtml + '<div class="msg-time">' + getRelativeTime(Date.now()) + '</div>';
  addMessage('user', userMsg);
  input.value = '';
  adjustTextarea();
  setRunning(true);
  saveConfig();
  var assistantState = { div: null, content: '', cursor: null };
  try {
    var engine = document.getElementById('engine').value;
    var apiPath, body;
    var allowWeb = document.getElementById('allow-web').checked;
    if (engine === 'direct') {
      apiPath = '/api/chat';
      body = JSON.stringify({
        task: task + (_attachedImage ? ' [Image attached]' : ''),
        session_id: currentSession || '',
        provider: document.getElementById('provider').value,
        model: document.getElementById('model').value,
        api_key: document.getElementById('api-key').value,
        use_cache: document.getElementById('use-cache').checked,
        allow_web: allowWeb,
      });
    } else {
      apiPath = '/api/chat/agentic';
      body = JSON.stringify({
        task: task + (_attachedImage ? ' [Image attached]' : ''),
        session_id: currentSession || '',
        engine: engine,
        workspace: _workspace || '',
        claude_session_id: _claudeSessionId || '',
        allow_web: allowWeb,
      });
    }
    _attachedImage = null;
    document.getElementById('img-name').style.display = 'none';
    var resp = await fetch(apiPath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
    });
    if (!resp.ok) {
      var errData;
      try { errData = await resp.json(); } catch(e) { errData = {}; }
      showToast(errData.detail || resp.statusText || 'Request failed', 'error');
      cleanupAfterTask();
      return;
    }
    var data = await resp.json();
    var taskId = data.task_id;
    activeTaskId = taskId;
    if (data.session_id) { currentSession = data.session_id; }
    var es = new EventSource('/api/chat/' + taskId + '/stream');
    currentEventSource = es;
    es.onmessage = function(event) {
      var msg;
      try { msg = JSON.parse(event.data); } catch(e) { return; }
      switch (msg.type) {
        case 'task_start':
          addMessage('system', '<div class="msg-label">Task</div><div style="font-size:14px;font-weight:600;margin-top:2px">' + escapeHtml((msg.data && msg.data.task || '').slice(0, 120)) + '</div>');
          break;
        case 'agent_init':
          var d = msg.data || {};
          var agentLabel = d.display_name || d.agent || d.engine || 'Agent';
          var modelBadge = d.model ? ' <span style="background:rgba(88,166,255,.15);color:#58a6ff;padding:1px 6px;border-radius:4px;font-size:10px">' + escapeHtml(d.model) + '</span>' : '';
          var pmBadge = d.permission_mode ? ' <span style="background:rgba(35,134,54,.15);color:#3fb950;padding:1px 6px;border-radius:4px;font-size:10px">' + escapeHtml(d.permission_mode) + '</span>' : '';
          var toolsBadge = d.tools_count ? ' <span style="color:var(--text-secondary);font-size:10px">' + d.tools_count + ' tools</span>' : '';
          addMessage('system', '<div class="msg-label">' + escapeHtml(agentLabel) + '</div><div style="margin-top:2px;display:flex;align-items:center;gap:4px;flex-wrap:wrap">' + modelBadge + pmBadge + toolsBadge + '</div>');
          break;
        case 'thinking':
          showThinking(msg.data);
          htmx.trigger('body', 'contextUpdated');
          break;
        case 'token':
          if (!assistantState.div) { assistantState.div = createAssistantDiv(); }
          assistantState.content += msg.data;
          assistantState.div.content.textContent = assistantState.content;
          if (!assistantState.cursor) { assistantState.cursor = addCursor(assistantState.div.content); }
          else { assistantState.div.content.appendChild(assistantState.cursor); }
          scrollToBottom();
          break;
        case 'move':
          var md = msg.data;
          var moveLabel = md.type === 'plan' ? 'Plan' : md.type === 'prompt' ? 'Prompt' : md.type === 'response' ? 'Response' : md.type && md.type.indexOf('tool:') === 0 ? md.tool || 'Action' : 'Move';
          showMove(md.type, moveLabel, md.description);
          break;
        case 'tool_call':
          if (assistantState.cursor) { removeCursor(assistantState.cursor); assistantState.cursor = null; }
          createToolPanel(msg.data.name, msg.data.arguments, msg.data.action_type || 'tool', msg.data.tool_id || '');
          fetch('/api/context/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({content: 'Tool: ' + msg.data.name, tier: 'important', source: msg.data.name}) }).then(function() { htmx.trigger('body', 'contextUpdated'); }).catch(function(){});
          break;
        case 'tool_result':
          // Match by tool_id first, fall back to last panel
          var toolPanel = null;
          if (msg.data.tool_id) {
            toolPanel = document.querySelector('.msg.tool[data-tool-id="' + msg.data.tool_id + '"]');
          }
          if (!toolPanel) {
            var panels = document.querySelectorAll('.msg.tool');
            toolPanel = panels[panels.length - 1] || null;
          }
          if (toolPanel) { updateToolPanel(toolPanel, msg.data.output, msg.data.error); }
          fetch('/api/context/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({content: (msg.data.output || '(no output)').slice(0, 200), tier: msg.data.error ? 'critical' : 'normal', source: 'tool_result'}) }).then(function() { htmx.trigger('body', 'contextUpdated'); }).catch(function(){});
          break;
        case 'error':
          addMessage('error', '<div class="msg-label">Error</div>' + escapeHtml(msg.data.message));
          htmx.trigger('body', 'contextUpdated');
          break;
        case 'error_llm':
          showLLMError(msg.data.message, msg.data.iteration);
          htmx.trigger('body', 'contextUpdated');
          break;
        case 'result':
          showResult(msg.data.content);
          htmx.trigger('body', 'contextUpdated');
          break;
        case 'done':
          // Capture Claude Code session ID for conversation continuity
          if (msg.data && msg.data.claude_session_id) {
            _claudeSessionId = msg.data.claude_session_id;
            updateSessionBadge();
          }
          if (assistantState.div) {
            removeCursor(assistantState.cursor);
            renderMarkdown(assistantState.div.content);
            // Cost + turns badge from Claude Code metadata
            if (msg.data && (msg.data.cost_usd || msg.data.turns)) {
              var meta = document.createElement('div');
              meta.className = 'msg-time';
              var parts = [];
              if (msg.data.cost_usd) parts.push('$' + msg.data.cost_usd.toFixed(4));
              if (msg.data.turns) parts.push(msg.data.turns + ' turn' + (msg.data.turns === 1 ? '' : 's'));
              if (msg.data.agent && msg.data.agent !== 'claude_code') parts.push(msg.data.agent);
              meta.textContent = parts.join(' · ');
              assistantState.div.container.appendChild(meta);
            } else {
              addTimestamp(assistantState.div.container);
            }
            speakText(assistantState.content);
          } else if (msg.data && msg.data.result) {
            showResult(msg.data.result);
            speakText(msg.data.result);
          }
          es.close();
          currentEventSource = null;
          cleanupAfterTask();
          break;
      }
    };
    es.onerror = function() {
      if (es.readyState === EventSource.CLOSED) {
        es.close();
        currentEventSource = null;
        if (activeTaskId && _reconnectAttempts < 3) { _reconnectAttempts++; return; }
        if (activeTaskId) cleanupAfterTask();
      }
    };
  } catch (err) {
    addMessage('error', '<div class="msg-label">Error</div>' + escapeHtml(err.message));
    cleanupAfterTask();
  }
}

function adjustTextarea() {
  var ta = document.getElementById('task-input');
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 300) + 'px';
}

function togglePreset(btn) {
  var isActive = btn.classList.contains('active');
  document.querySelectorAll('.preset-btn').forEach(function(b) { b.classList.remove('active'); });
  if (!isActive) {
    btn.classList.add('active');
    var eng = btn.getAttribute('data-engine');
    if (eng) document.getElementById('engine').value = eng;
    document.getElementById('provider').value = btn.getAttribute('data-provider');
    filterModelByProvider(document.getElementById('provider').value);
    document.getElementById('model').value = btn.getAttribute('data-model');
  } else {
    document.getElementById('engine').value = 'claude_code';
    document.getElementById('provider').value = 'anthropic';
    filterModelByProvider('anthropic');
    document.getElementById('model').value = 'claude-opus-4-7';
  }
  saveConfig();
  syncPreset();
}

function syncPreset() {
  var engine = document.getElementById('engine').value;
  var provider = document.getElementById('provider').value;
  var model = document.getElementById('model').value;
  document.querySelectorAll('.preset-btn').forEach(function(b) {
    var be = b.getAttribute('data-engine') || 'direct';
    var p = b.getAttribute('data-provider');
    var m = b.getAttribute('data-model');
    if (be === engine && p === provider && m === model) {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });
}

function setTask(text) {
  document.getElementById('task-input').value = text;
  adjustTextarea();
  document.getElementById('task-input').focus();
  sendTask();
}

window.showWeather = async function showWeather() {
  document.getElementById('welcome').classList.add('hidden');
  var city = prompt('Enter city name:', 'New York');
  if (!city) return;
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#58a6ff">Weather</div><div class="msg-content"><em>Fetching weather for ' + escapeHtml(city) + '...</em></div>');
  var contentDiv = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/weather?location=' + encodeURIComponent(city) + '&units=celsius');
    if (!r.ok) { var e = await r.json(); contentDiv.textContent = 'Error: ' + (e.detail || r.statusText); return; }
    var d = await r.json();
    var cur = d.current;
    var html = '<strong>' + escapeHtml(d.location) + '</strong><br>';
    html += '<span style="font-size:28px;font-weight:700;color:#58a6ff">' + cur.temperature + cur.units.temp + '</span>';
    html += '  <span style="color:#8b949e">' + escapeHtml(cur.condition) + '</span><br>';
    html += '<span style="color:#8b949e;font-size:12px">Wind: ' + cur.windspeed + ' ' + cur.units.wind + '</span><br><br>';
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap">';
    d.forecast.forEach(function(f) {
      html += '<div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;padding:8px 12px;min-width:90px">';
      html += '<div style="font-size:11px;color:#8b949e">' + f.date + '</div>';
      html += '<div style="font-weight:600">' + f.high + '/' + f.low + cur.units.temp + '</div>';
      html += '<div style="font-size:11px;color:#8b949e">' + escapeHtml(f.condition) + '</div>';
      if (f.precipitation_mm) html += '<div style="font-size:11px;color:#58a6ff">Rain ' + f.precipitation_mm + 'mm</div>';
      html += '</div>';
    });
    html += '</div>';
    contentDiv.innerHTML = html;
  } catch(e) { contentDiv.textContent = 'Error: ' + e.message; }
}

window.showNews = async function showNews() {
  document.getElementById('welcome').classList.add('hidden');
  var topic = prompt('Topic (leave empty for top headlines):', '');
  var label = topic ? 'News: ' + topic : 'Top Headlines';
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#3fb950">News</div><div class="msg-content"><em>Fetching headlines...</em></div>');
  var contentDiv = msgDiv.querySelector('.msg-content');
  try {
    var url = '/api/news?count=8' + (topic ? '&query=' + encodeURIComponent(topic) : '');
    var r = await fetch(url);
    if (!r.ok) { var e = await r.json(); contentDiv.textContent = 'Error: ' + (e.detail || r.statusText); return; }
    var d = await r.json();
    var html = '<strong>' + escapeHtml(label) + '</strong><br><br>';
    d.articles.forEach(function(a, i) {
      html += '<div style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--border)">';
      html += '<a href="' + escapeHtml(a.link) + '" target="_blank" rel="noopener" style="color:var(--text-primary);text-decoration:none;font-weight:600;line-height:1.4">' + escapeHtml(a.title) + '</a>';
      if (a.source) html += ' <span style="font-size:10px;color:#8b949e;background:var(--bg-tertiary);padding:1px 5px;border-radius:3px">' + escapeHtml(a.source) + '</span>';
      if (a.published) html += '<div style="font-size:11px;color:#8b949e;margin-top:2px">' + escapeHtml(a.published) + '</div>';
      if (a.summary) html += '<div style="font-size:12px;color:#8b949e;margin-top:3px">' + escapeHtml(a.summary) + '</div>';
      html += '</div>';
    });
    contentDiv.innerHTML = html;
  } catch(e) { contentDiv.textContent = 'Error: ' + e.message; }
}

function toggleLivePanel() {
  var p = document.getElementById('live-panel');
  p.style.display = p.style.display === 'flex' ? 'none' : 'flex';
}
function closeLivePanel() {
  document.getElementById('live-panel').style.display = 'none';
}
document.addEventListener('click', function(e) {
  if (!document.getElementById('live-data-wrap').contains(e.target)) closeLivePanel();
});
window.toggleLivePanel = toggleLivePanel;
window.closeLivePanel = closeLivePanel;

window.showCrypto = async function showCrypto() {
  document.getElementById('welcome').classList.add('hidden');
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#f0883e">Crypto</div><div class="msg-content"><em>Fetching prices...</em></div>');
  var cd = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/crypto?count=10&currency=usd');
    if (!r.ok) { cd.textContent = 'Error: ' + (await r.json()).detail; return; }
    var d = await r.json();
    var html = '<strong>Top Crypto — USD</strong><br><br><div style="display:flex;flex-direction:column;gap:6px">';
    d.coins.forEach(function(c) {
      var chg = (c.price_change_percentage_24h || 0).toFixed(2);
      var color = chg >= 0 ? '#3fb950' : '#f85149';
      var arrow = chg >= 0 ? '▲' : '▼';
      html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 10px;background:var(--bg-tertiary);border-radius:6px">'
        + '<span style="font-weight:700;min-width:50px">' + escapeHtml(c.symbol.toUpperCase()) + '</span>'
        + '<span style="flex:1;color:#8b949e;font-size:12px">' + escapeHtml(c.name) + '</span>'
        + '<span style="font-weight:600">$' + (c.current_price >= 1 ? c.current_price.toLocaleString() : c.current_price.toFixed(6)) + '</span>'
        + '<span style="color:' + color + ';font-size:12px;min-width:60px;text-align:right">' + arrow + ' ' + Math.abs(chg) + '%</span>'
        + '</div>';
    });
    html += '</div>';
    cd.innerHTML = html;
  } catch(e) { cd.textContent = 'Error: ' + e.message; }
};

window.showCurrency = async function showCurrency() {
  document.getElementById('welcome').classList.add('hidden');
  var base = prompt('Base currency:', 'USD');
  if (!base) return;
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#d29922">Currency</div><div class="msg-content"><em>Fetching rates...</em></div>');
  var cd = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/currency?base=' + encodeURIComponent(base.toUpperCase()));
    if (!r.ok) { cd.textContent = 'Error: ' + (await r.json()).detail; return; }
    var d = await r.json();
    var html = '<strong>1 ' + escapeHtml(d.base) + ' =</strong><br><br>';
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px">';
    Object.entries(d.rates).forEach(function(kv) {
      html += '<div style="background:var(--bg-tertiary);border-radius:6px;padding:6px 10px">'
        + '<span style="font-weight:700;color:#58a6ff">' + escapeHtml(kv[0]) + '</span>'
        + '<span style="float:right;font-size:13px">' + Number(kv[1]).toFixed(4) + '</span></div>';
    });
    html += '</div>';
    if (d.updated) html += '<div style="font-size:11px;color:#8b949e;margin-top:8px">' + escapeHtml(d.updated) + '</div>';
    cd.innerHTML = html;
  } catch(e) { cd.textContent = 'Error: ' + e.message; }
};

window.showWikipedia = async function showWikipedia() {
  document.getElementById('welcome').classList.add('hidden');
  var topic = prompt('Search Wikipedia:', '');
  if (!topic) return;
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#58a6ff">Wikipedia</div><div class="msg-content"><em>Looking up "' + escapeHtml(topic) + '"...</em></div>');
  var cd = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/wikipedia?topic=' + encodeURIComponent(topic) + '&sentences=6');
    if (!r.ok) { cd.textContent = 'Error: ' + (await r.json()).detail; return; }
    var d = await r.json();
    var html = '<strong>' + escapeHtml(d.title) + '</strong>';
    if (d.description) html += ' <span style="color:#8b949e;font-size:12px">— ' + escapeHtml(d.description) + '</span>';
    if (d.thumbnail) html += '<br><img src="' + escapeHtml(d.thumbnail) + '" style="max-width:160px;border-radius:6px;margin:8px 0;float:right;margin-left:12px">';
    html += '<br><br>' + escapeHtml(d.summary);
    html += '<div style="clear:both"></div>';
    if (d.url) html += '<br><a href="' + escapeHtml(d.url) + '" target="_blank" rel="noopener" style="color:#58a6ff;font-size:12px">Read full article →</a>';
    cd.innerHTML = html;
  } catch(e) { cd.textContent = 'Error: ' + e.message; }
};

window.showGitHub = async function showGitHub() {
  document.getElementById('welcome').classList.add('hidden');
  var q = prompt('Search GitHub repos:', '');
  if (!q) return;
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#8b949e">GitHub</div><div class="msg-content"><em>Searching repos...</em></div>');
  var cd = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/github/search?q=' + encodeURIComponent(q) + '&count=8');
    if (!r.ok) { cd.textContent = 'Error: ' + (await r.json()).detail; return; }
    var d = await r.json();
    var html = '<strong>GitHub: "' + escapeHtml(d.query) + '"</strong> <span style="color:#8b949e;font-size:12px">(' + d.total.toLocaleString() + ' results)</span><br><br>';
    d.repos.forEach(function(repo) {
      html += '<div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
        + '<a href="' + escapeHtml(repo.url) + '" target="_blank" rel="noopener" style="font-weight:600;color:var(--text-primary);text-decoration:none">' + escapeHtml(repo.name) + '</a>';
      if (repo.language) html += ' <span style="font-size:10px;color:#8b949e;background:var(--bg-tertiary);padding:1px 5px;border-radius:3px">' + escapeHtml(repo.language) + '</span>';
      html += ' <span style="color:#d29922;font-size:12px">★ ' + repo.stars.toLocaleString() + '</span>';
      if (repo.description) html += '<div style="font-size:12px;color:#8b949e;margin-top:3px">' + escapeHtml(repo.description) + '</div>';
      html += '</div>';
    });
    cd.innerHTML = html;
  } catch(e) { cd.textContent = 'Error: ' + e.message; }
};

window.showNASA = async function showNASA() {
  document.getElementById('welcome').classList.add('hidden');
  var msgDiv = addMessage('assistant', '<div class="msg-label" style="color:#79c0ff">NASA APOD</div><div class="msg-content"><em>Fetching today\'s astronomy picture...</em></div>');
  var cd = msgDiv.querySelector('.msg-content');
  try {
    var r = await fetch('/api/nasa/apod');
    if (!r.ok) { cd.textContent = 'Error: ' + (await r.json()).detail; return; }
    var d = await r.json();
    var img = d.hdurl || d.url || '';
    var html = '<strong>' + escapeHtml(d.title) + '</strong> <span style="color:#8b949e;font-size:12px">' + escapeHtml(d.date) + '</span><br>';
    if (d.copyright) html += '<span style="font-size:11px;color:#8b949e">© ' + escapeHtml(d.copyright.trim()) + '</span><br>';
    if (img && (d.media_type === 'image' || !d.media_type)) {
      html += '<br><img src="' + escapeHtml(img) + '" style="max-width:100%;border-radius:8px;margin:8px 0" loading="lazy"><br>';
    }
    html += '<div style="font-size:13px;color:#8b949e;line-height:1.6;margin-top:6px">' + escapeHtml((d.explanation || '').slice(0, 500)) + '…</div>';
    if (img) html += '<br><a href="' + escapeHtml(img) + '" target="_blank" rel="noopener" style="color:#79c0ff;font-size:12px">View full image →</a>';
    cd.innerHTML = html;
  } catch(e) { cd.textContent = 'Error: ' + e.message; }
};

function askPrince() {
  var input = document.getElementById('task-input');
  var question = input.value.trim();
  if (!question || _isRunning) return;
  document.getElementById('welcome').classList.add('hidden');
  var userHtml = '<div class="msg-label">You</div><div style="font-weight:500;margin-top:2px">' + escapeHtml(question) + '</div><div class="msg-time">' + getRelativeTime(Date.now()) + '</div>';
  addMessage('user', userHtml);
  input.value = '';
  adjustTextarea();
  setRunning(true);
  var msgDiv = addMessage('assistant', '<div class="msg-label">Prince</div><div class="msg-content"><em>Searching...</em></div>');
  var contentDiv = msgDiv.querySelector('.msg-content');
  fetch('/api/prince', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: question, search_query: question}),
  }).then(function(r) { return r.json(); }).then(function(result) {
    try {
      html = marked.parse(result.answer || '');
      contentDiv.innerHTML = html;
      contentDiv.querySelectorAll('pre code').forEach(function(b) { hljs.highlightElement(b); });
      contentDiv.querySelectorAll('pre').forEach(function(pre) {
        var btn = document.createElement('button');
        btn.className = 'copy-btn';
        btn.textContent = 'Copy';
        btn.onclick = function() {
          var code = pre.querySelector('code');
          var text = code ? code.textContent : pre.textContent;
          navigator.clipboard.writeText(text);
          btn.textContent = 'Copied!';
          setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
        };
        pre.appendChild(btn);
      });
      contentDiv.innerHTML = contentDiv.innerHTML.replace(/\[(\d+)\]/g, '<sup class="citation" data-id="$1">[$1]</sup>');
    } catch(e) { contentDiv.innerHTML = result.answer || ''; }
    if (result.sources && result.sources.length) {
      var srcHtml = '<div class="sources-section"><div class="sources-title">Sources</div><div class="sources-list">';
      result.sources.forEach(function(s) {
        var domain = '?';
        try { domain = new URL(s.url).hostname; } catch(e) {}
        srcHtml += '<a class="source-card" href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener">'
          + '<span class="source-num">' + s.id + '</span>'
          + '<span class="source-body">'
          + '<span class="source-title">' + escapeHtml((s.title||'').slice(0, 60)) + '</span>'
          + '<span class="source-url">' + escapeHtml(domain) + '</span>'
          + '</span></a>';
      });
      srcHtml += '</div></div>';
      msgDiv.insertAdjacentHTML('beforeend', srcHtml);
    }
    addTimestamp(msgDiv);
    setRunning(false);
    scrollToBottom();
  }).catch(function(err) {
    contentDiv.innerHTML = '<span style="color:var(--msg-error-text)">Error: ' + escapeHtml(err.message) + '</span>';
    setRunning(false);
  });
}

function newSession() {
  if (_isRunning) return;
  currentSession = null;
  _claudeSessionId = '';
  updateSessionBadge();
  document.getElementById('messages').innerHTML = '';
  document.getElementById('welcome').classList.remove('hidden');
  document.querySelectorAll('.session-item').forEach(function(e) { e.classList.remove('active'); });
  document.getElementById('task-input').value = '';
  document.getElementById('img-name').style.display = 'none';
  _attachedImage = null;
  adjustTextarea();
  document.getElementById('task-input').focus();
  if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
  activeTaskId = null;
}

// ── Sidebar Navigation ──────────────────────────────────
function switchSidebar(view) {
  document.querySelectorAll('.nav-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('.sidebar-view').forEach(function(v) { v.classList.remove('active'); v.style.display = 'none'; });
  var btn = document.querySelector('.nav-btn[data-view="' + view + '"]');
  if (btn) btn.classList.add('active');
  var title = document.getElementById('sidebar-title');
  if (title) title.textContent = view === 'files' ? 'Files' : view.charAt(0).toUpperCase() + view.slice(1);

  if (view === 'files') {
    var el = document.getElementById('files-view');
    if (el) { el.classList.add('active'); el.style.display = 'flex'; }
    if (!_fileBrowsePath) browseFiles('');
    return;
  }

  if (view === 'history') {
    var el = document.getElementById('history-view');
    if (el) { el.classList.add('active'); el.style.display = 'flex'; }
    if (title) title.textContent = 'History';
    loadRunHistory();
    return;
  }

  if (view === 'github') {
    var el = document.getElementById('github-view');
    if (el) { el.classList.add('active'); el.style.display = 'flex'; }
    if (title) title.textContent = 'GitHub';
    // Auto-load status if token already set
    if (_ghToken || localStorage.getItem('gh_token')) {
      if (!_ghToken) _ghToken = localStorage.getItem('gh_token') || '';
      ghLoadStatus();
    }
    return;
  }

  var el = document.getElementById(view === 'sessions' ? 'session-list' : view + '-list');
  if (el) { el.classList.add('active'); el.style.display = 'flex'; }
  if (view === 'spaces') loadSpaces();
  if (view === 'artifacts') loadArtifacts();
}

function loadSpaces() {
  fetch('/api/spaces').then(function(r) { return r.json(); }).then(function(data) {
    var list = document.getElementById('spaces-list');
    if (!data.spaces || data.spaces.length === 0) {
      list.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:8px">No spaces yet. <a href="#" style="color:var(--text-link)" onclick="createSpace()">Create one</a></div>';
      return;
    }
    var html = '';
    data.spaces.forEach(function(s) {
      html += '<div class="session-item" onclick="openSpace(\'' + s.id + '\')">'
        + '<div class="task">' + s.name + '</div>'
        + '<div class="date">' + (s.description || '') + ' &middot; ' + s.session_count + ' chats</div>'
        + '</div>';
    });
    list.innerHTML = html;
  });
}

function createSpace() {
  var name = prompt('Space name:');
  if (!name) return;
  fetch('/api/spaces', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name: name, description: ''}) })
    .then(function(r) { return r.json(); })
    .then(function() { loadSpaces(); });
}

function openSpace(id) {
  // Load sessions filtered by space
  currentSession = null;
  document.getElementById('welcome').classList.add('hidden');
  document.getElementById('messages').innerHTML = '';
  document.getElementById('task-input').focus();
}

function loadArtifacts() {
  fetch('/api/artifacts').then(function(r) { return r.json(); }).then(function(data) {
    var list = document.getElementById('artifacts-list');
    if (!data.artifacts || data.artifacts.length === 0) {
      list.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:8px">No artifacts yet.</div>';
      return;
    }
    var html = '';
    data.artifacts.forEach(function(a) {
      html += '<div class="session-item" onclick="viewArtifact(\'' + a.id + '\')">'
        + '<div class="task">' + a.title + '</div>'
        + '<div class="date">' + a.type + ' &middot; ' + (a.created_at || '').slice(0,10) + '</div>'
        + '</div>';
    });
    list.innerHTML = html;
  });
}

function viewArtifact(id) {
  fetch('/api/artifacts/' + id).then(function(r) { return r.json(); }).then(function(a) {
    var msg = '<div class="msg assistant"><div class="msg-label">Artifact: ' + a.title + '</div><div class="msg-content">';
    if (a.type === 'code') msg += '<pre><code>' + escapeHtml(a.content) + '</code></pre>';
    else msg += '<p>' + escapeHtml(a.content) + '</p>';
    msg += '</div></div>';
    document.getElementById('messages').innerHTML = msg;
    document.getElementById('welcome').classList.add('hidden');
  });
}

function switchCtxTab(tab) {
  document.querySelectorAll('.ctx-tab').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('#ctx-panel > div:not(#ctx-tabs)').forEach(function(p) { p.style.display = 'none'; });
  var btn = document.querySelector('.ctx-tab[onclick*="' + tab + '"]');
  if (btn) btn.classList.add('active');
  var el = document.getElementById(tab === 'context' ? 'ctx-inner' : 'artifacts-inner');
  if (el) el.style.display = 'flex';
}

function searchHistory(query) {
  if (!query) { document.getElementById('session-list').innerHTML = '<div style="color:var(--text-secondary);font-size:13px;padding:8px">Search cleared.</div>'; return; }
  htmx.ajax('GET', '/api/sessions?q=' + encodeURIComponent(query), '#session-list');
}

function toggleMemory() {
  var enabled = document.getElementById('memory-toggle').checked;
  try { localStorage.setItem('ca_memory', enabled ? '1' : '0'); } catch(e) {}
  fetch('/api/memory/toggle', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({enabled: enabled}) }).catch(function(){});
}

function deleteSession(sid) {
  fetch('/api/sessions/' + sid, { method: 'DELETE' }).then(function() { htmx.ajax('GET', '/api/sessions', '#session-list'); }).catch(function(){});
}

// === JARVIS MODE ===
var _jarvisActive = false;
var _recognition = null;
var _listening = false;
var _attachedImage = null;
var _ttsEnabled = false;

function toggleJarvis() {
  _jarvisActive = !_jarvisActive;
  document.body.classList.toggle('jarvis-active', _jarvisActive);
  document.getElementById('jarvis-btn').style.background = _jarvisActive ? 'linear-gradient(90deg,#1f6feb,#238636)' : '';
  document.getElementById('jarvis-btn').style.color = _jarvisActive ? '#fff' : '';
  document.getElementById('task-input').disabled = false;
  document.getElementById('send-btn').disabled = false;
  document.getElementById('img-btn').disabled = false;
  document.getElementById('mic-btn').disabled = false;
  if (_jarvisActive) document.getElementById('task-input').focus();
  try { localStorage.setItem('ca_jarvis', _jarvisActive ? '1' : '0'); } catch(e) {}
}

function attachImage(input) {
  var file = input.files && input.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function(e) {
    _attachedImage = e.target.result;
    var nameEl = document.getElementById('img-name');
    nameEl.textContent = '\u{1F5BC} ' + file.name;
    nameEl.style.display = 'inline';
  };
  reader.readAsDataURL(file);
}

var _browserInfo = (function() {
  var ua = navigator.userAgent;
  var isChrome = ua.indexOf('Chrome') > -1 && ua.indexOf('Edg') === -1 && ua.indexOf('OPR') === -1;
  var isEdge = ua.indexOf('Edg') > -1;
  var isSafari = ua.indexOf('Safari') > -1 && !isChrome && !isEdge;
  var isFirefox = ua.indexOf('Firefox') > -1;
  var isMobile = /iPhone|iPad|iPod|Android/i.test(ua);
  return { chrome: isChrome, edge: isEdge, safari: isSafari, firefox: isFirefox, mobile: isMobile,
           hasSpeech: 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window,
           name: isEdge ? 'Edge' : isChrome ? 'Chrome' : isSafari ? 'Safari' : isFirefox ? 'Firefox' : 'Unknown' };
})();

function toggleMic() {
  if (!_browserInfo.hasSpeech) {
    var hint = _browserInfo.mobile
      ? 'Speech recognition requires Chrome or Edge on this device.'
      : 'Speech recognition requires Chrome or Edge. Safari and Firefox are not supported.';
    addMessage('error', '<div class="msg-label">Error</div>' + hint);
    var btn = document.getElementById('mic-btn');
    btn.title = hint;
    btn.style.opacity = '0.3';
    return;
  }
  if (_listening) { stopMic(); return; }
  startMic();
}

function startMic() {
  var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  _recognition = new SpeechRecognition();
  _recognition.continuous = false;
  _recognition.interimResults = true;
  _recognition.lang = 'en-US';
  var finalText = '';
  document.getElementById('mic-status').style.display = 'inline';
  document.getElementById('mic-btn').classList.add('listening');
  _listening = true;
  _recognition.onresult = function(event) {
    var interim = '';
    for (var i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else interim += event.results[i][0].transcript;
    }
    document.getElementById('mic-status').textContent = finalText ? '\u201C' + finalText + '\u201D' : 'Listening...';
    if (finalText) {
      document.getElementById('task-input').value = finalText;
      adjustTextarea();
    }
  };
  _recognition.onerror = function() { stopMic(); };
  _recognition.onend = function() { if (!finalText) stopMic(); };
  _recognition.start();
}

function stopMic() {
  if (_recognition) { try { _recognition.stop(); } catch(e) {} _recognition = null; }
  _listening = false;
  document.getElementById('mic-status').style.display = 'none';
  document.getElementById('mic-btn').classList.remove('listening');
}

function toggleTts() {
  _ttsEnabled = document.getElementById('tts-toggle').checked;
  try { localStorage.setItem('ca_tts', _ttsEnabled ? '1' : '0'); } catch(e) {}
}

async function showToast(message, type) {
  type = type || 'info';
  var container = document.getElementById('toast-container');
  var toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function() {
    toast.style.animation = 'toastOut 0.3s ease-out forwards';
    setTimeout(function() { toast.remove(); }, 300);
  }, 4000);
}

async function detectLanguage() {
  var badge = document.getElementById('lang-badge');
  var langMap = [
    {file: 'Cargo.toml', label: '\u{1F980} Rust'},
    {file: 'package.json', label: '\u{1F596} TypeScript'},
    {file: 'pyproject.toml', label: '\u{1F40D} Python'},
    {file: 'mojoproject.toml', label: '\u{1F525} Mojo'},
  ];
  for (var item of langMap) {
    try {
      var r = await fetch('/' + item.file, {method: 'HEAD'});
      if (r.status === 200) { badge.textContent = item.label; badge.style.display = 'inline'; return; }
    } catch(e) {}
  }
  badge.style.display = 'none';
}

function speakText(text) {
  if (!_ttsEnabled || !text || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  var utterance = new SpeechSynthesisUtterance(text.replace(/<[^>]*>/g, '').slice(0, 1000));
  utterance.rate = 1.0;
  utterance.pitch = 1.0;
  utterance.volume = 1.0;
  window.speechSynthesis.speak(utterance);
}

function loadSession(id) {
  if (_isRunning) return;
  currentSession = id;
  _claudeSessionId = '';  // historical sessions can't resume a live Claude Code session
  updateSessionBadge();
  document.getElementById('welcome').classList.add('hidden');
  document.querySelectorAll('.session-item').forEach(function(e) { e.classList.remove('active'); });
  var el = document.querySelector('[data-session="' + id + '"]');
  if (el) el.classList.add('active');
  htmx.ajax('GET', '/api/sessions/' + id + '/messages', {
    target: '#messages',
    swap: 'innerHTML',
  });
  // Add export button to messages header
  var msgs = document.getElementById('messages');
  msgs.style.paddingTop = '4px';
  var exportBtn = document.createElement('div');
  exportBtn.style.cssText = 'display:flex;gap:6px;padding:4px 0 8px;border-bottom:1px solid var(--border-subtle);margin-bottom:8px';
  exportBtn.innerHTML = '<button class="header-btn" onclick="exportSession()">Export MD</button>';
  msgs.insertBefore(exportBtn, msgs.firstChild);
  if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
  activeTaskId = null;
}

function exportSession() {
  if (!currentSession) return;
  window.open('/api/sessions/' + currentSession + '/export?fmt=md', '_blank');
}

function toggleCtxEntry(id) {
  var el = document.getElementById('ctx-text-' + id);
  if (el) {
    el.classList.toggle('expanded');
    var btn = el.parentNode.querySelector('.ctx-entry-expand');
    if (btn) btn.textContent = el.classList.contains('expanded') ? 'less' : 'more';
  }
}

function toggleContext() {
  ctxOpen = !ctxOpen;
  document.getElementById('ctx-panel').classList.toggle('closed', !ctxOpen);
  if (ctxOpen) htmx.trigger('body', 'contextUpdated');
  saveConfig();
}

function toggleConfig() {
  _configOpen = !_configOpen;
  document.getElementById('config-fields').classList.toggle('collapsed', !_configOpen);
}

var _overflowOpen = false;
function toggleOverflow() {
  _overflowOpen = !_overflowOpen;
  var m = document.getElementById('overflow-menu');
  m.style.display = _overflowOpen ? 'flex' : 'none';
}
document.addEventListener('click', function(e) {
  if (_overflowOpen && !document.getElementById('overflow-btn').contains(e.target) && !document.getElementById('overflow-menu').contains(e.target)) {
    _overflowOpen = false;
    document.getElementById('overflow-menu').style.display = 'none';
  }
});

window.switchTab = function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('.tab-content').forEach(function(c) { c.style.display = 'none'; });
  document.querySelector('.tab-btn[onclick="switchTab(\'' + name + '\')"]').classList.add('active');
  document.getElementById('tab-' + name).style.display = 'flex';
  if (name === 'skills') refreshSkills();
};

function refreshSkills() {
  // ── Tools ──────────────────────────────────────────────────
  fetch('/api/tools').then(function(r) { return r.json(); }).then(function(data) {
    var tools = data.tools || [];
    document.getElementById('tools-count').textContent = '(' + tools.length + ')';
    var _ICONS = {
      read:'📄', write:'✏️', edit:'✏️', glob:'🔍', bash:'💻', grep:'🔎',
      webfetch:'🌐', websearch:'🔍', weather:'⛅', news:'📰', crypto:'₿',
      currency:'💱', wikipedia:'📖', github_search:'🐙', nasa_apod:'🌌',
      git:'🌿', task:'📋', diff:'⚖️', patch:'🩹', apply_edit:'✅',
      index:'📑', analyze:'🧠', testgen:'🧪', watch:'👁️', sandbox:'📦',
      scaffold:'🏗️', improve:'⚡', workflow:'🔄', docgen:'📝', graphviz:'📊',
      knowledge:'💡', security_audit:'🔒', multilang:'🌍', swarm:'🐝',
      transform:'🔀', review:'✔️', api:'🔌', sql:'🗄️', browser:'🖥️',
    };
    window._toolRegistry = tools;
    var html = '';
    tools.forEach(function(t, i) {
      var icon = _ICONS[t.name] || '🔧';
      html += '<button data-tool-idx="' + i + '" class="tool-chip" style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:14px;font-size:11px;cursor:pointer;font-family:inherit;color:var(--text-primary);transition:all .15s">'
        + '<span>' + icon + '</span>'
        + '<span style="font-weight:500">' + escapeHtml(t.name) + '</span>'
        + '</button>';
    });
    var grid = document.getElementById('tools-grid');
    grid.innerHTML = html || '<span style="color:var(--text-secondary);font-size:12px">No tools loaded.</span>';
    grid.onclick = function(e) {
      var chip = e.target.closest('.tool-chip');
      if (!chip) return;
      showToolDetail(parseInt(chip.getAttribute('data-tool-idx'), 10));
    };
  }).catch(function() {
    document.getElementById('tools-grid').innerHTML = '<span style="color:#f85149;font-size:12px">Failed to load tools.</span>';
  });

  // ── Active Agents ──────────────────────────────────────────
  fetch('/api/nemotron/agents').then(function(r) { return r.json(); }).then(function(data) {
    var agents = data.agents || [];
    var _AGENT_COLORS = { claude_code: '#58a6ff', opencode: '#a371f7', codex: '#3fb950', openclaw: '#d29922' };
    var html = '';
    agents.forEach(function(a) {
      var color = _AGENT_COLORS[a.name] || '#8b949e';
      var status = (a.health && a.health.status) || 'unknown';
      var dot = status === 'available' ? '#3fb950' : status === 'degraded' ? '#d29922' : '#8b949e';
      var caps = (a.capabilities || []).join(', ') || 'general';
      html += '<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px">'
        + '<span style="width:8px;height:8px;border-radius:50%;background:' + dot + ';flex-shrink:0"></span>'
        + '<div style="flex:1;min-width:0">'
        + '<div style="font-weight:600;font-size:12px;color:' + color + '">' + escapeHtml(a.display_name || a.name) + '</div>'
        + '<div style="font-size:11px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + escapeHtml(caps) + '</div>'
        + '</div>'
        + '<span style="font-size:10px;color:' + dot + ';background:var(--bg-primary);padding:1px 6px;border-radius:8px;border:1px solid ' + dot + '">' + escapeHtml(status) + '</span>'
        + '</div>';
    });
    document.getElementById('agents-grid').innerHTML = html || '<span style="color:var(--text-secondary);font-size:12px">No agents registered.</span>';
  }).catch(function() {
    document.getElementById('agents-grid').innerHTML = '<span style="color:#f85149;font-size:12px">Failed to load agents.</span>';
  });

  // ── Learned Skills ─────────────────────────────────────────
  fetch('/api/skillsv2/list?limit=50').then(function(r) { return r.json(); }).then(function(data) {
    var skills = data.skills || [];
    var el = document.getElementById('skills-list');
    if (skills.length === 0) {
      el.innerHTML = '<span style="color:var(--text-secondary)">None yet — skills are learned automatically as Orchestra completes tasks.</span>';
      document.getElementById('skills-stats').textContent = '';
      return;
    }
    document.getElementById('skills-stats').textContent = '(' + skills.length + ')';
    var html = '<div style="display:flex;flex-direction:column;gap:4px">';
    skills.forEach(function(s) {
      var reward = ((s.total_reward || 0) / Math.max(s.usage_count || 1, 1));
      var bar = Math.max(0, Math.min(100, reward * 100));
      var barColor = reward >= 0.7 ? '#3fb950' : reward >= 0.4 ? '#d29922' : '#f85149';
      html += '<div style="padding:7px 10px;background:var(--bg-tertiary);border-radius:6px;border:1px solid var(--border)">'
        + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
        + '<span style="font-size:11px;font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:8px">' + escapeHtml((s.body || '').slice(0, 80)) + '</span>'
        + '<span style="font-size:10px;color:var(--text-secondary);flex-shrink:0">' + (s.usage_count || 0) + ' uses</span>'
        + '</div>'
        + '<div style="height:3px;background:var(--bg-primary);border-radius:2px">'
        + '<div style="height:100%;width:' + bar + '%;background:' + barColor + ';border-radius:2px"></div>'
        + '</div>'
        + '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
  }).catch(function() {
    document.getElementById('skills-list').innerHTML = '<span style="color:#f85149;font-size:12px">Failed to load skills.</span>';
  });
}

function pruneSkills() {
  fetch('/api/skillsv2/prune', {method:'POST'}).then(function(r) { return r.json(); }).then(function(d) {
    alert('Pruned ' + d.removed + ' skills. Remaining: ' + d.remaining);
    refreshSkills();
  });
}

document.addEventListener('htmx:afterSwap', function(evt) {
  if (evt.detail && evt.detail.target) {
    if (evt.detail.target.id === 'session-list') {
      var count = document.querySelectorAll('.session-item').length;
      document.getElementById('session-count').textContent = count;
    }
    if (evt.detail.target.id === 'messages') {
      // Render markdown in loaded session messages
      evt.detail.target.querySelectorAll('.msg.assistant .msg-content').forEach(function(div) {
        try {
          var raw = div.textContent;
          if (raw && raw.trim()) {
            div.innerHTML = marked.parse(raw);
            div.querySelectorAll('pre code').forEach(function(b) { try { hljs.highlightElement(b); } catch(e) {} });
          }
        } catch(e) {}
      });
    }
  }
});

function applyCtxOpen() {
  var panel = document.getElementById('ctx-panel');
  if (panel) panel.classList.toggle('closed', !ctxOpen);
  if (ctxOpen) htmx.trigger('body', 'contextUpdated');
}

var _modelOpts = [];
document.querySelectorAll('#model option').forEach(function(o) { _modelOpts.push({value:o.value,label:o.label,group:o.parentElement.label}); });

function filterModelByProvider(provider) {
  var sel = document.getElementById('model');
  var current = sel.value;
  sel.innerHTML = '';
  var groups = {};
  _modelOpts.forEach(function(o) {
    var match = (provider === 'ollama' && (o.group === 'Ollama' || o.group === 'vLLM')) ||
                (provider === 'openai' && o.group === 'OpenAI') ||
                (provider === 'anthropic' && o.group === 'Anthropic') ||
                (provider === 'vllm' && o.group === 'vLLM');
    if (match) {
      if (!groups[o.group]) {
        var g = document.createElement('optgroup');
        g.label = o.group;
        groups[o.group] = g;
        sel.appendChild(g);
      }
      var opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      groups[o.group].appendChild(opt);
    }
  });
  if (sel.querySelector('option[value="' + current + '"]')) { sel.value = current; }
  else { sel.selectedIndex = 0; }
}

// ── Theme management ──────────────────────────────────────────────────────
function currentTheme() {
  try { return localStorage.getItem('orchestra-theme') || 'dark'; } catch(e) { return 'dark'; }
}
function applyTheme(theme, animate) {
  try {
    var isLight = (theme === 'light');

    // Remove injected stylesheet
    var prev = document.getElementById('__orch_theme__');
    if (prev) prev.remove();

    if (isLight) {
      // Force inline styles on root elements (maximum override priority)
      document.documentElement.style.background = '#f6f8fa';
      document.body.style.background = '#f6f8fa';
      document.body.style.color = '#1f2328';

      // Inject stylesheet with !important for all child elements
      var s = document.createElement('style');
      s.id = '__orch_theme__';
      s.textContent = [
        'html,body{background:#f6f8fa!important;color:#1f2328!important}',
        'header{background:rgba(246,248,250,.92)!important;border-bottom-color:#d0d7de!important}',
        '#sidebar,#sidebar-header,#sidebar-nav,#sidebar-footer{background:#ffffff!important;border-color:#d0d7de!important;color:#1f2328!important}',
        '#main,#chat,#messages{background:#f6f8fa!important}',
        '#input-area,.config-bar,.tab-bar{background:#ffffff!important;border-color:#d0d7de!important}',
        '#ctx-panel,#ctx-inner{background:#ffffff!important;border-color:#d0d7de!important}',
        '.session-item{color:#1f2328!important}',
        '.session-item:hover{background:#eaeef2!important}',
        '.session-item.active{background:rgba(9,105,218,.08)!important}',
        '.session-del{color:#656d76!important}',
        '.header-btn{background:#eaeef2!important;border-color:#d0d7de!important;color:#1f2328!important}',
        '#task-input{background:#ffffff!important;color:#1f2328!important;border-color:#d0d7de!important}',
        '.nav-btn{color:#656d76!important}.nav-btn.active{color:#0969da!important;border-bottom-color:#0969da!important}',
        '.tab-btn{color:#656d76!important}.tab-btn.active{color:#0969da!important;border-bottom-color:#0969da!important}',
        '.ctx-tab{color:#656d76!important}.ctx-tab.active{color:#0969da!important;border-bottom-color:#0969da!important}',
        '.preset-btn{background:#eaeef2!important;border-color:#d0d7de!important;color:#656d76!important}',
        '.preset-btn.active{background:#0969da!important;border-color:#0969da!important;color:#fff!important}',
        '.msg.assistant .msg-content pre{background:#ffffff!important;border-color:#d0d7de!important}',
        '.msg.assistant .msg-content code{background:rgba(9,105,218,.07)!important;color:#0969da!important}',
        '.msg.tool{background:#ffffff!important;border-color:#d0d7de!important}',
        '.msg.tool summary{color:#0969da!important}',
        '.msg.tool .tool-args,.msg.tool .tool-result{background:#f6f8fa!important;border-color:#d0d7de!important;color:#1f2328!important}',
        'select,option,.config-bar select,.config-bar input{background:#ffffff!important;color:#1f2328!important;border-color:#d0d7de!important}',
        '#engine{color:#0969da!important;border-color:#0969da!important}',
        '#search-history{background:#ffffff!important;color:#1f2328!important}',
        '.example-btn{background:#eaeef2!important;border-color:#d0d7de!important;color:#656d76!important}',
        '.theme-pill{background:#eaeef2!important;border-color:#d0d7de!important}',
        '.theme-pill__seg{color:#656d76!important}',
        '.theme-pill__seg.active{background:#ffffff!important;color:#1f2328!important;box-shadow:0 1px 3px rgba(0,0,0,.1)!important}',
        '#welcome h2{color:#1f2328!important}',
        '#welcome p{color:#656d76!important}',
        '.section-thought{background:#f6f8fa!important}',
        '.section-thought-body{color:#656d76!important}',
        '.sidebar-footer-label,.toggle-track{border-color:#d0d7de!important}',
        'h1,h2,h3,h4,p,span,label,div{color:inherit}',
      ].join('\n');
      document.head.appendChild(s);
    } else {
      // Dark mode: remove inline overrides so CSS vars take over
      document.documentElement.style.background = '';
      document.body.style.background = '';
      document.body.style.color = '';
    }

    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('orchestra-theme', theme); } catch(e) {}

    // Update pill button active states
    var darkBtn = document.getElementById('theme-dark-btn');
    var lightBtn = document.getElementById('theme-light-btn');
    if (darkBtn) darkBtn.classList.toggle('active', !isLight);
    if (lightBtn) lightBtn.classList.toggle('active', isLight);

    // Meta theme-color for mobile browser chrome
    var metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', isLight ? '#f6f8fa' : '#0d1117');

    if (animate) {
      document.documentElement.classList.add('theme-transitioning');
      setTimeout(function(){ document.documentElement.classList.remove('theme-transitioning'); }, 300);
    }
  } catch(err) {
    console.error('[Orchestra] applyTheme error:', err);
  }
}
function toggleTheme() { applyTheme(currentTheme() === 'dark' ? 'light' : 'dark', true); }

document.addEventListener('DOMContentLoaded', function() {
  // Wire theme pill buttons — addEventListener is more reliable than inline onclick
  var _darkBtn = document.getElementById('theme-dark-btn');
  var _lightBtn = document.getElementById('theme-light-btn');
  if (_darkBtn) _darkBtn.addEventListener('click', function(e) { e.stopPropagation(); applyTheme('dark', true); });
  if (_lightBtn) _lightBtn.addEventListener('click', function(e) { e.stopPropagation(); applyTheme('light', true); });

  applyTheme(currentTheme(), false);
  loadConfig();
  filterModelByProvider(document.getElementById('provider').value);
  syncPreset();
  applyCtxOpen();
  try { if (localStorage.getItem('ca_jarvis') === '1') toggleJarvis(); } catch(e) {}
  try { if (localStorage.getItem('ca_tts') === '1') { document.getElementById('tts-toggle').checked = true; _ttsEnabled = true; } } catch(e) {}
  detectLanguage();
  var input = document.getElementById('task-input');
  input.disabled = false;
  document.getElementById('send-btn').disabled = false;
  input.focus();
  input.addEventListener('input', adjustTextarea);
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTask();
    }
  });
  document.getElementById('engine').addEventListener('change', function() {
    // When engine changes to an agentic mode, switch to Anthropic by default
    var eng = this.value;
    if (eng === 'claude_code' || eng === 'opencode' || eng === 'auto') {
      if (document.getElementById('provider').value === 'ollama') {
        document.getElementById('provider').value = 'anthropic';
        filterModelByProvider('anthropic');
        document.getElementById('model').value = 'claude-opus-4-7';
      }
    } else if (eng === 'direct') {
      if (document.getElementById('provider').value === 'anthropic') {
        document.getElementById('provider').value = 'ollama';
        filterModelByProvider('ollama');
        document.getElementById('model').value = 'nemotron-mini';
      }
    }
    saveConfig();
    syncPreset();
  });
  document.getElementById('provider').addEventListener('change', function() {
    filterModelByProvider(this.value);
    saveConfig();
    syncPreset();
  });
  document.getElementById('model').addEventListener('change', function() {
    saveConfig();
    syncPreset();
  });

  // Show onboarding on first visit
  try {
    if (!localStorage.getItem('orchestra_onboarded')) {
      setTimeout(function() { showOnboarding(); }, 400);
    }
  } catch(e) {}
});

function showToolDetail(idx) {
  var t = (window._toolRegistry || [])[idx];
  if (!t) return;
  var detail = document.getElementById('tool-detail');
  var curName = document.getElementById('tool-detail-name').textContent;
  if (detail.style.display !== 'none' && curName === t.name) {
    detail.style.display = 'none';
    return;
  }
  document.getElementById('tool-detail-name').textContent = t.name;
  document.getElementById('tool-detail-desc').textContent = t.description;
  var paramsEl = document.getElementById('tool-detail-params');
  if (t.parameters && t.parameters.length) {
    paramsEl.innerHTML = '<span style="font-weight:600">Parameters:</span> '
      + t.parameters.map(function(p) {
          return '<code style="background:var(--bg-tertiary);padding:1px 5px;border-radius:3px;font-size:11px">' + escapeHtml(p) + '</code>';
        }).join(' ');
  } else {
    paramsEl.textContent = 'No parameters required.';
  }
  document.getElementById('tool-detail-use').onclick = function() {
    window.switchTab('chat');
    var input = document.getElementById('task-input');
    input.value = 'Use the ' + t.name + ' tool to ';
    input.focus();
    adjustTextarea();
  };
  detail.style.display = 'block';
  detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── File Browser ─────────────────────────────────────────────────────────────

function updateWorkspaceBadge() {
  var badge = document.getElementById('workspace-badge');
  if (!badge) return;
  if (_workspace) {
    var short = _workspace.replace(/\\/g, '/').split('/').slice(-2).join('/');
    badge.textContent = '📌 ' + short;
    badge.title = 'Workspace: ' + _workspace;
    badge.style.display = '';
  } else {
    badge.style.display = 'none';
  }
}

function updateSessionBadge() {
  var badge = document.getElementById('session-badge');
  if (!badge) return;
  badge.style.display = _claudeSessionId ? '' : 'none';
}

function clearClaudeSession() {
  _claudeSessionId = '';
  updateSessionBadge();
  showToast('Session cleared — next task starts fresh', 'info');
}

function setWorkspaceHere() {
  _workspace = _fileBrowsePath;
  updateWorkspaceBadge();
  showToast('Workspace set to: ' + _fileBrowsePath.split(/[\\/]/).slice(-1)[0], 'success');
}

function fileBrowseUp() {
  var cur = _fileBrowsePath;
  if (!cur) return;
  // Find parent by stripping last segment
  var parts = cur.replace(/\\/g, '/').split('/').filter(Boolean);
  if (parts.length <= 1) return;
  parts.pop();
  var parent = parts.join('/');
  // Re-add drive letter prefix on Windows (e.g. C:)
  if (cur.match(/^[A-Za-z]:\\/)) {
    parent = cur.slice(0, 3) + parts.slice(1).join('\\');
  }
  browseFiles(parent);
}

function browseFiles(path) {
  var list = document.getElementById('file-list');
  var pathDisplay = document.getElementById('file-path-display');
  var wsBtn = document.getElementById('file-set-workspace');
  if (list) list.innerHTML = '<div style="color:var(--text-secondary);font-size:11px;padding:6px">Loading...</div>';

  var url = '/api/files/browse' + (path ? '?path=' + encodeURIComponent(path) : '');
  fetch(url).then(function(r) { return r.json(); }).then(function(data) {
    _fileBrowsePath = data.path;
    if (pathDisplay) {
      var shortPath = data.path.replace(/\\/g, '/');
      pathDisplay.textContent = shortPath;
      pathDisplay.title = data.path;
    }
    if (wsBtn) wsBtn.style.display = data.path ? '' : 'none';
    var upBtn = document.getElementById('file-up-btn');
    if (upBtn) upBtn.disabled = !data.parent;

    if (!list) return;
    var html = '';
    (data.entries || []).forEach(function(e) {
      var icon = e.is_dir ? '&#x1F4C1;' : getFileIcon(e.name);
      var size = e.is_dir ? '' : formatFileSize(e.size);
      html += '<div class="file-entry" style="display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:4px;cursor:pointer;font-size:11px;transition:background .1s" '
        + 'onmouseenter="this.style.background=\'var(--bg-tertiary)\'" '
        + 'onmouseleave="this.style.background=\'transparent\'" '
        + 'onclick="' + (e.is_dir ? 'browseFiles(' + JSON.stringify(e.path) + ')' : 'previewFile(' + JSON.stringify(e.path) + ',' + JSON.stringify(e.name) + ')') + '">'
        + '<span style="flex-shrink:0">' + icon + '</span>'
        + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:' + (e.is_dir ? 'var(--text-link)' : 'var(--text-primary)') + '">' + escapeHtml(e.name) + '</span>'
        + (size ? '<span style="color:var(--text-secondary);flex-shrink:0">' + size + '</span>' : '')
        + '</div>';
    });
    list.innerHTML = html || '<div style="color:var(--text-secondary);font-size:11px;padding:6px">Empty directory</div>';
  }).catch(function(err) {
    if (list) list.innerHTML = '<div style="color:#f85149;font-size:11px;padding:6px">Error: ' + escapeHtml(err.message || 'failed') + '</div>';
  });
}

function previewFile(path, name) {
  var preview = document.getElementById('file-preview');
  var previewName = document.getElementById('file-preview-name');
  var previewContent = document.getElementById('file-preview-content');
  if (previewName) previewName.textContent = name;
  if (previewContent) previewContent.textContent = 'Loading...';
  if (preview) preview.style.display = '';

  fetch('/api/files/read?path=' + encodeURIComponent(path)).then(function(r) { return r.json(); }).then(function(data) {
    var text = data.content || '';
    if (data.truncated) text += '\n... (truncated, ' + formatFileSize(data.size) + ' total)';
    if (previewContent) previewContent.textContent = text;
    // Also attach file context to task input
    var input = document.getElementById('task-input');
    if (input && !input.value) {
      input.value = 'Read and analyze the file: ' + path;
      adjustTextarea();
    }
  }).catch(function(err) {
    if (previewContent) previewContent.textContent = 'Error: ' + err.message;
  });
}

function getFileIcon(name) {
  var ext = name.split('.').pop().toLowerCase();
  var map = { py:'&#x1F40D;', js:'&#x1F7E1;', ts:'&#x1F535;', html:'&#x1F7E0;', css:'&#x1F7E3;',
    json:'&#x1F4CB;', md:'&#x1F4DD;', txt:'&#x1F4C4;', sh:'&#x1F4BB;', bat:'&#x1F4BB;',
    yml:'&#x2699;', yaml:'&#x2699;', toml:'&#x2699;', rs:'&#x1F984;', go:'&#x1F4A0;',
    java:'&#x2615;', c:'&#x1F527;', cpp:'&#x1F527;', png:'&#x1F5BC;', jpg:'&#x1F5BC;',
    gif:'&#x1F5BC;', svg:'&#x1F5BC;', pdf:'&#x1F4D5;', zip:'&#x1F4E6;', tar:'&#x1F4E6;',
  };
  return map[ext] || '&#x1F4C4;';
}

function formatFileSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Self-Improve ──────────────────────────────────────────────────────────────

var _orchestraInfo = null;

function openSelfImprove() {
  var modal = document.getElementById('self-improve-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  var wsEl = document.getElementById('self-improve-ws');
  if (!_orchestraInfo) {
    fetch('/api/orchestra/info').then(function(r) { return r.json(); }).then(function(d) {
      _orchestraInfo = d;
      if (wsEl) wsEl.textContent = 'src: ' + (d.source_root || d.workspace || '');
    }).catch(function() {});
  } else {
    if (wsEl) wsEl.textContent = 'src: ' + (_orchestraInfo.source_root || _orchestraInfo.workspace || '');
  }
  setTimeout(function() {
    var inp = document.getElementById('self-improve-input');
    if (inp) inp.focus();
  }, 50);
}

function runSelfImprove(mode) {
  var inp = document.getElementById('self-improve-input');
  var task = inp ? inp.value.trim() : '';
  var orchestraRoot = (_orchestraInfo && (_orchestraInfo.source_root || _orchestraInfo.workspace)) || '';
  var SUMMARY_SUFFIX = '\n\nWhen finished, write a concise summary of every file changed and why.';

  if (mode === 'analyze') {
    task = task || 'Analyze Orchestra\'s source code structure, identify any bugs or improvements, and report your findings without making changes.';
    task += SUMMARY_SUFFIX;
  } else {
    if (!task) {
      showToast('Please describe what to improve', 'warning');
      return;
    }
    task = 'Working on Orchestra\'s own source code at ' + (orchestraRoot || 'the project root') + '. ' + task + SUMMARY_SUFFIX;
  }

  // Close modal
  document.getElementById('self-improve-modal').style.display = 'none';

  // Set workspace to orchestra source root
  if (orchestraRoot) {
    _workspace = orchestraRoot;
    updateWorkspaceBadge();
  }

  // Pre-fill input and auto-set engine
  switchTab('chat');
  var input = document.getElementById('task-input');
  if (input) {
    input.value = task;
    adjustTextarea();
  }
  var engineEl = document.getElementById('engine');
  if (engineEl) engineEl.value = 'claude_code';

  // Auto-submit — don't make user press Run a second time
  setTimeout(function() { sendTask(); }, 80);
}

// Expose all onclick-called functions to global scope
window.cancelTask = cancelTask;
window.togglePreset = togglePreset;
window.setTask = setTask;
window.askPrince = askPrince;
window.newSession = newSession;
window.switchSidebar = switchSidebar;
window.createSpace = createSpace;
window.openSpace = openSpace;
window.viewArtifact = viewArtifact;
window.switchCtxTab = switchCtxTab;
window.toggleJarvis = toggleJarvis;
window.toggleMic = toggleMic;
window.exportSession = exportSession;
window.toggleCtxEntry = toggleCtxEntry;
window.toggleContext = toggleContext;
window.toggleConfig = toggleConfig;
window.toggleOverflow = toggleOverflow;
window.refreshSkills = refreshSkills;
window.pruneSkills = pruneSkills;
window.showToolDetail = showToolDetail;
window.browseFiles = browseFiles;
window.previewFile = previewFile;
window.fileBrowseUp = fileBrowseUp;
window.setWorkspaceHere = setWorkspaceHere;
window.updateSessionBadge = updateSessionBadge;
window.clearClaudeSession = clearClaudeSession;
window.openSelfImprove = openSelfImprove;
window.runSelfImprove = runSelfImprove;
window.loadSession = loadSession;
window.deleteSession = deleteSession;
window.searchHistory = searchHistory;
window.toggleMemory = toggleMemory;
window.attachImage = attachImage;
window.toggleTts = toggleTts;
window.adjustTextarea = adjustTextarea;
window.sendTask = sendTask;

})();

// Register service worker for PWA offline support
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(function() {});
}

// ── Run History ───────────────────────────────────────────────────────────
async function loadRunHistory() {
  var list = document.getElementById('run-list');
  if (!list) return;
  try {
    var r = await fetch('/api/runs?limit=80');
    var d = await r.json();
    var runs = d.runs || [];
    if (!runs.length) { list.innerHTML = '<div style="color:var(--text-secondary);font-size:11px;padding:8px">No runs yet.</div>'; return; }
    list.innerHTML = runs.map(function(run) {
      var dot = run.status === 'done' ? '#3fb950' : run.status === 'error' ? '#f85149' : '#f0883e';
      var age = run.created_at ? _relTime(run.created_at) : '';
      var eng = run.engine ? '<span style="font-size:9px;background:var(--bg-tertiary);padding:1px 5px;border-radius:3px;color:var(--text-secondary)">'+run.engine+'</span>' : '';
      var cost = run.cost_usd ? '<span style="font-size:9px;color:var(--text-secondary)">$'+Number(run.cost_usd).toFixed(3)+'</span>' : '';
      var taskShort = (run.task||'').substring(0,70) + ((run.task||'').length>70?'…':'');
      return '<div class="session-item" style="padding:8px 10px;margin-bottom:2px;cursor:pointer;border-radius:8px" onclick="replayRun(\''+run.id+'\')" title="Click to replay">'
        + '<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px">'
          + '<span style="width:6px;height:6px;border-radius:50%;background:'+dot+';flex-shrink:0"></span>'
          + '<span style="font-size:11px;font-weight:600;color:var(--text-primary);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+_esc2(taskShort)+'</span>'
          + '<button onclick="event.stopPropagation();deleteRun(\''+run.id+'\')" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:10px;flex-shrink:0;opacity:.5;padding:0">&#x2715;</button>'
        + '</div>'
        + '<div style="display:flex;gap:6px;align-items:center">'+eng+cost+'<span style="font-size:10px;color:var(--text-secondary);margin-left:auto">'+age+'</span></div>'
        + '</div>';
    }).join('');
  } catch(e) {
    if (list) list.innerHTML = '<div style="color:var(--accent-red);font-size:11px;padding:8px">'+e.message+'</div>';
  }
}

function replayRun(id) {
  fetch('/api/runs/'+id).then(function(r){return r.json();}).then(function(run) {
    if (!run || !run.task) return;
    var inp = document.getElementById('task-input');
    if (inp) { inp.value = run.task; adjustTextarea && adjustTextarea.call(inp); inp.focus(); }
    showToast('Task loaded — press Run to re-execute', 'info');
  });
}

async function deleteRun(id) {
  await fetch('/api/runs/'+id, {method:'DELETE'});
  loadRunHistory();
}

async function clearRunHistory() {
  if (!confirm('Clear all run history?')) return;
  await fetch('/api/runs', {method:'DELETE'});
  loadRunHistory();
}

function _esc2(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function _relTime(iso) {
  try {
    var ms = Date.now() - new Date(iso.replace(' ','T')+'Z').getTime();
    var s = Math.floor(ms/1000);
    if (s < 60) return 'just now';
    var m = Math.floor(s/60); if (m < 60) return m+'m ago';
    var h = Math.floor(m/60); if (h < 24) return h+'h ago';
    return Math.floor(h/24)+'d ago';
  } catch(e) { return ''; }
}

// ── Mobile sidebar ───────────────────────────────────────────────────────
function toggleMobileSidebar() {
  var sb = document.getElementById('sidebar');
  var bd = document.getElementById('sidebar-backdrop');
  var open = sb.classList.toggle('mobile-open');
  if (bd) bd.classList.toggle('visible', open);
}

// Close sidebar when a session or nav item is tapped on mobile
document.addEventListener('click', function(e) {
  var sb = document.getElementById('sidebar');
  if (!sb || !sb.classList.contains('mobile-open')) return;
  // Close if tap was on a session-item or nav-btn (but not the toggle itself)
  if (e.target.closest('.session-item') || e.target.closest('.nav-btn')) {
    sb.classList.remove('mobile-open');
    var bd = document.getElementById('sidebar-backdrop');
    if (bd) bd.classList.remove('visible');
  }
});

// ── GitHub Integration ───────────────────────────────────────────────────
var _ghToken = '';
var _ghRepos = [];
var _ghCurrentRepo = null;

function _ghHeaders() {
  var h = { 'Content-Type': 'application/json' };
  if (_ghToken) h['X-GitHub-Token'] = _ghToken;
  return h;
}

async function ghConnect() {
  var inp = document.getElementById('gh-token-input');
  if (inp) _ghToken = inp.value.trim();
  try { localStorage.setItem('gh_token', _ghToken); } catch(e) {}
  await ghLoadStatus();
}

function ghDisconnect() {
  _ghToken = '';
  try { localStorage.removeItem('gh_token'); } catch(e) {}
  document.getElementById('gh-user-bar').style.display = 'none';
  document.getElementById('gh-search-bar').style.display = 'none';
  document.getElementById('gh-connect-prompt').style.display = '';
  document.getElementById('gh-repo-list').innerHTML = '';
}

async function ghLoadStatus() {
  try {
    var r = await fetch('/api/github/status', { headers: _ghHeaders() });
    var d = await r.json();
    if (d.connected && d.user) {
      document.getElementById('gh-connect-prompt').style.display = 'none';
      var bar = document.getElementById('gh-user-bar');
      bar.style.display = 'flex';
      document.getElementById('gh-avatar').src = d.user.avatar_url || '';
      document.getElementById('gh-username').textContent = d.user.login || '';
      document.getElementById('gh-repo-count').textContent = (d.user.public_repos || 0) + ' repos';
      document.getElementById('gh-search-bar').style.display = '';
      ghLoadRepos();
    }
  } catch(e) {}
}

async function ghLoadRepos() {
  var list = document.getElementById('gh-repo-list');
  list.innerHTML = '<div style="color:var(--text-secondary);font-size:11px;padding:8px">Loading&#x2026;</div>';
  try {
    var r = await fetch('/api/github/repos?per_page=50&sort=pushed', { headers: _ghHeaders() });
    var d = await r.json();
    _ghRepos = d.repos || [];
    ghRenderRepos(_ghRepos);
  } catch(e) {
    list.innerHTML = '<div style="color:var(--accent-red);font-size:11px;padding:8px">'+e.message+'</div>';
  }
}

function ghFilterRepos(q) {
  var filtered = q ? _ghRepos.filter(function(r){ return r.full_name.toLowerCase().includes(q.toLowerCase()) || (r.description||'').toLowerCase().includes(q.toLowerCase()); }) : _ghRepos;
  ghRenderRepos(filtered);
}

function ghRenderRepos(repos) {
  var list = document.getElementById('gh-repo-list');
  if (!repos.length) { list.innerHTML = '<div style="color:var(--text-secondary);font-size:11px;padding:8px">No repos found.</div>'; return; }
  list.innerHTML = repos.map(function(r) {
    var lang = r.language ? '<span style="font-size:9px;background:var(--bg-tertiary);padding:1px 5px;border-radius:4px;color:var(--text-secondary)">'+r.language+'</span>' : '';
    var priv = r.private ? '<span style="font-size:9px;color:#f0883e">&#x1F512;</span>' : '';
    return '<div class="session-item" onclick="ghOpenRepo(\''+r.full_name+'\',\''+r.clone_url+'\',\''+r.default_branch+'\')" style="cursor:pointer;padding:8px 10px;border-radius:8px;margin-bottom:2px">'
      + '<div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">'
        + priv + '<span style="font-size:12px;font-weight:600;color:var(--text-primary);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+r.name+'</span>'
        + lang
      + '</div>'
      + (r.description ? '<div style="font-size:10px;color:var(--text-secondary);line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+r.description+'</div>' : '')
      + '</div>';
  }).join('');
}

async function ghOpenRepo(fullName, cloneUrl, defaultBranch) {
  _ghCurrentRepo = { fullName: fullName, cloneUrl: cloneUrl, defaultBranch: defaultBranch };
  var parts = fullName.split('/');
  document.getElementById('gh-tree-name').textContent = fullName;
  document.getElementById('gh-repo-list').style.display = 'none';
  document.getElementById('gh-search-bar').style.display = 'none';
  document.getElementById('gh-tree-view').style.display = 'flex';

  // Load branches
  try {
    var rb = await fetch('/api/github/repos/'+parts[0]+'/'+parts[1]+'/branches', { headers: _ghHeaders() });
    var db = await rb.json();
    var sel = document.getElementById('gh-branch-select');
    sel.innerHTML = (db.branches||[defaultBranch]).map(function(b){ return '<option value="'+b+'"'+(b===defaultBranch?' selected':'')+'>'+b+'</option>'; }).join('');
    ghLoadTree();
  } catch(e) {}
}

async function ghLoadTree() {
  var parts = (_ghCurrentRepo||{}).fullName.split('/');
  var branch = document.getElementById('gh-branch-select').value || (_ghCurrentRepo||{}).defaultBranch || 'main';
  var tl = document.getElementById('gh-tree-list');
  tl.innerHTML = '<div style="color:var(--text-secondary);font-size:11px;padding:6px">Loading&#x2026;</div>';
  try {
    var r = await fetch('/api/github/repos/'+parts[0]+'/'+parts[1]+'/tree?branch='+encodeURIComponent(branch), { headers: _ghHeaders() });
    var d = await r.json();
    var files = (d.files||[]).filter(function(f){ return f.type==='blob'; }).slice(0,200);
    tl.innerHTML = files.map(function(f) {
      var name = f.path.split('/').pop();
      var dir = f.path.includes('/') ? f.path.replace('/'+name,'') : '';
      return '<div style="padding:2px 4px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+f.path+'">'
        + (dir ? '<span style="color:var(--text-secondary);opacity:.5">'+dir+'/</span>' : '')
        + '<span style="color:var(--text-primary)">'+name+'</span>'
        + '</div>';
    }).join('') || '<div style="color:var(--text-secondary);font-size:11px;padding:6px">Empty repo</div>';
  } catch(e) { tl.innerHTML = '<div style="color:var(--accent-red);font-size:11px;padding:6px">'+e.message+'</div>'; }
}

function ghShowRepos() {
  document.getElementById('gh-tree-view').style.display = 'none';
  document.getElementById('gh-repo-list').style.display = '';
  document.getElementById('gh-search-bar').style.display = '';
}

async function ghClone() {
  if (!_ghCurrentRepo) return;
  var dest = prompt('Clone to path:', 'C:\\repos\\' + (_ghCurrentRepo.fullName||'').split('/')[1]);
  if (!dest) return;
  try {
    var r = await fetch('/api/github/clone', {
      method: 'POST',
      headers: _ghHeaders(),
      body: JSON.stringify({ clone_url: _ghCurrentRepo.cloneUrl, dest: dest })
    });
    var d = await r.json();
    if (d.cloned) {
      _workspace = dest;
      updateWorkspaceBadge();
      showToast('Cloned to ' + dest + ' — workspace set', 'success');
    }
  } catch(e) { showToast('Clone failed: ' + e.message, 'error'); }
}

function ghUseAsTask() {
  if (!_ghCurrentRepo) return;
  var inp = document.getElementById('task-input');
  if (inp) inp.value = 'Explain the ' + _ghCurrentRepo.fullName + ' repository — summarize what each module does and identify any issues.';
}

// Load saved token on startup
document.addEventListener('DOMContentLoaded', function() {
  try {
    var saved = localStorage.getItem('gh_token');
    if (saved) { _ghToken = saved; }
  } catch(e) {}
});

// ── Billing ───────────────────────────────────────────────────────────────
var _BILLING_LOCAL_KEY = 'orchestra_customer_id';
function _getBillingId() {
  var id = localStorage.getItem(_BILLING_LOCAL_KEY);
  if (!id) {
    id = 'lcl_' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    localStorage.setItem(_BILLING_LOCAL_KEY, id);
  }
  return id;
}

// Attach X-Customer-Id to every fetch to /api/chat/agentic
var _origFetch = window.fetch;
window.fetch = function(url, opts) {
  if (typeof url === 'string' && url.includes('/api/chat/agentic')) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, {'X-Customer-Id': _getBillingId()});
  }
  return _origFetch.apply(this, [url, opts]).then(function(resp) {
    if (resp.status === 402 && typeof url === 'string' && url.includes('/api/chat')) {
      resp.clone().json().then(function(d) {
        var detail = d.detail || {};
        if (detail.error === 'subscription_required') { showUpgradeModal(); }
      }).catch(function(){});
    }
    return resp;
  });
};

function showUpgradeModal() {
  document.getElementById('upgrade-modal').style.display = 'flex';
}

async function _loadBillingStatus() {
  try {
    var r = await _origFetch('/api/billing/status', {
      headers: {'X-Customer-Id': _getBillingId()}
    });
    var d = await r.json();
    var btn = document.getElementById('billing-btn');
    if (!btn) return;
    if (d.active) {
      btn.textContent = '&#x2726; Pro';
      btn.style.color = '#a78bfa';
      btn.style.borderColor = 'rgba(167,139,250,.5)';
    } else {
      btn.textContent = 'Upgrade';
      btn.style.color = '#f0883e';
      btn.style.borderColor = 'rgba(240,136,46,.4)';
    }
    btn.innerHTML = btn.textContent;
  } catch(e) {
    var btn = document.getElementById('billing-btn');
    if (btn) { btn.textContent = 'Pro'; }
  }
}
_loadBillingStatus();
</script>
<!-- ══ Self-Improve Panel ══ -->
<div id="self-improve-panel" style="display:none;position:fixed;inset:0;z-index:1050;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px)" onclick="if(event.target===this)closeSelfImprove()">
  <div style="position:absolute;right:0;top:0;bottom:0;width:min(680px,100vw);background:#0d1117;border-left:1px solid #30363d;display:flex;flex-direction:column;box-shadow:-8px 0 40px rgba(0,0,0,.6)">
    <!-- Panel header -->
    <div style="padding:1.25rem 1.5rem;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between;flex-shrink:0">
      <div>
        <div style="font-weight:700;font-size:1rem;display:flex;align-items:center;gap:.5rem">
          <span style="color:#a78bfa">&#x1F9E0;</span> Orchestra Self-Improvement
        </div>
        <div id="si-subtitle" style="font-size:.78rem;color:#8b949e;margin-top:.2rem">Analyzing codebase…</div>
      </div>
      <div style="display:flex;align-items:center;gap:.75rem">
        <button onclick="runSelfAnalysis()" id="si-refresh-btn" style="background:#a78bfa;color:#fff;border:none;padding:.4rem 1rem;border-radius:6px;font-size:.8rem;font-weight:600;cursor:pointer">↺ Re-analyze</button>
        <button onclick="closeSelfImprove()" style="background:none;border:none;color:#8b949e;cursor:pointer;font-size:1.2rem;line-height:1">✕</button>
      </div>
    </div>

    <!-- Stats bar -->
    <div id="si-stats" style="display:none;padding:.75rem 1.5rem;border-bottom:1px solid #21262d;display:flex;gap:1.5rem;flex-wrap:wrap;flex-shrink:0;background:#161b22">
      <div><span id="si-stat-files" style="font-weight:700;color:#58a6ff">—</span> <span style="color:#8b949e;font-size:.8rem">Python files</span></div>
      <div><span id="si-stat-routes" style="font-weight:700;color:#58a6ff">—</span> <span style="color:#8b949e;font-size:.8rem">API routes</span></div>
      <div><span id="si-stat-modules" style="font-weight:700;color:#58a6ff">—</span> <span style="color:#8b949e;font-size:.8rem">modules</span></div>
      <div><span id="si-stat-todos" style="font-weight:700;color:#f0883e">—</span> <span style="color:#8b949e;font-size:.8rem">TODOs</span></div>
      <div><span id="si-stat-tests" style="font-weight:700;color:#3fb950">—</span> <span style="color:#8b949e;font-size:.8rem">test files</span></div>
    </div>

    <!-- Suggestions list -->
    <div id="si-body" style="flex:1;overflow-y:auto;padding:1rem 1.25rem">
      <div id="si-loading" style="display:flex;align-items:center;justify-content:center;height:200px;gap:.75rem;color:#8b949e">
        <div style="width:20px;height:20px;border:2px solid #30363d;border-top-color:#a78bfa;border-radius:50%;animation:spin .7s linear infinite"></div>
        Scanning Orchestra's codebase and reasoning about improvements…
      </div>
      <div id="si-suggestions" style="display:none;flex-direction:column;gap:.75rem"></div>
      <div id="si-error" style="display:none;color:#f85149;font-size:.875rem;padding:1rem"></div>
    </div>
  </div>
</div>

<script>
(function(){
  const PRIORITY_COLORS = {critical:'#f85149',high:'#f0883e',medium:'#e3b341',low:'#8b949e'};
  const CATEGORY_ICONS = {ux:'✨',reliability:'🛡',performance:'⚡',security:'🔒',feature:'🚀',quality:'🧹',dx:'🔧'};

  window.openSelfImprove = function() {
    document.getElementById('self-improve-panel').style.display = 'block';
    const sugg = document.getElementById('si-suggestions');
    if (!sugg.hasChildNodes()) runSelfAnalysis();
  };

  window.closeSelfImprove = function() {
    document.getElementById('self-improve-panel').style.display = 'none';
  };

  window.runSelfAnalysis = async function() {
    const loading = document.getElementById('si-loading');
    const sugg = document.getElementById('si-suggestions');
    const errEl = document.getElementById('si-error');
    const statsBar = document.getElementById('si-stats');
    loading.style.display = 'flex';
    sugg.style.display = 'none';
    errEl.style.display = 'none';
    document.getElementById('si-subtitle').textContent = 'Scanning codebase and reasoning about improvements…';
    document.getElementById('si-refresh-btn').disabled = true;

    try {
      const provider = localStorage.getItem('ca_provider') || 'anthropic';
      const model = localStorage.getItem('ca_model') || 'claude-opus-4-7';
      const api_key = localStorage.getItem('ca_api_key') || '';
      const res = await fetch('/api/self/analyze', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({provider, model, api_key})
      });
      const data = await res.json();

      // Populate stats
      const snap = data.snapshot || {};
      document.getElementById('si-stat-files').textContent = snap.total_python_files || '—';
      document.getElementById('si-stat-routes').textContent = snap.api_route_count || '—';
      document.getElementById('si-stat-modules').textContent = Object.keys(snap.module_inventory || {}).length || '—';
      document.getElementById('si-stat-todos').textContent = snap.todo_fixme_count || '0';
      document.getElementById('si-stat-tests').textContent = snap.test_files || '0';
      statsBar.style.display = 'flex';

      if (data.error) {
        errEl.textContent = '⚠ ' + data.error;
        errEl.style.display = 'block';
        document.getElementById('si-subtitle').textContent = 'Error — check API key in Settings';
      } else {
        renderSuggestions(data.suggestions || []);
        const engine = data.engine === 'claude_code' ? 'Claude Code' : (data.engine || 'API');
        document.getElementById('si-subtitle').textContent =
          `${(data.suggestions||[]).length} improvements identified · via ${engine}`;
      }
    } catch(e) {
      errEl.textContent = '⚠ Network error: ' + e.message;
      errEl.style.display = 'block';
      document.getElementById('si-subtitle').textContent = 'Error';
    } finally {
      loading.style.display = 'none';
      document.getElementById('si-refresh-btn').disabled = false;
    }
  };

  function renderSuggestions(suggestions) {
    const container = document.getElementById('si-suggestions');
    container.innerHTML = '';
    if (!suggestions.length) {
      container.innerHTML = '<div style="color:#8b949e;text-align:center;padding:2rem">No suggestions returned.</div>';
    } else {
      suggestions.forEach((s, i) => {
        const pcolor = PRIORITY_COLORS[s.priority] || '#8b949e';
        const icon = CATEGORY_ICONS[s.category] || '💡';
        const card = document.createElement('div');
        card.style.cssText = 'background:#161b22;border:1px solid #21262d;border-radius:10px;padding:1rem;border-left:3px solid '+pcolor;
        card.innerHTML = `
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:.75rem;margin-bottom:.5rem">
            <div style="display:flex;align-items:center;gap:.5rem;flex:1">
              <span style="font-size:1rem">${icon}</span>
              <span style="font-weight:600;font-size:.9rem">${_esc(s.title)}</span>
            </div>
            <div style="display:flex;gap:.35rem;flex-shrink:0">
              <span style="background:${pcolor}22;color:${pcolor};padding:.15rem .5rem;border-radius:12px;font-size:.72rem;font-weight:700;text-transform:uppercase">${s.priority||''}</span>
              <span style="background:#21262d;color:#8b949e;padding:.15rem .5rem;border-radius:12px;font-size:.72rem">${s.effort||''}</span>
            </div>
          </div>
          <div style="color:#8b949e;font-size:.825rem;line-height:1.55;margin-bottom:.75rem">${_esc(s.why)}</div>
          <div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem">
            <span style="font-size:.75rem;color:#58a6ff;background:rgba(88,166,255,.08);padding:.2rem .55rem;border-radius:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%">${_esc(s.area||'')}</span>
            <button onclick="buildImprovement(${i})" style="background:#a78bfa;color:#fff;border:none;padding:.35rem .9rem;border-radius:6px;font-size:.78rem;font-weight:700;cursor:pointer;flex-shrink:0;transition:background .15s" onmouseover="this.style.background='#8b5cf6'" onmouseout="this.style.background='#a78bfa'">
              → Build it
            </button>
          </div>
        `;
        container.appendChild(card);
      });
    }
    container.style.display = 'flex';
    window._siSuggestions = suggestions;
  }

  window.buildImprovement = function(i) {
    const s = (window._siSuggestions||[])[i];
    if (!s) return;
    closeSelfImprove();
    const taskInput = document.getElementById('task-input');
    if (taskInput) {
      taskInput.removeAttribute('disabled');
      taskInput.value = s.prompt || s.title;
      // Auto-resize
      taskInput.style.height = 'auto';
      taskInput.style.height = Math.min(taskInput.scrollHeight, 200) + 'px';
      taskInput.dispatchEvent(new Event('input', {bubbles:true}));
      taskInput.focus();
    }
    const sendBtn = document.getElementById('send-btn');
    if (sendBtn) sendBtn.removeAttribute('disabled');
  };

  function _esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
})();
</script>

<!-- Upgrade / Paywall Modal -->
<div id="upgrade-modal" style="display:none;position:fixed;inset:0;z-index:1100;background:rgba(0,0,0,0.75);backdrop-filter:blur(6px);align-items:center;justify-content:center">
  <div style="background:#161b22;border:1px solid rgba(167,139,250,.4);border-radius:16px;padding:32px 28px;max-width:440px;width:92%;box-shadow:0 24px 64px rgba(0,0,0,.6);text-align:center">
    <div style="font-size:32px;margin-bottom:12px">&#x1F680;</div>
    <div style="font-size:20px;font-weight:800;background:linear-gradient(135deg,#a78bfa,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:8px">Upgrade to Orchestra Pro</div>
    <div style="font-size:13px;color:#8b949e;line-height:1.6;margin-bottom:20px">Executing code requires an active Pro subscription. Agents that write files, run commands, and make real changes to your software are a Pro feature.</div>
    <div style="background:rgba(167,139,250,.08);border:1px solid rgba(167,139,250,.2);border-radius:10px;padding:14px 18px;margin-bottom:20px;font-size:13px;color:#e6edf3;text-align:left">
      <div style="font-weight:700;color:#a78bfa;margin-bottom:8px">Pro — $50 / month</div>
      <div style="display:flex;flex-direction:column;gap:6px;color:#8b949e">
        <div>&#x2713;&ensp;Autonomous code execution &amp; file writes</div>
        <div>&#x2713;&ensp;All agent engines (Claude Code, Codex, OpenClaw)</div>
        <div>&#x2713;&ensp;MCP tools &amp; multi-agent swarms</div>
        <div>&#x2713;&ensp;Full Finance engine &amp; live market data</div>
      </div>
    </div>
    <div style="display:flex;gap:10px;justify-content:center">
      <button onclick="window.open('/billing','_blank')" style="background:linear-gradient(135deg,#7c3aed,#6d28d9);border:none;color:#fff;padding:11px 28px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit">View Plans</button>
      <button onclick="document.getElementById('upgrade-modal').style.display='none'" style="background:#21262d;border:1px solid #30363d;color:#8b949e;padding:11px 20px;border-radius:8px;font-size:14px;cursor:pointer;font-family:inherit">Maybe later</button>
    </div>
  </div>
</div>
<!-- ═══════════════════════════════════════════════════════════════════════
     CODE DIFF PREVIEW PANEL
     ═══════════════════════════════════════════════════════════════════════ -->
<style>
.diff-panel { position:fixed;top:0;right:-560px;width:540px;height:100vh;background:#161b22;border-left:1px solid #30363d;z-index:900;display:flex;flex-direction:column;transition:right .3s cubic-bezier(.4,0,.2,1);box-shadow:-8px 0 32px rgba(0,0,0,.4); }
.diff-panel.open { right:0; }
.diff-panel-header { padding:16px 20px;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between;flex-shrink:0; }
.diff-panel-title { font-size:14px;font-weight:700;color:#e6edf3; }
.diff-panel-close { background:none;border:none;color:#8b949e;cursor:pointer;font-size:18px;line-height:1;padding:0; }
.diff-panel-close:hover { color:#e6edf3; }
.diff-summary { padding:14px 20px;border-bottom:1px solid #21262d;flex-shrink:0; }
.diff-summary-text { font-size:13px;color:#e6edf3;line-height:1.5;margin-bottom:8px; }
.diff-approach { font-size:12px;color:#8b949e;line-height:1.5; }
.diff-meta { display:flex;gap:10px;margin-top:10px;flex-wrap:wrap; }
.diff-badge { font-size:11px;padding:2px 8px;border-radius:8px;font-weight:600; }
.diff-badge.low { background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.25); }
.diff-badge.medium { background:rgba(240,136,46,.12);color:#f0883e;border:1px solid rgba(240,136,46,.25); }
.diff-badge.high { background:rgba(248,81,73,.12);color:#f85149;border:1px solid rgba(248,81,73,.25); }
.diff-badge.lines { background:rgba(88,166,255,.1);color:#58a6ff;border:1px solid rgba(88,166,255,.2); }
.diff-file-tabs { display:flex;gap:0;overflow-x:auto;border-bottom:1px solid #21262d;flex-shrink:0;scrollbar-width:none; }
.diff-file-tab { padding:8px 14px;font-size:11px;color:#8b949e;cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;transition:all .15s;background:none;border-top:none;border-left:none;border-right:none;font-family:inherit; }
.diff-file-tab:hover { color:#e6edf3; }
.diff-file-tab.active { color:#58a6ff;border-bottom-color:#58a6ff; }
.diff-file-tab .tab-action { font-size:9px;margin-left:4px;padding:1px 5px;border-radius:4px;font-weight:700; }
.diff-file-tab .tab-action.modify { background:rgba(240,136,46,.2);color:#f0883e; }
.diff-file-tab .tab-action.create { background:rgba(63,185,80,.2);color:#3fb950; }
.diff-file-tab .tab-action.delete { background:rgba(248,81,73,.2);color:#f85149; }
.diff-content { flex:1;overflow-y:auto;padding:0; }
.diff-file-header { padding:10px 16px;background:#0d1117;border-bottom:1px solid #21262d;font-size:11px;color:#8b949e;font-family:monospace;display:flex;align-items:center;gap:8px; }
.diff-hunk { font-family:'Cascadia Code','Fira Code','JetBrains Mono',monospace;font-size:12px;line-height:1.6; }
.diff-line { display:flex;min-width:0; }
.diff-line-num { width:36px;flex-shrink:0;color:#484f58;padding:0 8px;text-align:right;font-size:11px;user-select:none;border-right:1px solid #21262d; }
.diff-line-code { flex:1;padding:0 10px;white-space:pre;overflow-x:auto; }
.diff-line.add { background:rgba(63,185,80,.08); }
.diff-line.add .diff-line-code { color:#3fb950; }
.diff-line.add .diff-line-code::before { content:'+'; color:rgba(63,185,80,.6);margin-right:4px; }
.diff-line.del { background:rgba(248,81,73,.08); }
.diff-line.del .diff-line-code { color:#f85149; }
.diff-line.del .diff-line-code::before { content:'-'; color:rgba(248,81,73,.6);margin-right:4px; }
.diff-line.ctx .diff-line-code::before { content:' '; margin-right:4px;color:transparent; }
.diff-line.hunk { background:#21262d; }
.diff-line.hunk .diff-line-code { color:#58a6ff;font-size:11px; }
.diff-panel-cta { padding:16px 20px;border-top:1px solid #30363d;flex-shrink:0;background:#161b22; }
.diff-cta-btn { width:100%;padding:12px;background:linear-gradient(135deg,#7c3aed,#6d28d9);border:none;color:#fff;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:opacity .15s; }
.diff-cta-btn:hover { opacity:.9; }
.diff-cta-free { font-size:11px;color:#6e7681;text-align:center;margin-top:8px; }
.diff-empty { display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;gap:12px;color:#8b949e; }
.diff-loading { display:flex;align-items:center;justify-content:center;height:200px;flex-direction:column;gap:12px; }
.diff-spinner { width:28px;height:28px;border:3px solid #30363d;border-top-color:#a78bfa;border-radius:50%;animation:diff-spin .8s linear infinite; }
@keyframes diff-spin { to { transform:rotate(360deg); } }
</style>

<div class="diff-panel" id="diff-panel">
  <div class="diff-panel-header">
    <span class="diff-panel-title">&#x1F50D; Change Preview</span>
    <button class="diff-panel-close" onclick="closeDiffPanel()">&#x2715;</button>
  </div>
  <div id="diff-summary" class="diff-summary" style="display:none"></div>
  <div id="diff-file-tabs" class="diff-file-tabs" style="display:none"></div>
  <div class="diff-content" id="diff-content">
    <div class="diff-loading" id="diff-loading" style="display:none">
      <div class="diff-spinner"></div>
      <div style="font-size:12px;color:#8b949e">Analysing your codebase&#x2026;</div>
    </div>
    <div class="diff-empty" id="diff-empty">
      <div style="font-size:32px">&#x1F4CB;</div>
      <div style="font-size:13px">Type a task and click <strong>Preview</strong><br>to see what the agent would change</div>
    </div>
  </div>
  <div class="diff-panel-cta" id="diff-cta" style="display:none">
    <button class="diff-cta-btn" onclick="applyDiffChanges()">&#x1F680; Apply Changes with Pro</button>
    <div class="diff-cta-free">Pro subscribers can execute this plan &#x2014; <a href="/billing" target="_blank" style="color:#a78bfa">$50/month</a></div>
  </div>
</div>

<script>
var _diffPlanTask = '';

function openDiffPanel() {
  document.getElementById('diff-panel').classList.add('open');
}
function closeDiffPanel() {
  document.getElementById('diff-panel').classList.remove('open');
}

async function runPreview() {
  var task = (document.getElementById('task-input') || {}).value || '';
  task = task.trim();
  if (!task) { showToast('Enter a task first', 'warning'); return; }

  _diffPlanTask = task;
  openDiffPanel();

  // Hide empty/summary, show loading
  document.getElementById('diff-empty').style.display = 'none';
  document.getElementById('diff-loading').style.display = 'flex';
  document.getElementById('diff-summary').style.display = 'none';
  document.getElementById('diff-file-tabs').style.display = 'none';
  document.getElementById('diff-cta').style.display = 'none';
  document.getElementById('diff-content').innerHTML = '<div class="diff-loading" id="diff-loading"><div class="diff-spinner"></div><div style="font-size:12px;color:#8b949e">Analysing your codebase&#x2026;</div></div>';

  try {
    var r = await window._origFetch ? window._origFetch('/api/chat/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task: task,
        workspace: typeof _workspace !== 'undefined' ? _workspace : '',
        provider: (document.getElementById('provider') || {}).value || 'anthropic',
        model: (document.getElementById('model') || {}).value || 'claude-opus-4-7',
        api_key: (document.getElementById('api-key') || {}).value || '',
      })
    }) : await fetch('/api/chat/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: task, workspace: typeof _workspace !== 'undefined' ? _workspace : '' })
    });

    var d = await r.json();
    if (!r.ok) { throw new Error(d.detail || 'Preview failed'); }
    renderDiffPlan(d.plan);
  } catch(e) {
    document.getElementById('diff-content').innerHTML =
      '<div class="diff-empty"><div style="font-size:28px">&#x26A0;</div><div style="font-size:13px;text-align:center">Could not generate preview:<br><span style="color:#f85149">'+e.message+'</span></div></div>';
  }
}

function renderDiffPlan(plan) {
  if (!plan) return;

  // Summary block
  var summaryEl = document.getElementById('diff-summary');
  var riskClass = (plan.risk || 'low').toLowerCase();
  summaryEl.innerHTML =
    '<div class="diff-summary-text">' + _esc(plan.summary || '') + '</div>'
    + (plan.approach ? '<div class="diff-approach">' + _esc(plan.approach) + '</div>' : '')
    + '<div class="diff-meta">'
    + '<span class="diff-badge ' + riskClass + '">risk: ' + (plan.risk || 'low') + '</span>'
    + (plan.estimated_lines_changed ? '<span class="diff-badge lines">~' + plan.estimated_lines_changed + ' lines</span>' : '')
    + '<span class="diff-badge lines">' + (plan.files || []).length + ' file' + ((plan.files||[]).length===1?'':'s') + '</span>'
    + '</div>';
  summaryEl.style.display = '';

  var files = plan.files || [];
  if (!files.length) {
    document.getElementById('diff-content').innerHTML = '<div class="diff-empty"><div style="font-size:28px">&#x2139;</div><div style="font-size:13px">No specific file changes identified.</div></div>';
    document.getElementById('diff-cta').style.display = '';
    return;
  }

  // File tabs
  var tabsEl = document.getElementById('diff-file-tabs');
  tabsEl.innerHTML = files.map(function(f, i) {
    var name = (f.path || 'file').split('/').pop().split('\\').pop();
    var actionClass = (f.action || 'modify').toLowerCase();
    return '<button class="diff-file-tab'+(i===0?' active':'')+'" onclick="showDiffFile('+i+')" id="dtab-'+i+'">'
      + name
      + '<span class="tab-action '+actionClass+'">'+actionClass+'</span>'
      + '</button>';
  }).join('');
  tabsEl.style.display = '';

  // Render first file
  window._diffFiles = files;
  showDiffFile(0);
  document.getElementById('diff-cta').style.display = '';
}

function showDiffFile(idx) {
  var files = window._diffFiles || [];
  var f = files[idx];
  if (!f) return;

  // Update tabs
  files.forEach(function(_, i) {
    var t = document.getElementById('dtab-' + i);
    if (t) t.className = 'diff-file-tab' + (i === idx ? ' active' : '');
  });

  var html = '<div class="diff-file-header">&#x1F4C4;&ensp;' + _esc(f.path || '') + '&ensp;<span style="color:#484f58">' + _esc(f.description || '') + '</span></div>';
  html += '<div class="diff-hunk">';

  if (f.diff) {
    var lines = f.diff.split('\n');
    var lineNum = 1;
    lines.forEach(function(line) {
      if (line.startsWith('@@')) {
        html += '<div class="diff-line hunk"><div class="diff-line-num"></div><div class="diff-line-code">' + _esc(line) + '</div></div>';
      } else if (line.startsWith('+')) {
        html += '<div class="diff-line add"><div class="diff-line-num">'+(lineNum++)+'</div><div class="diff-line-code">' + _esc(line.slice(1)) + '</div></div>';
      } else if (line.startsWith('-')) {
        html += '<div class="diff-line del"><div class="diff-line-num"></div><div class="diff-line-code">' + _esc(line.slice(1)) + '</div></div>';
      } else {
        html += '<div class="diff-line ctx"><div class="diff-line-num">'+(lineNum++)+'</div><div class="diff-line-code">' + _esc(line) + '</div></div>';
      }
    });
  } else {
    html += '<div style="padding:16px;color:#8b949e;font-size:12px">' + _esc(f.description || 'No diff available.') + '</div>';
  }
  html += '</div>';

  document.getElementById('diff-content').innerHTML = html;
}

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function applyDiffChanges() {
  // Pro users execute; free users see upgrade
  closeDiffPanel();
  if (_diffPlanTask) {
    document.getElementById('task-input').value = _diffPlanTask;
    sendTask();
  }
}

// Show Preview button only when engine is agentic
(function() {
  function _updatePreviewBtn() {
    var engEl = document.getElementById('engine');
    var btn = document.getElementById('preview-btn');
    if (!engEl || !btn) return;
    var isAgentic = ['claude_code','opencode','auto','openclaw','codex'].indexOf(engEl.value) >= 0;
    btn.style.display = isAgentic ? '' : 'none';
  }
  document.addEventListener('DOMContentLoaded', function() {
    var eng = document.getElementById('engine');
    if (eng) eng.addEventListener('change', _updatePreviewBtn);
    _updatePreviewBtn();
  });
})();
</script>
<!-- ═══════════════════════════════════════════════════════════════════════
     ONBOARDING MODAL
     ═══════════════════════════════════════════════════════════════════════ -->
<style>
.ob-overlay { position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.85);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;padding:16px; }
.ob-card { background:#161b22;border:1px solid #30363d;border-radius:20px;width:100%;max-width:560px;overflow:hidden;box-shadow:0 32px 80px rgba(0,0,0,.7); }
.ob-header { padding:32px 32px 0; }
.ob-steps { display:flex;gap:6px;margin-bottom:20px; }
.ob-step-dot { flex:1;height:3px;border-radius:3px;background:#21262d;transition:background .3s; }
.ob-step-dot.done { background:#3fb950; }
.ob-step-dot.active { background:#a78bfa; }
.ob-icon { font-size:36px;margin-bottom:8px; }
.ob-title { font-size:22px;font-weight:800;color:#e6edf3;margin-bottom:6px;line-height:1.2; }
.ob-sub { font-size:13px;color:#8b949e;line-height:1.6;margin-bottom:0; }
.ob-body { padding:24px 32px;min-height:180px; }
.ob-footer { padding:16px 32px 28px;display:flex;align-items:center;justify-content:space-between; }
.ob-btn-primary { background:linear-gradient(135deg,#7c3aed,#6d28d9);border:none;color:#fff;padding:11px 28px;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:opacity .15s,transform .15s; }
.ob-btn-primary:hover { opacity:.9;transform:translateY(-1px); }
.ob-btn-primary:disabled { opacity:.45;cursor:not-allowed;transform:none; }
.ob-btn-skip { background:none;border:none;color:#8b949e;font-size:13px;cursor:pointer;font-family:inherit;padding:0; }
.ob-btn-skip:hover { color:#e6edf3; }
.ob-btn-back { background:none;border:none;color:#8b949e;font-size:13px;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:4px; }
.ob-btn-back:hover { color:#e6edf3; }
.ob-provider-grid { display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px; }
.ob-provider-card { background:#21262d;border:2px solid #30363d;border-radius:12px;padding:14px 16px;cursor:pointer;transition:border-color .15s,background .15s;display:flex;align-items:center;gap:10px; }
.ob-provider-card:hover { background:#2d333b;border-color:#6e7681; }
.ob-provider-card.selected { border-color:#a78bfa;background:rgba(167,139,250,.08); }
.ob-provider-card .logo { font-size:20px;flex-shrink:0; }
.ob-provider-card .info { min-width:0; }
.ob-provider-card .name { font-size:13px;font-weight:700;color:#e6edf3; }
.ob-provider-card .desc { font-size:11px;color:#8b949e;margin-top:1px; }
.ob-input { width:100%;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 14px;color:#e6edf3;font-size:13px;font-family:inherit;outline:none;transition:border-color .15s;margin-bottom:10px; }
.ob-input:focus { border-color:#a78bfa; }
.ob-input::placeholder { color:#484f58; }
.ob-label { font-size:12px;color:#8b949e;margin-bottom:6px;display:block; }
.ob-key-hint { font-size:11px;color:#6e7681;margin-top:-6px;margin-bottom:12px; }
.ob-key-hint a { color:#a78bfa; }
.ob-prompt-grid { display:grid;grid-template-columns:1fr 1fr;gap:8px; }
.ob-prompt-card { background:#21262d;border:1px solid #30363d;border-radius:10px;padding:12px 14px;cursor:pointer;transition:border-color .15s,background .15s;text-align:left;font-family:inherit; }
.ob-prompt-card:hover { background:#2d333b;border-color:#58a6ff; }
.ob-prompt-card .emoji { font-size:18px;display:block;margin-bottom:6px; }
.ob-prompt-card .text { font-size:12px;color:#e6edf3;line-height:1.4; }
.ob-ws-row { display:flex;gap:8px;align-items:stretch;margin-bottom:10px; }
.ob-ws-row .ob-input { margin-bottom:0;flex:1; }
.ob-ws-btn { background:#21262d;border:1px solid #30363d;color:#8b949e;padding:0 14px;border-radius:8px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap; }
.ob-ws-btn:hover { background:#2d333b;color:#e6edf3; }
.ob-ws-hint { font-size:11px;color:#6e7681;margin-bottom:12px; }
.ob-ws-hint.valid { color:#3fb950; }
.ob-ws-hint.invalid { color:#f85149; }
</style>

<div class="ob-overlay" id="ob-overlay" style="display:none">
  <div class="ob-card" id="ob-card">
    <!-- Header (always visible) -->
    <div class="ob-header">
      <div class="ob-steps">
        <div class="ob-step-dot active" id="ob-dot-0"></div>
        <div class="ob-step-dot" id="ob-dot-1"></div>
        <div class="ob-step-dot" id="ob-dot-2"></div>
        <div class="ob-step-dot" id="ob-dot-3"></div>
      </div>
      <div id="ob-icon" class="ob-icon">&#x1F3BC;</div>
      <div id="ob-title" class="ob-title">Welcome to Orchestra</div>
      <div id="ob-sub" class="ob-sub">Your autonomous coding agent. Let&#x2019;s get you set up in 60 seconds.</div>
    </div>

    <!-- Body (changes per step) -->
    <div class="ob-body" id="ob-body"></div>

    <!-- Footer -->
    <div class="ob-footer">
      <div id="ob-left">
        <button class="ob-btn-back" id="ob-back" onclick="obBack()" style="display:none">&#x2190; Back</button>
      </div>
      <div style="display:flex;gap:12px;align-items:center">
        <button class="ob-btn-skip" id="ob-skip" onclick="obSkip()">Skip setup</button>
        <button class="ob-btn-primary" id="ob-next" onclick="obNext()">Get started &#x2192;</button>
      </div>
    </div>
  </div>
</div>

<script>
// ── Onboarding state ──────────────────────────────────────────────────────────
var _obStep = 0;
var _obTotalSteps = 4;
var _obData = { provider: 'anthropic', model: 'claude-opus-4-7', apiKey: '', workspace: '' };

var _obSteps = [
  {
    icon: '&#x1F3BC;',
    title: 'Welcome to Orchestra',
    sub: 'Your autonomous coding agent. Let&#x2019;s get you set up in 60 seconds.',
    nextLabel: 'Get started &#x2192;',
    showSkip: true,
    render: function() { return '<div style="display:flex;flex-direction:column;gap:10px">'
      + '<div style="background:rgba(167,139,250,.08);border:1px solid rgba(167,139,250,.2);border-radius:12px;padding:16px 18px;display:flex;gap:14px;align-items:flex-start">'
        + '<span style="font-size:22px;flex-shrink:0">&#x1F916;</span>'
        + '<div><div style="font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:4px">Autonomous code execution</div><div style="font-size:12px;color:#8b949e;line-height:1.5">Orchestra agents read your codebase, plan changes, write code, run tests, and commit — all on their own.</div></div>'
      + '</div>'
      + '<div style="background:rgba(63,185,80,.06);border:1px solid rgba(63,185,80,.2);border-radius:12px;padding:16px 18px;display:flex;gap:14px;align-items:flex-start">'
        + '<span style="font-size:22px;flex-shrink:0">&#x1F4CA;</span>'
        + '<div><div style="font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:4px">Finance &amp; market intelligence</div><div style="font-size:12px;color:#8b949e;line-height:1.5">Built-in double-entry ledger, real-time market data, AI-powered CFO insights.</div></div>'
      + '</div>'
      + '<div style="background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.2);border-radius:12px;padding:16px 18px;display:flex;gap:14px;align-items:flex-start">'
        + '<span style="font-size:22px;flex-shrink:0">&#x1F50C;</span>'
        + '<div><div style="font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:4px">MCP ecosystem</div><div style="font-size:12px;color:#8b949e;line-height:1.5">Connect any MCP server — filesystem, browser, databases, search and more.</div></div>'
      + '</div>'
      + '</div>'; }
  },
  {
    icon: '&#x1F9E0;',
    title: 'Choose your AI model',
    sub: 'Pick a provider and paste your API key. You can change this any time.',
    nextLabel: 'Continue &#x2192;',
    showSkip: true,
    render: function() {
      var providers = [
        { id:'anthropic', logo:'&#x1F7E3;', name:'Anthropic', desc:'Claude Opus, Sonnet, Haiku', models:['claude-opus-4-7','claude-sonnet-4-6','claude-haiku-4-5-20251001'] },
        { id:'openai',    logo:'&#x1F7E2;', name:'OpenAI',    desc:'GPT-4o, o1, o3-mini', models:['gpt-4o','gpt-4o-mini','o1','o3-mini'] },
        { id:'ollama',    logo:'&#x1F7E4;', name:'Ollama',    desc:'Local models — no key needed', models:['llama3.2','llama3.1','gemma3','phi4','deepseek-r1:8b','nemotron-mini'] },
        { id:'openrouter',logo:'&#x1F535;', name:'OpenRouter',desc:'100+ models via one key', models:['openai/gpt-4o','anthropic/claude-opus-4','meta-llama/llama-3.1-70b'] },
      ];
      var html = '<div class="ob-provider-grid" id="ob-providers">';
      providers.forEach(function(p) {
        var sel = _obData.provider === p.id ? ' selected' : '';
        html += '<div class="ob-provider-card'+sel+'" onclick="obSelectProvider(\''+p.id+'\','+JSON.stringify(p.models)+')" data-pid="'+p.id+'">'
          + '<div class="logo">'+p.logo+'</div>'
          + '<div class="info"><div class="name">'+p.name+'</div><div class="desc">'+p.desc+'</div></div>'
          + '</div>';
      });
      html += '</div>';
      var noKeyNeeded = _obData.provider === 'ollama';
      html += '<label class="ob-label" for="ob-api-key">API Key'+(noKeyNeeded ? ' <span style="color:#3fb950;font-size:10px">(not required for Ollama)</span>':' <span style="color:#f85149;font-size:10px">*</span>')+'</label>';
      html += '<input class="ob-input" id="ob-api-key" type="password" placeholder="'+(noKeyNeeded?'Not required — leave blank':'sk-ant-... or sk-... or your key')+'" value="'+(_obData.apiKey||'')+'" oninput="_obData.apiKey=this.value">';
      if (!noKeyNeeded) {
        var links = { anthropic:'https://console.anthropic.com/settings/keys', openai:'https://platform.openai.com/api-keys', openrouter:'https://openrouter.ai/keys' };
        html += '<div class="ob-key-hint">Get your key at <a href="'+(links[_obData.provider]||'#')+'" target="_blank">'+(_obData.provider)+' dashboard</a>.</div>';
      }
      return html;
    }
  },
  {
    icon: '&#x1F4C1;',
    title: 'Connect your codebase',
    sub: 'Tell Orchestra where your project lives. Agents will read and write files here.',
    nextLabel: 'Continue &#x2192;',
    showSkip: true,
    render: function() {
      return '<label class="ob-label">Project folder path</label>'
        + '<div class="ob-ws-row">'
        + '<input class="ob-input" id="ob-ws-input" type="text" placeholder="e.g. C:\\\\Users\\\\you\\\\myproject or /home/you/myproject" value="'+(_obData.workspace||'')+'" oninput="obValidateWs(this.value)">'
        + '</div>'
        + '<div class="ob-ws-hint" id="ob-ws-hint">Paste the full path to your project root.</div>'
        + '<div style="margin-top:16px;background:#21262d;border:1px solid #30363d;border-radius:10px;padding:14px 16px">'
        + '<div style="font-size:12px;font-weight:600;color:#8b949e;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px">&#x1F4A1; Tips</div>'
        + '<div style="display:flex;flex-direction:column;gap:8px;font-size:12px;color:#6e7681">'
        + '<div>&#x2022;&ensp;Agents can read any file inside this folder</div>'
        + '<div>&#x2022;&ensp;Pro subscribers can write &amp; commit changes</div>'
        + '<div>&#x2022;&ensp;You can change this any time from the Files tab</div>'
        + '</div></div>';
    }
  },
  {
    icon: '&#x1F680;',
    title: 'Try your first task',
    sub: 'Pick a prompt or type your own. Orchestra will handle the rest.',
    nextLabel: '&#x1F680; Launch Orchestra',
    showSkip: false,
    render: function() {
      var prompts = [
        { emoji:'&#x1F50D;', text:'Explain my codebase — what does each module do?' },
        { emoji:'&#x1F41B;', text:'Find and fix any obvious bugs in my code' },
        { emoji:'&#x274C;', text:'Add error handling and input validation throughout' },
        { emoji:'&#x1F9EA;', text:'Write unit tests for my core functions' },
        { emoji:'&#x26A1;', text:'Refactor this for better performance and readability' },
        { emoji:'&#x1F4DD;', text:'Generate comprehensive documentation for my project' },
      ];
      var html = '<div class="ob-prompt-grid">';
      prompts.forEach(function(p, i) {
        html += '<button class="ob-prompt-card" onclick="obPickPrompt(this,'+i+')" data-text="'+p.text.replace(/"/g,\'&quot;\')+'">'
          + '<span class="emoji">'+p.emoji+'</span>'
          + '<span class="text">'+p.text+'</span>'
          + '</button>';
      });
      html += '</div>';
      html += '<input class="ob-input" id="ob-custom-prompt" type="text" placeholder="Or describe your own task&#x2026;" style="margin-top:10px">';
      return html;
    }
  }
];

function showOnboarding() {
  _obStep = 0;
  document.getElementById('ob-overlay').style.display = 'flex';
  obRender();
}

function obRender() {
  var s = _obSteps[_obStep];
  document.getElementById('ob-icon').innerHTML = s.icon;
  document.getElementById('ob-title').textContent = s.title.replace(/&#x[^;]+;/g, '');
  document.getElementById('ob-title').innerHTML = s.title;
  document.getElementById('ob-sub').innerHTML = s.sub;
  document.getElementById('ob-body').innerHTML = s.render();
  document.getElementById('ob-next').innerHTML = s.nextLabel;
  document.getElementById('ob-skip').style.display = s.showSkip ? '' : 'none';
  document.getElementById('ob-back').style.display = _obStep > 0 ? '' : 'none';

  // Update step dots
  for (var i = 0; i < _obTotalSteps; i++) {
    var dot = document.getElementById('ob-dot-' + i);
    if (!dot) continue;
    dot.className = 'ob-step-dot' + (i < _obStep ? ' done' : i === _obStep ? ' active' : '');
  }

  // Auto-focus first input
  setTimeout(function() {
    var inp = document.querySelector('#ob-body input');
    if (inp && inp.type !== 'hidden') inp.focus();
  }, 100);
}

function obSelectProvider(pid, models) {
  _obData.provider = pid;
  _obData.model = models[0];
  _obData.apiKey = '';
  // Re-render step
  document.getElementById('ob-body').innerHTML = _obSteps[_obStep].render();
}

function obValidateWs(val) {
  _obData.workspace = val;
  var hint = document.getElementById('ob-ws-hint');
  if (!val) { hint.textContent = 'Paste the full path to your project root.'; hint.className='ob-ws-hint'; return; }
  // Basic validation — just check it looks like a path
  var looksLike = /^([a-zA-Z]:\\|\/|\~)/.test(val.trim());
  if (looksLike) { hint.innerHTML = '&#x2713; Looks good. Agents will work in this folder.'; hint.className='ob-ws-hint valid'; }
  else { hint.innerHTML = '&#x26A0; Should be an absolute path (e.g. C:\\\\Users\\\\you\\\\project)'; hint.className='ob-ws-hint invalid'; }
}

var _obChosenPrompt = '';
function obPickPrompt(el, idx) {
  document.querySelectorAll('.ob-prompt-card').forEach(function(c) { c.style.borderColor=''; c.style.background=''; });
  el.style.borderColor = '#58a6ff';
  el.style.background = 'rgba(88,166,255,.08)';
  _obChosenPrompt = el.dataset.text;
}

function obBack() {
  if (_obStep > 0) { _obStep--; obRender(); }
}

function obSkip() {
  obFinish(true);
}

function obNext() {
  // Collect data from current step
  if (_obStep === 1) {
    var keyEl = document.getElementById('ob-api-key');
    if (keyEl) _obData.apiKey = keyEl.value.trim();
  }
  if (_obStep === 2) {
    var wsEl = document.getElementById('ob-ws-input');
    if (wsEl) _obData.workspace = wsEl.value.trim();
  }

  if (_obStep < _obTotalSteps - 1) {
    _obStep++;
    obRender();
  } else {
    // Last step — collect prompt and finish
    var customEl = document.getElementById('ob-custom-prompt');
    if (customEl && customEl.value.trim()) _obChosenPrompt = customEl.value.trim();
    obFinish(false);
  }
}

function obFinish(skipped) {
  // Apply config to main UI
  try {
    if (_obData.provider) {
      document.getElementById('provider').value = _obData.provider;
      filterModelByProvider(_obData.provider);
    }
    if (_obData.model) {
      var modelEl = document.getElementById('model');
      if (modelEl) { modelEl.value = _obData.model; }
    }
    if (_obData.apiKey) {
      document.getElementById('api-key').value = _obData.apiKey;
    }
    if (_obData.workspace) {
      _workspace = _obData.workspace;
      updateWorkspaceBadge();
    }
    saveConfig();
    // Switch engine to agentic if Anthropic/OpenAI
    if (_obData.provider === 'anthropic' || _obData.provider === 'openai' || _obData.provider === 'openrouter') {
      var engEl = document.getElementById('engine');
      if (engEl && (engEl.value === 'direct')) {
        engEl.value = 'auto';
        saveConfig(); syncPreset();
      }
    }
  } catch(e) {}

  // Mark onboarded
  try { localStorage.setItem('orchestra_onboarded', '1'); } catch(e) {}

  // Close modal
  document.getElementById('ob-overlay').style.display = 'none';

  // Fire first task if one was chosen
  if (!skipped && _obChosenPrompt) {
    var inp = document.getElementById('task-input');
    if (inp) {
      inp.value = _obChosenPrompt;
      adjustTextarea && adjustTextarea.call(inp);
      setTimeout(function() { sendTask && sendTask(); }, 200);
    }
  } else {
    showToast('Setup complete! Orchestra is ready.', 'success');
  }
}
</script>
<!-- MCP Servers Panel -->
<div id="mcp-modal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,0.7);backdrop-filter:blur(4px);align-items:center;justify-content:center">
  <div style="background:var(--bg-elevated);border:1px solid var(--border-accent);border-radius:16px;padding:24px;max-width:680px;width:94%;max-height:80vh;display:flex;flex-direction:column;box-shadow:var(--shadow-lg)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div>
        <div style="font-size:15px;font-weight:700;color:#a78bfa">&#x1F50C; MCP Servers</div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:2px">Model Context Protocol — dynamic tool sources for Orchestra agents</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <button onclick="mcpConnectAll()" style="background:rgba(124,58,237,.15);border:1px solid rgba(124,58,237,.4);color:#a78bfa;padding:5px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit">Connect All</button>
        <button onclick="document.getElementById('mcp-modal').style.display='none'" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:18px;line-height:1">&#x2715;</button>
      </div>
    </div>
    <div id="mcp-server-list" style="overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:2px">
      <div style="color:var(--text-secondary);font-size:12px;text-align:center;padding:24px">Loading servers&#x2026;</div>
    </div>
  </div>
</div>
<script>
function openMCPPanel() {
  document.getElementById('mcp-modal').style.display = 'flex';
  loadMCPStatus();
}

async function loadMCPStatus() {
  var list = document.getElementById('mcp-server-list');
  try {
    var r = await fetch('/api/mcp/status');
    var d = await r.json();
    renderMCPServers(d.servers || []);
  } catch(e) {
    list.innerHTML = '<div style="color:var(--accent-red);font-size:12px;text-align:center;padding:16px">Could not load MCP status: '+e.message+'</div>';
  }
}

function renderMCPServers(servers) {
  var list = document.getElementById('mcp-server-list');
  if (!servers.length) { list.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;text-align:center;padding:24px">No MCP servers configured.</div>'; return; }
  list.innerHTML = servers.map(function(s) {
    var dot = s.connected ? '#3fb950' : (s.ready ? '#f0883e' : '#6e7681');
    var dotTitle = s.connected ? 'Connected' : (s.ready ? 'Ready — click Connect' : 'Missing API key');
    var keyWarning = s.needs_keys && s.needs_keys.length ? '<div style="font-size:10px;color:#f0883e;margin-top:3px">Needs: '+s.needs_keys.join(', ')+'</div>' : '';
    var toolBadge = s.connected ? '<span style="font-size:10px;background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.25);border-radius:10px;padding:1px 7px;margin-left:6px">'+s.tool_count+' tools</span>' : '';
    var errMsg = s.error ? '<div style="font-size:10px;color:var(--accent-red);margin-top:3px;word-break:break-all">'+s.error+'</div>' : '';
    var connectBtn = !s.connected ? '<button onclick="mcpConnect(\''+s.name+'\')" style="flex-shrink:0;background:rgba(124,58,237,.1);border:1px solid rgba(124,58,237,.3);color:#a78bfa;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit">'+(s.ready?'Connect':'Set Key')+'</button>' : '<button onclick="mcpDisconnect(\''+s.name+'\')" style="flex-shrink:0;background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.25);color:#f85149;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit">Disconnect</button>';
    return '<div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:10px;padding:12px 14px;display:flex;align-items:flex-start;gap:10px">'
      +'<div style="margin-top:3px;width:8px;height:8px;border-radius:50%;background:'+dot+';flex-shrink:0" title="'+dotTitle+'"></div>'
      +'<div style="flex:1;min-width:0">'
        +'<div style="display:flex;align-items:center;gap:6px"><span style="font-size:13px;font-weight:600;color:var(--text-primary)">'+s.name+'</span>'+toolBadge+'</div>'
        +'<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">'+s.description+'</div>'
        +keyWarning+errMsg
      +'</div>'
      +connectBtn
      +'</div>';
  }).join('');
}

async function mcpConnect(name) {
  var r = await fetch('/api/mcp/connect/'+name, {method:'POST'});
  await loadMCPStatus();
}

async function mcpDisconnect(name) {
  await fetch('/api/mcp/disconnect/'+name, {method:'POST'});
  await loadMCPStatus();
}

async function mcpConnectAll() {
  document.getElementById('mcp-server-list').innerHTML = '<div style="color:var(--text-secondary);font-size:12px;text-align:center;padding:24px">Connecting&#x2026; (this may take a moment while packages install)</div>';
  await fetch('/api/mcp/connect', {method:'POST'});
  await loadMCPStatus();
}
</script>
<!-- Self-Improve Modal -->
<div id="self-improve-modal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,0.7);backdrop-filter:blur(4px);align-items:center;justify-content:center">
  <div style="background:var(--bg-elevated);border:1px solid var(--border-accent);border-radius:16px;padding:24px;max-width:520px;width:90%;box-shadow:var(--shadow-lg)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div>
        <div style="font-size:15px;font-weight:700;color:var(--accent-purple)">&#x1F527; Self-Improve Orchestra</div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:2px">Claude Code will work directly on Orchestra&#x27;s source code</div>
      </div>
      <button onclick="document.getElementById('self-improve-modal').style.display='none'" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:18px;line-height:1">&#x2715;</button>
    </div>
    <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px">What should Orchestra improve about itself?</div>
    <textarea id="self-improve-input" rows="4" placeholder="e.g. Add a dark mode toggle, fix the file browser, add a keyboard shortcut to send, improve the UI design..." style="width:100%;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:10px 12px;color:var(--text-primary);font-size:13px;font-family:inherit;resize:vertical;min-height:90px;outline:none"></textarea>
    <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
      <button onclick="runSelfImprove()" style="background:linear-gradient(135deg,#8957e5,#6e40c9);border:none;color:#fff;padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit">&#x1F680; Run Improvement</button>
      <button onclick="runSelfImprove('analyze')" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary);padding:8px 14px;border-radius:8px;font-size:12px;cursor:pointer;font-family:inherit">Analyze only</button>
      <span id="self-improve-ws" style="margin-left:auto;font-size:10px;color:var(--text-secondary)"></span>
    </div>
  </div>
</div>
<div id="toast-container"></div>

<!-- ══ Logs & Errors Panel ══ -->
<div id="logs-panel" style="display:none;position:fixed;inset:0;z-index:1060;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px)" onclick="if(event.target===this)closeLogsPanel()">
  <div style="position:absolute;right:0;top:0;bottom:0;width:min(820px,100vw);background:#0d1117;border-left:1px solid #30363d;display:flex;flex-direction:column;box-shadow:-8px 0 40px rgba(0,0,0,.6)">

    <!-- Header -->
    <div style="padding:1rem 1.5rem;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:1rem">
      <div style="display:flex;align-items:center;gap:.75rem;min-width:0">
        <span style="font-size:1.1rem">📋</span>
        <div>
          <div style="font-weight:700;font-size:.95rem;color:#fff">Logs & Errors</div>
          <div id="logs-subtitle" style="font-size:.75rem;color:#8b949e;margin-top:.1rem">Loading…</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:.5rem;flex-shrink:0">
        <button id="logs-autorefresh-btn" onclick="toggleLogsAutoRefresh()" style="background:none;border:1px solid #30363d;color:#58a6ff;padding:.3rem .7rem;border-radius:6px;font-size:.75rem;cursor:pointer" title="Toggle auto-refresh">⟳ Live</button>
        <button onclick="clearLogs()" style="background:none;border:1px solid rgba(248,81,73,.4);color:#f85149;padding:.3rem .7rem;border-radius:6px;font-size:.75rem;cursor:pointer">Clear</button>
        <button onclick="closeLogsPanel()" style="background:none;border:none;color:#8b949e;cursor:pointer;font-size:1.2rem;line-height:1;padding:.2rem .4rem">✕</button>
      </div>
    </div>

    <!-- Stats bar -->
    <div id="logs-stats-bar" style="padding:.6rem 1.5rem;border-bottom:1px solid #21262d;display:flex;gap:1.5rem;flex-wrap:wrap;background:#161b22;font-size:.78rem;flex-shrink:0">
      <span><b id="ls-total" style="color:#c9d1d9">—</b> <span style="color:#8b949e">total</span></span>
      <span><b id="ls-err" style="color:#f85149">—</b> <span style="color:#8b949e">errors</span></span>
      <span><b id="ls-warn" style="color:#f0883e">—</b> <span style="color:#8b949e">warnings</span></span>
      <span><b id="ls-crit" style="color:#ff6b6b">—</b> <span style="color:#8b949e">critical</span></span>
      <span><b id="ls-1h" style="color:#f85149">—</b> <span style="color:#8b949e">errors/hr</span></span>
      <span style="margin-left:auto;color:#8b949e" id="ls-uptime"></span>
    </div>

    <!-- Filters -->
    <div style="padding:.75rem 1.5rem;border-bottom:1px solid #21262d;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;flex-shrink:0">
      <select id="logs-filter-level" onchange="loadLogs()" style="background:#161b22;border:1px solid #30363d;color:#c9d1d9;padding:.35rem .6rem;border-radius:6px;font-size:.8rem">
        <option value="">All levels</option>
        <option value="CRITICAL">Critical</option>
        <option value="ERROR">Error</option>
        <option value="WARNING">Warning</option>
        <option value="INFO">Info</option>
        <option value="DEBUG">Debug</option>
      </select>
      <select id="logs-filter-source" onchange="loadLogs()" style="background:#161b22;border:1px solid #30363d;color:#c9d1d9;padding:.35rem .6rem;border-radius:6px;font-size:.8rem;max-width:200px">
        <option value="">All sources</option>
      </select>
      <input id="logs-search" placeholder="Search messages…" oninput="loadLogs()" style="background:#161b22;border:1px solid #30363d;color:#c9d1d9;padding:.35rem .7rem;border-radius:6px;font-size:.8rem;flex:1;min-width:150px;font-family:inherit">
      <button onclick="loadLogs()" style="background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:.35rem .75rem;border-radius:6px;font-size:.8rem;cursor:pointer">Refresh</button>
    </div>

    <!-- Log list -->
    <div id="logs-body" style="flex:1;overflow-y:auto;padding:.5rem 0;font-family:monospace;font-size:.78rem"></div>
  </div>
</div>

<script>
(function(){
  let _logsOpen = false;
  let _logsTimer = null;
  let _logsAutoRefresh = true;
  let _logsSources = [];

  const LEVEL_COLOR = {
    CRITICAL: '#ff6b6b', ERROR: '#f85149', WARNING: '#f0883e',
    INFO: '#58a6ff', DEBUG: '#8b949e',
  };

  window.openLogsPanel = function() {
    _logsOpen = true;
    document.getElementById('logs-panel').style.display = 'block';
    loadLogs();
    loadStats();
    if (_logsAutoRefresh) startLogsTimer();
  };

  window.closeLogsPanel = function() {
    _logsOpen = false;
    document.getElementById('logs-panel').style.display = 'none';
    stopLogsTimer();
  };

  window.toggleLogsAutoRefresh = function() {
    _logsAutoRefresh = !_logsAutoRefresh;
    const btn = document.getElementById('logs-autorefresh-btn');
    btn.style.color = _logsAutoRefresh ? '#58a6ff' : '#8b949e';
    btn.style.borderColor = _logsAutoRefresh ? '#58a6ff' : '#30363d';
    if (_logsAutoRefresh) startLogsTimer(); else stopLogsTimer();
  };

  function startLogsTimer() {
    stopLogsTimer();
    _logsTimer = setInterval(() => { if (_logsOpen) { loadLogs(); loadStats(); } }, 4000);
  }
  function stopLogsTimer() {
    if (_logsTimer) { clearInterval(_logsTimer); _logsTimer = null; }
  }

  window.loadLogs = async function() {
    const level = document.getElementById('logs-filter-level').value;
    const source = document.getElementById('logs-filter-source').value;
    const search = document.getElementById('logs-search').value;
    const params = new URLSearchParams({ limit: 300 });
    if (level) params.set('level', level);
    if (source) params.set('source', source);
    if (search) params.set('search', search);

    try {
      const r = await fetch('/api/logs?' + params.toString());
      if (!r.ok) return;
      const data = await r.json();
      renderLogs(data.events || []);
      document.getElementById('logs-subtitle').textContent =
        `${data.count} events${level||source||search ? ' (filtered)' : ''}`;
    } catch(e) {
      document.getElementById('logs-subtitle').textContent = 'Error loading logs';
    }
  };

  window.loadStats = async function() {
    try {
      const [statsR, healthR] = await Promise.all([
        fetch('/api/logs/stats'), fetch('/api/health')
      ]);
      const stats = await statsR.json();
      const health = healthR.ok ? await healthR.json() : {};
      const bl = stats.by_level || {};
      document.getElementById('ls-total').textContent = stats.total || 0;
      document.getElementById('ls-err').textContent = (bl.ERROR || 0);
      document.getElementById('ls-warn').textContent = (bl.WARNING || 0);
      document.getElementById('ls-crit').textContent = (bl.CRITICAL || 0);
      document.getElementById('ls-1h').textContent = stats.errors_1h || 0;
      if (health.uptime_human) {
        document.getElementById('ls-uptime').textContent = 'up ' + health.uptime_human;
      }
      // Update error badge on header button
      const totalErrors = (bl.ERROR||0) + (bl.CRITICAL||0);
      const badge = document.getElementById('logs-err-badge');
      if (badge) {
        if (stats.errors_1h > 0) {
          badge.style.display = 'flex';
          badge.textContent = stats.errors_1h > 9 ? '9+' : stats.errors_1h;
        } else {
          badge.style.display = 'none';
        }
      }
      // Populate source filter
      const sel = document.getElementById('logs-filter-source');
      const cur = sel.value;
      const sources = stats.sources || [];
      if (sources.length !== _logsSources.length) {
        _logsSources = sources;
        while (sel.options.length > 1) sel.remove(1);
        sources.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s; opt.textContent = s;
          if (s === cur) opt.selected = true;
          sel.appendChild(opt);
        });
      }
    } catch(e) {}
  };

  window.clearLogs = async function() {
    if (!confirm('Clear all log events?')) return;
    await fetch('/api/logs', { method: 'DELETE' });
    loadLogs(); loadStats();
  };

  function renderLogs(events) {
    const body = document.getElementById('logs-body');
    if (!events.length) {
      body.innerHTML = '<div style="text-align:center;padding:3rem;color:#8b949e;font-family:inherit">No log events. Errors and warnings will appear here.</div>';
      return;
    }
    body.innerHTML = events.map(e => {
      const color = LEVEL_COLOR[e.level] || '#8b949e';
      const ts = e.ts ? e.ts.replace('T', ' ').replace(/\.\d+Z?$/, '') : '';
      const hasDetails = e.details && e.details !== '{}' && e.details !== '';
      const detailsId = 'ld-' + e.id.slice(0,8);
      return `<div style="padding:.45rem 1.5rem;border-bottom:1px solid #161b22;display:flex;gap:.75rem;align-items:flex-start;cursor:${hasDetails?'pointer':'default'}" ${hasDetails ? `onclick="toggleLogDetail('${detailsId}')"` : ''}>
        <span style="color:#8b949e;white-space:nowrap;font-size:.72rem;padding-top:.1rem;flex-shrink:0">${ts}</span>
        <span style="background:${color}22;color:${color};padding:.08rem .4rem;border-radius:3px;font-size:.7rem;font-weight:700;flex-shrink:0;min-width:54px;text-align:center">${e.level}</span>
        <span style="color:#8b949e;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;flex-shrink:0;padding-top:.1rem" title="${_esc(e.source)}">${_esc(e.source)}</span>
        <span style="color:#c9d1d9;flex:1;min-width:0;word-break:break-word">${_esc(e.message)}</span>
        ${hasDetails ? '<span style="color:#8b949e;flex-shrink:0;font-size:.8rem">▸</span>' : ''}
      </div>
      ${hasDetails ? `<div id="${detailsId}" style="display:none;padding:.5rem 1.5rem .75rem 5.5rem;border-bottom:1px solid #21262d;background:#0d1117">
        <pre style="color:#8b949e;font-size:.72rem;white-space:pre-wrap;word-break:break-word;margin:0;max-height:300px;overflow-y:auto">${_esc(e.details)}</pre>
      </div>` : ''}`;
    }).join('');
  }

  window.toggleLogDetail = function(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  };

  // Poll error badge even when panel is closed
  async function _pollBadge() {
    try {
      const r = await fetch('/api/logs/stats');
      if (!r.ok) return;
      const stats = await r.json();
      const badge = document.getElementById('logs-err-badge');
      if (!badge) return;
      if (stats.errors_1h > 0) {
        badge.style.display = 'flex';
        badge.textContent = stats.errors_1h > 9 ? '9+' : stats.errors_1h;
      } else {
        badge.style.display = 'none';
      }
    } catch(e) {}
  }
  // Check badge every 30s
  setInterval(_pollBadge, 30000);
  setTimeout(_pollBadge, 3000);

})();
</script>

</body>
</html>
"""


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def render_context_html(cd: dict) -> str:
    pct = cd["saturation_pct"]
    level = cd.get("saturation_level", "empty")
    badge_class = level if level != "empty" else "empty"

    html = """
<h3>Context Window
  <span class="ctx-header-actions">
    <button onclick="toggleContext()" title="Close context">x</button>
  </span>
</h3>

<div class="ctx-section">
  <div class="ctx-gauge">"""

    for block in cd.get("bar_blocks", []):
        w = max(0.5, block["pct"])
        html += f'<div class="ctx-gauge-block" style="width:{w}%;background:{block["color_hex"].strip()}"></div>'

    free_pct = cd.get("free_pct", 0)
    reserve_pct = cd.get("reserve_pct", 0)
    if free_pct > 0:
        html += f'<div class="ctx-gauge-free" style="width:{free_pct}%"></div>'
    if reserve_pct > 0:
        html += f'<div class="ctx-gauge-reserve" style="width:{reserve_pct}%"></div>'

    html += """  </div>
  <div class="ctx-stat-row">
    <span class="lbl">Tokens</span>
    <span class="val">""" + f"{fmt_tokens(cd['used_tokens'])} / {fmt_tokens(cd['max_tokens'])}" + f"""</span>
  </div>
  <div class="ctx-stat-row">
    <span class="lbl">Saturation</span>
    <span class="val"><span class="ctx-badge {badge_class}">{level.upper()}</span> {pct}%</span>
  </div>
</div>

<div class="ctx-section">
  <h4>Tier Breakdown</h4>"""

    for t in cd.get("tiers", []):
        if t["count"] == 0:
            continue
        html += f"""
  <div class="ctx-tier">
    <div class="ctx-dot" style="background:{t['color_hex'].strip()}"></div>
    <span>{t['name']}</span>
    <span class="ctx-tier-tokens">{fmt_tokens(t['tokens'])}</span>
    <span class="ctx-tier-count">{t['count']} entries</span>
  </div>"""

    if not cd.get("tiers") or all(t["count"] == 0 for t in cd["tiers"]):
        html += '<div style="color:#8b949e;font-size:11px;padding:4px 0">No entries yet</div>'

    html += """</div>

<div class="ctx-section">
  <h4>Stats</h4>
  <div class="ctx-stat-row"><span class="lbl">Entries</span><span class="val">${
        cd['entries']}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Free</span><span class="val">${
        fmt_tokens(cd['free_tokens'])}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Reserve</span><span class="val">${
        fmt_tokens(cd['reserve_tokens'])}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Used</span><span class="val">${
        fmt_tokens(cd['used_tokens'])}</span></div>
</div>"""

    sources = cd.get("sources", {})
    if sources:
        html += '<div class="ctx-section"><h4>Sources</h4>'
        for src, tok in list(sources.items())[:6]:
            html += f'<div class="ctx-stat-row"><span class="lbl">{src}</span><span class="val">{fmt_tokens(tok)}</span></div>'
        html += '</div>'

    entries = cd.get("entries_list", [])
    if entries:
        html += '<div class="ctx-section"><h4>Building <span class="ctx-section-count">' + str(len(entries)) + '</span></h4>'
        html += '<div class="ctx-entries">'
        for i, entry in enumerate(entries):
            preview = entry.get("content", "")[:100]
            if len(entry.get("content", "")) > 100:
                preview += "..."
            tier = entry.get("tier", "normal")
            source = entry.get("source", "")
            tokens = entry.get("tokens", 0)
            color = {"critical": "#ff5050", "important": "#ffb432", "normal": "#50a0ff", "low": "#8c8ca0"}.get(tier, "#888")
            pending_class = " pending" if i >= len(entries) - 3 else ""
            html += f'<div class="ctx-entry{pending_class}">'
            html += f'<div class="ctx-entry-dot" style="background:{color}"></div>'
            html += '<div class="ctx-entry-body">'
            html += '<div class="ctx-entry-head">'
            if source:
                html += f'<span class="ctx-entry-source">{source}</span>'
            html += f'<span class="ctx-entry-tokens">{fmt_tokens(tokens)}</span>'
            html += '</div>'
            full_content = entry.get("content", "")
            if len(full_content) > 100:
                html += f'<div class="ctx-entry-text" id="ctx-text-{i}">{escape_html(preview)}</div>'
                html += f'<button class="ctx-entry-expand" onclick="toggleCtxEntry({i})">more</button>'
            else:
                html += f'<div class="ctx-entry-text">{escape_html(preview)}</div>'
            html += '</div></div>'
        html += '</div></div>'

    html += """
<div class="ctx-actions">
  <button onclick="htmx.ajax('POST', '/api/context/add-demo', {target:'#ctx-inner',swap:'innerHTML'})" title="Add demo data">Demo</button>
  <button onclick="htmx.ajax('POST', '/api/context/clear', {target:'#ctx-inner',swap:'innerHTML'})" title="Clear context">Clear</button>
</div>"""

    return html
