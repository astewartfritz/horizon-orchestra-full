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
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-sans); background: var(--bg-primary); color: var(--text-primary); height: 100vh; display: flex; flex-direction: column; overflow: hidden; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
header { background: var(--glass-bg); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid var(--glass-border); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
header h1 { font-size: 16px; background: var(--gradient-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; font-weight: 700; letter-spacing: -0.3px; }
header .sub { font-size: 11px; color: var(--text-secondary); }
.header-btn { background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); padding: 5px 12px; font-size: 12px; border-radius: var(--radius-sm); cursor: pointer; font-family: inherit; transition: all var(--transition-fast); }
.header-btn:hover { background: var(--border); color: var(--text-primary); border-color: var(--text-link); box-shadow: var(--shadow-sm); }
.header-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
#body { display: flex; flex: 1; overflow: hidden; }
#sidebar { width: 240px; background: var(--bg-secondary); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
#sidebar-header { padding: 14px 14px 10px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-subtle); }
#sidebar-header h3 { font-size: 11px; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.8px; font-weight: 600; }
#sidebar-header .count { font-size: 10px; color: var(--text-secondary); background: var(--bg-tertiary); padding: 2px 8px; border-radius: 10px; font-weight: 600; }
#session-list { flex: 1; overflow-y: auto; padding: 6px 8px 8px; }
.session-item { padding: 10px 12px; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; margin-bottom: 3px; border-left: 3px solid transparent; transition: all var(--transition-fast); background: transparent; }
.session-item:hover { background: var(--bg-tertiary); border-left-color: var(--border); }
.session-item.active { background: rgba(31, 111, 235, 0.08); border-left-color: var(--accent-blue); }
.session-item .task { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; font-weight: 500; }
.session-item .date { font-size: 10px; color: var(--text-secondary); margin-top: 3px; }
.session-item .preview { font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 3px; padding-left: 6px; border-left: 2px solid var(--border); }
.session-item.in-progress .task::after { content: '...'; color: var(--accent-orange); margin-left: 2px; animation: pulse 1.5s ease-in-out infinite; }
.session-item { position: relative; }
.session-del { position: absolute; top: 4px; right: 4px; background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 10px; padding: 2px 4px; border-radius: 3px; opacity: 0; transition: opacity var(--transition-fast); }
.session-item:hover .session-del { opacity: 0.6; }
.session-del:hover { opacity: 1 !important; color: var(--accent-red); }
#sidebar-nav { display: flex; border-bottom: 1px solid var(--border); padding: 4px; gap: 2px; background: var(--bg-secondary); }
.nav-btn { flex: 1; background: none; border: none; color: var(--text-secondary); padding: 6px 4px; font-size: 10px; cursor: pointer; border-radius: var(--radius-sm); font-family: inherit; transition: all var(--transition-fast); font-weight: 500; white-space: nowrap; }
.nav-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.nav-btn.active { background: var(--bg-tertiary); color: var(--text-primary); }
#sidebar-footer { padding: 8px 10px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; background: var(--bg-secondary); }
#sidebar-footer input[type="checkbox"] { accent-color: var(--accent-blue); }
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
.config-bar select:focus, .config-bar input:focus { outline: none; border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.12); }
.config-bar label { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.config-bar input[type="checkbox"] { accent-color: var(--accent-green); }
.config-toggle { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 12px; padding: 4px; border-radius: var(--radius-sm); display: flex; align-items: center; transition: all var(--transition-fast); }
.config-toggle:hover { color: var(--text-primary); background: var(--bg-tertiary); }
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
  #sidebar { width: 200px; }
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
  #sidebar { width: 180px; }
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
</style>
</head>
<body>
<header>
  <div><h1>Orchestra</h1><div class="sub">Autonomous AI software engineering</div></div>
  <div id="top-bar" style="display:flex;gap:6px;align-items:center;flex:1;max-width:600px;margin:0 12px">
    <input id="search-history" type="search" placeholder="Search conversations..." style="flex:1;background:var(--bg-primary);border:1px solid var(--border);border-radius:6px;padding:5px 10px;color:var(--text-primary);font-size:12px;font-family:inherit;max-width:300px" oninput="searchHistory(this.value)">
  </div>
  <div style="display:flex;gap:6px;align-items:center">
    <span id="status" style="font-size:12px;color:var(--text-secondary);padding:2px 8px;background:var(--bg-tertiary);border-radius:8px">Idle</span>
    <button class="header-btn" onclick="toggleContext()">Context</button>
    <button class="header-btn" onclick="window.open('/observability','_blank')" title="Prometheus metrics">Metrics</button>
    <button class="header-btn" onclick="window.open('/api/langfuse','_blank')" title="LangFuse LLM observability">LangFuse</button>
    <button class="header-btn" id="jarvis-btn" onclick="toggleJarvis()" title="Toggle JARVIS mode">J.A.R.V.I.S</button>
    <button class="header-btn" onclick="newSession()">+ New</button>
  </div>
</header>
<div id="body">
  <!-- Left Sidebar: Navigation + Spaces + Sessions -->
  <div id="sidebar">
    <div id="sidebar-nav">
      <button class="nav-btn active" data-view="sessions" onclick="switchSidebar('sessions')">&#x1F4AC; Chats</button>
      <button class="nav-btn" data-view="spaces" onclick="switchSidebar('spaces')">&#x1F4E6; Spaces</button>
      <button class="nav-btn" data-view="artifacts" onclick="switchSidebar('artifacts')">&#x1F4C4; Artifacts</button>
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
    <!-- Memory toggle -->
    <div id="sidebar-footer" style="padding:8px;border-top:1px solid var(--border);font-size:11px;color:var(--text-secondary);display:flex;align-items:center;gap:6px">
      <input type="checkbox" id="memory-toggle" onchange="toggleMemory()" checked> <label for="memory-toggle">Cross-chat memory</label>
    </div>
  </div>
  <!-- Main Chat Area -->
  <div id="main">
    <div id="chat">
      <div class="config-bar">
        <button class="config-toggle" onclick="toggleConfig()" title="Toggle config">&#x2699;</button>
        <div class="config-fields" id="config-fields">
          <select id="provider"><option value="ollama">Ollama</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="vllm">vLLM</option></select>
          <select id="model">
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
            <optgroup label="Anthropic">
              <option value="claude-sonnet-4-20250514">claude-sonnet-4</option>
              <option value="claude-3-opus">claude-3-opus</option>
            </optgroup>
            <optgroup label="vLLM">
              <option value="Qwen/Qwen2.5-7B-Instruct">Qwen2.5-7B</option>
              <option value="Qwen/Qwen2.5-32B-Instruct">Qwen2.5-32B</option>
              <option value="meta-llama/Llama-3.1-8B-Instruct">Llama-3.1-8B</option>
              <option value="mistralai/Mistral-7B-Instruct-v0.3">Mistral-7B</option>
            </optgroup>
          </select>
          <div class="model-presets">
            <span class="preset-btn active" data-provider="ollama" data-model="nemotron-mini" title="Ollama + nemotron-mini" onclick="togglePreset(this)">Nemotron</span>
            <span class="preset-btn" data-provider="ollama" data-model="qwen2.5:7b" title="Ollama + qwen2.5:7b" onclick="togglePreset(this)">Qwen</span>
            <span class="preset-btn" data-provider="ollama" data-model="deepseek-r1:8b" title="Ollama + deepseek-r1:8b" onclick="togglePreset(this)">DeepSeek</span>
            <span class="preset-btn" data-provider="ollama" data-model="gemma3:4b" title="Ollama + gemma3:4b" onclick="togglePreset(this)">Gemma</span>
          </div>
          <input id="api-key" type="password" placeholder="API key" style="width:170px">
          <label><input type="checkbox" id="use-cache" checked> Cache</label>
          <label style="margin-left:4px"><input type="checkbox" id="prince-mode" title="Ask with web search + citations"> Prince</label>
        </div>
      </div>
      <div class="tab-bar">
        <button class="tab-btn active" onclick="switchTab('chat')">Chat</button>
        <button class="tab-btn" onclick="switchTab('skills')">Skills</button>
      </div>
      <div id="tab-chat" class="tab-content">
        <div id="messages"></div>
        <div id="welcome">
          <h2>Welcome to Orchestra</h2>
          <p>Your autonomous AI software engineering assistant. Describe a task and watch the agent work.</p>
          <div class="example-tasks">
            <button class="example-btn" onclick="setTask('Build a Flask REST API with SQLite')">Build REST API</button>
            <button class="example-btn" onclick="setTask('Create a React dashboard with charts')">React Dashboard</button>
            <button class="example-btn" onclick="setTask('Analyze this project and suggest improvements')">Analyze Project</button>
            <button class="example-btn" onclick="setTask('Write unit tests for the agent module')">Write Tests</button>
          </div>
          <div class="example-tasks" style="margin-top:8px">
            <button class="example-btn prince-btn" onclick="askPrince()" title="Ask with web search + citations">Prince search</button>
          </div>
        </div>
        <div id="spinner"><div class="spinner-icon"></div><span>Agent is working...</span></div>
        <div id="input-area">
          <div id="input-form">
            <textarea id="task-input" rows="1" placeholder="Describe a task for the agent..." disabled></textarea>
            <button class="input-btn" id="img-btn" onclick="document.getElementById('img-input').click()" title="Attach image" disabled>&#x1F5BC;</button>
            <input type="file" id="img-input" accept="image/*" style="display:none" onchange="attachImage(this)">
            <button class="input-btn mic-btn" id="mic-btn" onclick="toggleMic()" title="Voice input" disabled>&#x1F3A4;</button>
            <button id="send-btn" onclick="sendTask()" disabled>Run</button>
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
        <div id="skills-panel" style="padding:16px;overflow-y:auto;height:100%">
          <div style="display:flex;gap:8px;margin-bottom:12px">
            <button class="example-btn" onclick="refreshSkills()">Refresh</button>
            <button class="example-btn" onclick="pruneSkills()">Prune</button>
          </div>
          <div id="skills-stats" style="margin-bottom:12px;font-size:13px;color:var(--text-secondary)">Loading...</div>
          <div id="skills-list" style="font-size:13px">Loading skills...</div>
          <div id="skills-credit" style="margin-top:16px">
            <h3 style="font-size:12px;text-transform:uppercase;color:var(--text-secondary);margin-bottom:8px">Credit Signals</h3>
            <div id="credit-curve" style="font-size:13px;color:var(--text-secondary)">No data yet.</div>
          </div>
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
let _configOpen = true;
let _reconnectAttempts = 0;

function saveConfig() {
  try {
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
    var p = localStorage.getItem('ca_provider');
    var m = localStorage.getItem('ca_model');
    var k = localStorage.getItem('ca_api_key');
    var c = localStorage.getItem('ca_cache');
    var pp = localStorage.getItem('ca_prince');
    var co = localStorage.getItem('ca_ctx_open');
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
  showMove('plan', 'Planning', trimmed.slice(0, 120));
  if (lastAssistant) {
    var existing = lastAssistant.querySelector('.thinking-details');
    if (existing) {
      existing.querySelector('.thinking-text').textContent = trimmed;
      return;
    }
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

function createToolPanel(name, args, actionType) {
  actionType = actionType || 'tool';
  var msgs = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg tool';
  var argStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
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
  } else {
    sendBtn.onclick = sendTask;
    document.getElementById('task-input').focus();
  }
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
    var body = JSON.stringify({
      task: task + (_attachedImage ? ' [Image attached]' : ''),
      session_id: currentSession || '',
      provider: document.getElementById('provider').value,
      model: document.getElementById('model').value,
      api_key: document.getElementById('api-key').value,
      use_cache: document.getElementById('use-cache').checked,
    });
    _attachedImage = null;
    document.getElementById('img-name').style.display = 'none';
    var resp = await fetch('/api/chat', {
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
          createToolPanel(msg.data.name, msg.data.arguments, msg.data.action_type || 'tool');
          fetch('/api/context/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({content: 'Tool: ' + msg.data.name, tier: 'important', source: msg.data.name}) }).then(function() { htmx.trigger('body', 'contextUpdated'); }).catch(function(){});
          break;
        case 'tool_result':
          var panels = document.querySelectorAll('.msg.tool');
          var lastPanel = panels[panels.length - 1];
          if (lastPanel) { updateToolPanel(lastPanel, msg.data.output, msg.data.error); }
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
          if (assistantState.div) {
            removeCursor(assistantState.cursor);
            renderMarkdown(assistantState.div.content);
            addTimestamp(assistantState.div.container);
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
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}

function togglePreset(btn) {
  var isActive = btn.classList.contains('active');
  document.querySelectorAll('.preset-btn').forEach(function(b) { b.classList.remove('active'); });
  if (!isActive) {
    btn.classList.add('active');
    document.getElementById('provider').value = btn.getAttribute('data-provider');
    filterModelByProvider(document.getElementById('provider').value);
    document.getElementById('model').value = btn.getAttribute('data-model');
  } else {
    document.getElementById('provider').value = 'ollama';
    filterModelByProvider('ollama');
    document.getElementById('model').value = 'nemotron-mini';
  }
  saveConfig();
  syncPreset();
}

function syncPreset() {
  var provider = document.getElementById('provider').value;
  var model = document.getElementById('model').value;
  document.querySelectorAll('.preset-btn').forEach(function(b) {
    var p = b.getAttribute('data-provider');
    var m = b.getAttribute('data-model');
    if (p === provider && m === model) {
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
  var el = document.getElementById(view === 'sessions' ? 'session-list' : view + '-list');
  if (el) { el.classList.add('active'); el.style.display = 'flex'; }
  var title = document.getElementById('sidebar-title');
  if (title) title.textContent = view.charAt(0).toUpperCase() + view.slice(1);
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

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('.tab-content').forEach(function(c) { c.style.display = 'none'; });
  document.querySelector('.tab-btn[onclick="switchTab(\'' + name + '\')"]').classList.add('active');
  document.getElementById('tab-' + name).style.display = 'flex';
  if (name === 'skills') refreshSkills();
}

function refreshSkills() {
  var panel = document.getElementById('skills-panel');
  if (!panel) return;
  document.getElementById('skills-stats').textContent = 'Loading...';
  document.getElementById('skills-list').innerHTML = 'Loading skills...';
  fetch('/api/skillsv2/stats').then(function(r) { return r.json(); }).then(function(data) {
    var lib = data.library || {};
    var html = 'Library: ' + (lib.count || 0) + ' skills &middot; ';
    html += 'Avg reward: ' + (lib.avg_reward || 0).toFixed(2) + ' &middot; ';
    html += 'Success rate: ' + ((lib.avg_success_rate || 0) * 100).toFixed(0) + '% &middot; ';
    html += 'Total usage: ' + (lib.total_usage || 0);
    document.getElementById('skills-stats').innerHTML = html;
    var comp = data.comparison || [];
    if (comp.length === 0) {
      document.getElementById('skills-list').innerHTML = '<div style="color:var(--text-secondary);padding:8px">No skills evaluated yet. Run tasks to build the library.</div>';
    } else {
      var listHtml = '<table style="width:100%;border-collapse:collapse;font-size:12px">';
      listHtml += '<tr style="color:var(--text-secondary);border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">Body</th><th style="text-align:right;padding:4px 8px">Avg Reward</th><th style="text-align:right;padding:4px 8px">Success Rate</th><th style="text-align:right;padding:4px 8px">Trials</th></tr>';
      comp.forEach(function(s) {
        listHtml += '<tr style="border-bottom:1px solid var(--border)">';
        listHtml += '<td style="padding:4px 8px;color:var(--text-link)">' + s.skill_id + '</td>';
        listHtml += '<td style="padding:4px 8px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(s.skill_body || '') + '</td>';
        listHtml += '<td style="padding:4px 8px;text-align:right">' + (s.avg_reward || 0).toFixed(2) + '</td>';
        listHtml += '<td style="padding:4px 8px;text-align:right">' + ((s.success_rate || 0) * 100).toFixed(0) + '%</td>';
        listHtml += '<td style="padding:4px 8px;text-align:right">' + s.count + '</td></tr>';
      });
      listHtml += '</table>';
      document.getElementById('skills-list').innerHTML = listHtml;
    }
    var credit = data.credit_curve || {};
    var steps = credit.steps || [];
    if (steps.length > 0) {
      var cHtml = '<div style="font-size:11px;color:var(--text-secondary)">';
      cHtml += 'Selection: <b>' + ((credit.selection && credit.selection[credit.selection.length-1]) || 0).toFixed(2) + '</b> &middot; ';
      cHtml += 'Utilization: <b>' + ((credit.utilization && credit.utilization[credit.utilization.length-1]) || 0).toFixed(2) + '</b> &middot; ';
      cHtml += 'Distillation: <b>' + ((credit.distillation && credit.distillation[credit.distillation.length-1]) || 0).toFixed(2) + '</b>';
      cHtml += '<div style="margin-top:4px;height:60px;position:relative;background:var(--bg-tertiary);border-radius:4px">';
      cHtml += '<span style="position:absolute;bottom:4px;right:4px;font-size:10px;color:var(--text-secondary)">' + steps.length + ' episodes</span></div>';
      cHtml += '</div>';
      document.getElementById('credit-curve').innerHTML = cHtml;
    } else {
      document.getElementById('credit-curve').innerHTML = '<span style="color:var(--text-secondary)">No credit data yet. Run training episodes.</span>';
    }
  }).catch(function(e) {
    document.getElementById('skills-stats').textContent = 'Error loading skills: ' + e;
  });
  fetch('/api/skillsv2/list?limit=50').then(function(r) { return r.json(); }).then(function(data) {
    var skills = data.skills || [];
    if (skills.length === 0) return;
    var sHtml = '<h3 style="font-size:12px;text-transform:uppercase;color:var(--text-secondary);margin:12px 0 8px">All Skills</h3>';
    sHtml += '<table style="width:100%;border-collapse:collapse;font-size:12px">';
    sHtml += '<tr style="color:var(--text-secondary);border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">Body</th><th style="text-align:right;padding:4px 8px">Usage</th><th style="text-align:right;padding:4px 8px">Success</th><th style="text-align:right;padding:4px 8px">Avg Reward</th></tr>';
    skills.forEach(function(s) {
      sHtml += '<tr style="border-bottom:1px solid var(--border)">';
      sHtml += '<td style="padding:4px 8px;color:var(--text-link)">' + s.id + '</td>';
      sHtml += '<td style="padding:4px 8px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(s.body || '') + '</td>';
      sHtml += '<td style="padding:4px 8px;text-align:right">' + (s.usage_count || 0) + '</td>';
      sHtml += '<td style="padding:4px 8px;text-align:right">' + (s.success_count || 0) + '</td>';
      sHtml += '<td style="padding:4px 8px;text-align:right">' + ((s.total_reward || 0) / Math.max(s.usage_count, 1)).toFixed(2) + '</td></tr>';
    });
    sHtml += '</table>';
    var container = document.getElementById('skills-list');
    if (container) container.innerHTML += sHtml;
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

document.addEventListener('DOMContentLoaded', function() {
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
  document.getElementById('provider').addEventListener('change', function() {
    filterModelByProvider(this.value);
    saveConfig();
    syncPreset();
  });
  document.getElementById('model').addEventListener('change', function() {
    saveConfig();
    syncPreset();
  });
});

})();

// Register service worker for PWA offline support
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(function() {});
}
</script>
<div id="toast-container"></div>
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
