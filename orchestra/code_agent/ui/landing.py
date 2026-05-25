"""Landing page for horizon-orchestra.com — Apple-style full-viewport architecture."""

LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Orchestra — Your AI. Your Machine. Your Rules.</title>
<meta name="description" content="Orchestra is autonomous AI for healthcare, legal, and finance professionals. Local-first. Privacy-first. Yours.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ─── Reset & Base ─────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; -webkit-font-smoothing: antialiased; }
body {
  background: #000;
  color: #f5f5f7;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  overflow-x: hidden;
}
a { text-decoration: none; color: inherit; }
img, svg { display: block; }
::-webkit-scrollbar { width: 0; }

/* ─── CSS Variables ────────────────────────────────────────────────────────── */
:root {
  --void: #000;
  --deep: #080a0f;
  --surface: #0f1117;
  --surface2: #161b25;
  --border: rgba(255,255,255,0.08);
  --border-bright: rgba(255,255,255,0.18);
  --text-1: #f5f5f7;
  --text-2: #86868b;
  --text-3: #515154;
  --accent: #5b8af0;
  --accent-glow: rgba(91,138,240,0.25);
  --cyan: #00c8e8;
  --purple: #a855f7;
  --green: #34d399;
  --rose: #f472b6;
  --mono: 'JetBrains Mono', 'Fira Code', monospace;
}

/* ─── Nav ──────────────────────────────────────────────────────────────────── */
#nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 200;
  height: 52px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 22px;
  background: rgba(0,0,0,0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border);
  transition: background .3s;
}
.nav-logo {
  display: flex; align-items: center; gap: 9px;
  font-size: 17px; font-weight: 600; letter-spacing: -.3px; color: var(--text-1);
}
.nav-logo svg { width: 28px; height: 28px; }
.nav-center {
  display: flex; align-items: center; gap: 4px;
  position: absolute; left: 50%; transform: translateX(-50%);
}
.nav-center a {
  font-size: 13px; font-weight: 400; color: var(--text-2);
  padding: 6px 12px; border-radius: 6px;
  transition: color .15s;
}
.nav-center a:hover { color: var(--text-1); }
.nav-right { display: flex; align-items: center; gap: 8px; }
.nav-link { font-size: 13px; color: var(--text-2); padding: 6px 10px; transition: color .15s; }
.nav-link:hover { color: var(--text-1); }
.nav-btn {
  font-size: 13px; font-weight: 500; color: var(--text-1);
  background: rgba(255,255,255,0.1);
  padding: 6px 14px; border-radius: 100px;
  border: 1px solid var(--border-bright);
  transition: background .15s;
}
.nav-btn:hover { background: rgba(255,255,255,0.16); }
.nav-btn-primary {
  background: var(--accent); border-color: transparent;
  box-shadow: 0 0 20px var(--accent-glow);
}
.nav-btn-primary:hover { background: #6f9bf3; }

/* ─── Utility ──────────────────────────────────────────────────────────────── */
.cta-pair { display: flex; align-items: center; gap: 28px; flex-wrap: wrap; }
.cta-primary {
  font-size: 17px; font-weight: 500;
  color: var(--text-1); background: var(--accent);
  padding: 13px 28px; border-radius: 100px;
  transition: all .2s;
  box-shadow: 0 0 30px var(--accent-glow);
}
.cta-primary:hover { background: #6f9bf3; transform: scale(1.02); }
.cta-secondary {
  font-size: 17px; font-weight: 400;
  color: var(--accent);
  transition: color .15s;
  display: flex; align-items: center; gap: 5px;
}
.cta-secondary::after { content: '›'; font-size: 20px; line-height: 1; }
.cta-secondary:hover { color: #6f9bf3; }

/* ─── Section Base ─────────────────────────────────────────────────────────── */
.scene {
  min-height: 100svh;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 100px 24px 80px;
  position: relative; overflow: hidden;
  text-align: center;
}
.scene-left {
  align-items: flex-start; text-align: left;
  padding-left: max(5vw, 60px);
}
.scene-tag {
  font-size: 13px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--accent); margin-bottom: 20px;
}
.scene h1 {
  font-size: clamp(56px, 9vw, 116px);
  font-weight: 800; line-height: 1.02; letter-spacing: -3px;
  color: var(--text-1); max-width: 14ch;
}
.scene h2 {
  font-size: clamp(40px, 6.5vw, 80px);
  font-weight: 700; line-height: 1.06; letter-spacing: -2px;
  color: var(--text-1); max-width: 20ch;
}
.scene h3 {
  font-size: clamp(28px, 4vw, 52px);
  font-weight: 700; line-height: 1.1; letter-spacing: -1px;
  color: var(--text-1); max-width: 24ch;
}
.scene p {
  font-size: clamp(16px, 2vw, 21px);
  color: var(--text-2); line-height: 1.55;
  max-width: 52ch; margin-top: 20px;
}
.scene .cta-pair { margin-top: 40px; }
.grad-text {
  background: linear-gradient(135deg, #5b8af0 0%, #a855f7 50%, #00c8e8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.grad-text-warm {
  background: linear-gradient(135deg, #f472b6 0%, #a855f7 60%, #5b8af0 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.grad-text-green {
  background: linear-gradient(135deg, #34d399 0%, #00c8e8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

/* ─── Hero ─────────────────────────────────────────────────────────────────── */
#hero {
  background: var(--void);
  min-height: 100svh;
}
.hero-glow {
  position: absolute; border-radius: 50%; pointer-events: none;
  filter: blur(120px); opacity: .18;
}
.glow-1 { width: 700px; height: 700px; background: #5b8af0; top: -200px; left: -200px; animation: glow-drift 18s ease-in-out infinite alternate; }
.glow-2 { width: 500px; height: 500px; background: #a855f7; bottom: -100px; right: -100px; animation: glow-drift 14s ease-in-out infinite alternate-reverse; }
.glow-3 { width: 400px; height: 400px; background: #00c8e8; top: 50%; right: 20%; animation: glow-drift 22s ease-in-out infinite alternate; }
@keyframes glow-drift { from { transform: translate(0,0) scale(1); } to { transform: translate(40px, 60px) scale(1.1); } }

.hero-badge {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 500;
  color: var(--text-2);
  background: rgba(255,255,255,.05);
  border: 1px solid var(--border-bright);
  padding: 6px 16px; border-radius: 100px;
  margin-bottom: 36px;
}
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
  animation: live-pulse 2s ease-in-out infinite;
}
@keyframes live-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.8)} }

/* ─── Divider line ─────────────────────────────────────────────────────────── */
.hairline { height: 1px; background: var(--border); }

/* ─── Statement section (big solo text) ───────────────────────────────────── */
.statement {
  min-height: 60svh;
  display: flex; align-items: center; justify-content: center;
  padding: 80px 24px;
  background: var(--deep);
  text-align: center;
}
.statement h2 {
  font-size: clamp(36px, 6vw, 76px);
  font-weight: 700; line-height: 1.1; letter-spacing: -2px;
  color: var(--text-1); max-width: 22ch; margin: 0 auto;
}
.statement h2 em { font-style: normal; color: var(--text-2); }

/* ─── Two-column feature scenes ───────────────────────────────────────────── */
.feature-scene {
  min-height: 100svh;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  overflow: hidden;
}
.feature-scene.flip { direction: rtl; }
.feature-scene.flip > * { direction: ltr; }
.feature-copy {
  padding: 80px max(5vw, 48px);
  display: flex; flex-direction: column;
  justify-content: center;
}
.feature-copy .scene-tag { margin-bottom: 20px; }
.feature-copy h2 {
  font-size: clamp(36px, 4.5vw, 64px);
  font-weight: 700; line-height: 1.08; letter-spacing: -1.5px;
  color: var(--text-1);
}
.feature-copy p {
  font-size: 17px; color: var(--text-2); line-height: 1.6;
  margin-top: 18px; max-width: 44ch;
}
.feature-copy .cta-pair { margin-top: 32px; }
.feature-copy .cta-secondary { font-size: 15px; }
.feature-copy .cta-secondary::after { font-size: 18px; }
.feature-visual {
  height: 100%;
  display: flex; align-items: center; justify-content: center;
  padding: 40px;
  position: relative;
}

/* ─── UI Mockup cards ─────────────────────────────────────────────────────── */
.mockup {
  width: 100%; max-width: 480px;
  border-radius: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  overflow: hidden;
  box-shadow: 0 40px 100px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.04);
}
.mockup-bar {
  background: #0c0e14; padding: 12px 16px;
  display: flex; align-items: center; gap: 7px;
  border-bottom: 1px solid var(--border);
}
.mock-dot { width: 11px; height: 11px; border-radius: 50%; }
.mock-dot:nth-child(1){background:#ff5f57} .mock-dot:nth-child(2){background:#ffbd2e} .mock-dot:nth-child(3){background:#28c840}
.mockup-body { padding: 20px; font-family: var(--mono); font-size: 13px; line-height: 1.9; }
.mock-line { display: flex; gap: 10px; }
.mock-prompt { color: var(--green); }
.mock-cmd { color: var(--text-1); }
.mock-out { color: var(--text-2); padding-left: 20px; }
.mock-out.hi { color: var(--cyan); }
.mock-out.ok { color: var(--green); }
.mock-out.warn { color: #fb923c; }
.mock-cursor { display: inline-block; width: 2px; height: 13px; background: var(--green); margin-left: 2px; vertical-align: middle; animation: blink .8s step-end infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

/* ─── Data table mockup ───────────────────────────────────────────────────── */
.data-mockup {
  width: 100%; max-width: 480px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 40px 100px rgba(0,0,0,.6);
}
.data-mockup-header {
  background: #0c0e14; padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.data-mockup-header span { font-size: 13px; font-weight: 600; color: var(--text-2); }
.data-mockup-header .badge { font-size: 11px; background: rgba(52,211,153,.12); color: var(--green); padding: 3px 10px; border-radius: 100px; font-weight: 600; }
.data-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  padding: 12px 20px; border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.data-row.header { color: var(--text-3); font-size: 11px; font-weight: 600; letter-spacing: .5px; text-transform: uppercase; }
.data-row:last-child { border-bottom: none; }
.data-row span:not(:first-child) { text-align: right; }
.data-pos { color: var(--green); }
.data-neg { color: var(--rose); }

/* ─── Chat mockup ─────────────────────────────────────────────────────────── */
.chat-mockup {
  width: 100%; max-width: 460px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 40px 100px rgba(0,0,0,.6);
}
.chat-header {
  background: #0c0e14; padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px;
  font-size: 14px; font-weight: 600; color: var(--text-1);
}
.chat-avatar { width: 30px; height: 30px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--purple)); display: flex; align-items: center; justify-content: center; font-size: 14px; }
.chat-body { padding: 16px; display: flex; flex-direction: column; gap: 12px; min-height: 200px; }
.chat-bubble {
  max-width: 78%; padding: 10px 14px;
  border-radius: 14px; font-size: 13px; line-height: 1.5;
}
.bubble-ai { background: var(--surface2); color: var(--text-1); align-self: flex-start; border-bottom-left-radius: 4px; }
.bubble-user { background: var(--accent); color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
.chat-input-row { padding: 12px 16px; border-top: 1px solid var(--border); display: flex; gap: 8px; }
.chat-input-fake { flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 100px; padding: 8px 14px; font-size: 13px; color: var(--text-3); }
.chat-send-fake { width: 32px; height: 32px; border-radius: 50%; background: var(--accent); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 14px; }

/* ─── Models scene ─────────────────────────────────────────────────────────── */
.models-scene {
  min-height: 80svh;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 100px 24px;
  background: var(--deep);
  text-align: center;
}
.models-grid {
  display: flex; gap: 16px; flex-wrap: wrap; justify-content: center;
  margin-top: 56px; max-width: 900px;
}
.model-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 100px; padding: 12px 22px;
  display: flex; align-items: center; gap: 10px;
  transition: all .2s;
}
.model-pill:hover { border-color: var(--border-bright); background: var(--surface2); transform: scale(1.02); }
.model-pill-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.model-pill-name { font-size: 15px; font-weight: 500; color: var(--text-1); }
.model-pill-sub { font-size: 12px; color: var(--text-3); }

/* ─── Live demo scene ─────────────────────────────────────────────────────── */
.demo-scene {
  min-height: 80svh;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 100px 24px;
  background: var(--void);
}
.demo-box {
  width: 100%; max-width: 720px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px; overflow: hidden;
  box-shadow: 0 0 80px rgba(91,138,240,.08);
  margin-top: 52px;
}
.demo-topbar {
  background: #0c0e14; padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.demo-topbar span { font-size: 13px; font-weight: 600; color: var(--text-2); }
.demo-model-pick {
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text-1); font-family: var(--mono); font-size: 12px;
  padding: 5px 10px; border-radius: 6px; cursor: pointer; outline: none;
}
.demo-model-pick option { background: var(--surface); }
#demo-messages {
  min-height: 200px; max-height: 320px; overflow-y: auto;
  padding: 20px; display: flex; flex-direction: column; gap: 16px;
}
.dmsg { display: flex; gap: 10px; align-items: flex-start; }
.dmsg-av {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 13px;
}
.dmsg-user .dmsg-av { background: rgba(91,138,240,.2); }
.dmsg-ai .dmsg-av   { background: rgba(0,200,232,.12); }
.dmsg-text { font-size: 14px; line-height: 1.6; color: var(--text-1); padding-top: 2px; }
.dmsg-ai .dmsg-text { color: var(--text-2); }
.demo-row {
  padding: 14px 20px; border-top: 1px solid var(--border);
  display: flex; gap: 10px;
}
.demo-inp {
  flex: 1; background: var(--surface2); border: 1px solid var(--border);
  border-radius: 100px; padding: 10px 18px;
  font-size: 14px; color: var(--text-1); outline: none;
  transition: border-color .2s; font-family: inherit;
}
.demo-inp:focus { border-color: var(--border-bright); }
.demo-inp::placeholder { color: var(--text-3); }
.demo-go {
  background: var(--accent); border: none; border-radius: 100px;
  padding: 10px 20px; color: #fff; font-size: 14px; font-weight: 500;
  cursor: pointer; transition: all .2s; white-space: nowrap;
}
.demo-go:hover { background: #6f9bf3; }
.demo-go:disabled { opacity: .4; cursor: not-allowed; }
.typing-dots { display: flex; gap: 4px; padding: 6px 0; align-items: center; }
.typing-dots span { width: 5px; height: 5px; border-radius: 50%; background: var(--text-3); animation: tdot .9s ease-in-out infinite; }
.typing-dots span:nth-child(2){animation-delay:.15s} .typing-dots span:nth-child(3){animation-delay:.3s}
@keyframes tdot { 0%,100%{transform:translateY(0);background:var(--text-3)} 50%{transform:translateY(-5px);background:var(--cyan)} }

/* ─── Security scene ──────────────────────────────────────────────────────── */
.security-scene {
  min-height: 70svh;
  background: var(--deep);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 80px 24px;
  text-align: center;
}
.security-checks {
  display: flex; gap: 12px; flex-wrap: wrap; justify-content: center;
  margin-top: 48px; max-width: 800px;
}
.security-chip {
  display: flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 100px; padding: 10px 18px;
  font-size: 14px; color: var(--text-2);
  transition: all .2s;
}
.security-chip:hover { border-color: var(--border-bright); color: var(--text-1); }
.security-chip .check { color: var(--green); font-size: 13px; }

/* ─── Pricing ─────────────────────────────────────────────────────────────── */
.pricing-scene {
  min-height: 100svh;
  background: var(--void);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 100px 24px;
}
.pricing-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; max-width: 960px; width: 100%; margin-top: 64px; }
.p-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px; padding: 36px 32px;
  display: flex; flex-direction: column;
  transition: all .2s; position: relative;
}
.p-card.featured {
  border-color: rgba(91,138,240,.5);
  background: rgba(91,138,240,.04);
  box-shadow: 0 0 60px rgba(91,138,240,.1);
}
.p-badge {
  position: absolute; top: -11px; left: 50%; transform: translateX(-50%);
  font-size: 11px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase;
  background: var(--accent); color: #fff;
  padding: 3px 14px; border-radius: 100px; white-space: nowrap;
}
.p-tier { font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-3); margin-bottom: 16px; }
.p-price { font-size: 52px; font-weight: 800; letter-spacing: -2px; line-height: 1; color: var(--text-1); margin-bottom: 4px; }
.p-price sup { font-size: 22px; font-weight: 400; vertical-align: super; }
.p-per { font-size: 13px; color: var(--text-3); margin-bottom: 28px; }
.p-items { list-style: none; flex: 1; margin-bottom: 28px; display: flex; flex-direction: column; gap: 10px; }
.p-items li { font-size: 14px; color: var(--text-2); display: flex; align-items: flex-start; gap: 10px; line-height: 1.4; }
.p-items li::before { content: '✓'; color: var(--green); font-weight: 700; flex-shrink: 0; }
.p-cta {
  display: block; text-align: center;
  padding: 13px; border-radius: 100px;
  font-size: 15px; font-weight: 500;
  transition: all .2s;
}
.p-cta-outline { background: transparent; color: var(--text-1); border: 1px solid var(--border-bright); }
.p-cta-outline:hover { background: rgba(255,255,255,.06); }
.p-cta-fill { background: var(--accent); color: #fff; border: 1px solid transparent; box-shadow: 0 0 20px var(--accent-glow); }
.p-cta-fill:hover { background: #6f9bf3; }

/* ─── Final CTA ───────────────────────────────────────────────────────────── */
.finale {
  min-height: 70svh;
  background: var(--deep);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  text-align: center;
  padding: 80px 24px;
}
.finale h2 {
  font-size: clamp(48px, 8vw, 96px);
  font-weight: 800; letter-spacing: -3px; line-height: 1.04;
  color: var(--text-1); margin-bottom: 20px;
}
.finale p { font-size: 19px; color: var(--text-2); max-width: 40ch; margin: 0 auto 40px; }
.finale .cta-pair { justify-content: center; }

/* ─── Footer ──────────────────────────────────────────────────────────────── */
footer {
  background: #0a0a0a;
  border-top: 1px solid var(--border);
  padding: 48px 48px 36px;
}
.footer-row { display: flex; gap: 64px; justify-content: space-between; flex-wrap: wrap; margin-bottom: 48px; }
.footer-brand { max-width: 260px; }
.footer-brand p { font-size: 13px; color: var(--text-3); line-height: 1.7; margin-top: 12px; }
.footer-col h5 { font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--text-3); margin-bottom: 14px; }
.footer-col ul { list-style: none; display: flex; flex-direction: column; gap: 9px; }
.footer-col li a { font-size: 13px; color: var(--text-3); transition: color .15s; }
.footer-col li a:hover { color: var(--text-1); }
.footer-bottom { border-top: 1px solid var(--border); padding-top: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.footer-bottom p { font-size: 12px; color: var(--text-3); }
.footer-bottom a { color: var(--text-3); transition: color .15s; }
.footer-bottom a:hover { color: var(--text-2); }

/* ─── Responsive ──────────────────────────────────────────────────────────── */
/* Mobile hamburger button */
.nav-hamburger {
  display: none; flex-direction: column; gap: 5px; cursor: pointer;
  background: none; border: none; padding: 6px; margin-left: 12px;
}
.nav-hamburger span {
  display: block; width: 22px; height: 2px;
  background: var(--text-1); border-radius: 2px; transition: all .25s;
}
.nav-hamburger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
.nav-hamburger.open span:nth-child(2) { opacity: 0; }
.nav-hamburger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }

/* Mobile drawer */
.nav-drawer {
  display: none; position: fixed; top: 52px; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,.96); backdrop-filter: blur(20px);
  flex-direction: column; align-items: center; justify-content: center;
  gap: 28px; z-index: 199;
}
.nav-drawer.open { display: flex; }
.nav-drawer a {
  font-size: 22px; font-weight: 600; color: var(--text-1);
  padding: 10px 0; min-height: 44px; display: flex; align-items: center;
}

@media (max-width: 900px) {
  .nav-center { display: none; }
  .nav-hamburger { display: flex; }
  .nav-right .nav-btn { padding: 7px 14px; font-size: 13px; }
  .feature-scene { grid-template-columns: 1fr; }
  .feature-scene.flip { direction: ltr; }
  .feature-visual { min-height: 280px; }
  .pricing-grid { grid-template-columns: 1fr; max-width: 420px; }
  footer { padding: 40px 24px 28px; }
  .footer-row { gap: 36px; flex-wrap: wrap; }
  .footer-col { min-width: 140px; }
}
@media (max-width: 600px) {
  #nav { padding: 0 16px; }
  .scene { padding: 0 20px; }
  .scene h1 { font-size: clamp(36px, 9vw, 52px); letter-spacing: -2px; }
  .scene h2 { font-size: clamp(26px, 6vw, 40px); letter-spacing: -1px; }
  .cta-pair { flex-direction: column; align-items: center; gap: 14px; width: 100%; }
  .scene .cta-pair { align-items: center; }
  .cta-pair a, .cta-pair button { width: 100%; text-align: center; min-height: 44px; }
  .feature-copy { padding: 50px 20px 32px; }
  .feature-visual { min-height: 220px; }
  .pricing-grid { max-width: 100%; padding: 0 4px; }
  .pricing-card { padding: 24px 20px; }
}
@media (max-width: 400px) {
  .scene h1 { font-size: 32px; }
  .nav-logo { font-size: 15px; }
}
</style>
</head>
<body>

<!-- ══════════════════════════════════════════════════════════════════════════
     NAV
════════════════════════════════════════════════════════════════════════════ -->
<nav id="nav">
  <a href="/" class="nav-logo">
    <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="28" height="28" rx="7" fill="#0f1117"/>
      <line x1="7"  y1="5.5" x2="7"  y2="22.5" stroke="#5b8af0" stroke-width="1.4"/>
      <line x1="10.5" y1="3.5" x2="10.5" y2="24.5" stroke="#7a9df5" stroke-width="1.4"/>
      <line x1="14" y1="3" x2="14" y2="25" stroke="#a855f7" stroke-width="1.6"/>
      <line x1="17.5" y1="3.5" x2="17.5" y2="24.5" stroke="#7a9df5" stroke-width="1.4"/>
      <line x1="21" y1="5.5" x2="21" y2="22.5" stroke="#5b8af0" stroke-width="1.4"/>
      <ellipse cx="14" cy="14" rx="2" ry="2" fill="#00c8e8"/>
    </svg>
    Orchestra
  </a>
  <nav class="nav-center">
    <a href="/app">Orchestra</a>
    <a href="/miles" style="color:var(--cyan);">MILES</a>
    <a href="http://localhost:3001" style="color:var(--purple);">OpenJARVIS</a>
    <a href="#features">Features</a>
    <a href="#pricing">Pricing</a>
    <a href="/docs">Docs</a>
  </nav>
  <div class="nav-right">
    <a href="/login" class="nav-link">Sign in</a>
    <a href="/app" class="nav-btn nav-btn-primary">Launch App</a>
    <button class="nav-hamburger" id="navHamburger" aria-label="Menu" onclick="toggleDrawer()">
      <span></span><span></span><span></span>
    </button>
  </div>
</nav>
<!-- Mobile drawer -->
<div class="nav-drawer" id="navDrawer">
  <a href="/app" onclick="closeDrawer()">Orchestra App</a>
  <a href="/miles" onclick="closeDrawer()" style="color:var(--cyan);">MILES</a>
  <a href="http://localhost:3001" onclick="closeDrawer()" style="color:var(--purple);">OpenJARVIS</a>
  <a href="#features" onclick="closeDrawer()">Features</a>
  <a href="#pricing" onclick="closeDrawer()">Pricing</a>
  <a href="/docs" onclick="closeDrawer()">Docs</a>
  <a href="/login" onclick="closeDrawer()">Sign in</a>
  <a href="/app" class="nav-btn nav-btn-primary" onclick="closeDrawer()" style="font-size:16px;padding:12px 28px">Launch App</a>
</div>


<!-- ══════════════════════════════════════════════════════════════════════════
     HERO
════════════════════════════════════════════════════════════════════════════ -->
<section id="hero" class="scene">
  <div class="hero-glow glow-1"></div>
  <div class="hero-glow glow-2"></div>
  <div class="hero-glow glow-3"></div>

  <div class="hero-badge" style="position:relative;z-index:1;">
    <span class="live-dot"></span>
    Now live — horizon-orchestra.com
  </div>

  <h1 style="position:relative;z-index:1;">
    Your AI.<br>
    <span class="grad-text">Your Machine.</span><br>
    Your Rules.
  </h1>

  <p style="position:relative;z-index:1;margin-top:28px;">
    Orchestra is autonomous AI for healthcare, legal, and finance professionals.
    Local-first. Multi-model. Yours — not ours.
  </p>

  <div class="cta-pair" style="position:relative;z-index:1;justify-content:center;margin-top:44px;">
    <a href="/app" class="cta-primary">Launch Orchestra</a>
    <a href="/miles" class="cta-secondary" style="border-color:var(--cyan);color:var(--cyan);">Open MILES</a>
    <a href="http://localhost:3001" class="cta-secondary" style="border-color:var(--purple);color:var(--purple);">OpenJARVIS</a>
  </div>
</section>

<div class="hairline"></div>

<!-- ══════════════════════════════════════════════════════════════════════════
     APP HUB
════════════════════════════════════════════════════════════════════════════ -->
<section style="padding:80px 24px;max-width:960px;margin:0 auto;">
  <h2 style="text-align:center;font-size:clamp(1.6rem,4vw,2.4rem);font-weight:700;letter-spacing:-0.03em;margin-bottom:12px;">
    Three Apps. One Platform.
  </h2>
  <p style="text-align:center;color:var(--text-2);max-width:520px;margin:0 auto 56px;">
    Orchestra is the hub. MILES handles conversation. OpenJARVIS runs the production API.
  </p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;">

    <!-- Orchestra App -->
    <a href="/app" style="text-decoration:none;display:flex;flex-direction:column;gap:16px;padding:28px;background:var(--surface2);border:1px solid var(--border);border-radius:16px;transition:border-color .2s,transform .2s;" onmouseover="this.style.borderColor='var(--accent)';this.style.transform='translateY(-2px)'" onmouseout="this.style.borderColor='var(--border)';this.style.transform=''">
      <div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#5b8af0,#a855f7);display:flex;align-items:center;justify-content:center;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M16.9 16.9l2.1 2.1M4.9 19.1l2.1-2.1M16.9 7.1l2.1-2.1"/></svg>
      </div>
      <div>
        <div style="font-size:1.1rem;font-weight:700;color:var(--text-1);margin-bottom:6px;">Orchestra</div>
        <div style="font-size:.875rem;color:var(--text-2);line-height:1.5;">Autonomous AI hub with domain apps for healthcare, legal, and finance. Full multi-agent workspace.</div>
      </div>
      <div style="margin-top:auto;font-size:.8rem;font-weight:600;color:var(--accent);letter-spacing:.05em;">LAUNCH APP →</div>
    </a>

    <!-- MILES -->
    <a href="/miles" style="text-decoration:none;display:flex;flex-direction:column;gap:16px;padding:28px;background:var(--surface2);border:1px solid var(--border);border-radius:16px;transition:border-color .2s,transform .2s;" onmouseover="this.style.borderColor='var(--cyan)';this.style.transform='translateY(-2px)'" onmouseout="this.style.borderColor='var(--border)';this.style.transform=''">
      <div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#00c8e8,#3b82f6);display:flex;align-items:center;justify-content:center;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </div>
      <div>
        <div style="font-size:1.1rem;font-weight:700;color:var(--text-1);margin-bottom:6px;">MILES</div>
        <div style="font-size:.875rem;color:var(--text-2);line-height:1.5;">Multi-model intelligent agent chat. Streaming conversations, tool calls, and agent execution in a sleek SPA.</div>
      </div>
      <div style="margin-top:auto;font-size:.8rem;font-weight:600;color:var(--cyan);letter-spacing:.05em;">OPEN MILES →</div>
    </a>

    <!-- OpenJARVIS -->
    <a href="http://localhost:3001" style="text-decoration:none;display:flex;flex-direction:column;gap:16px;padding:28px;background:var(--surface2);border:1px solid var(--border);border-radius:16px;transition:border-color .2s,transform .2s;" onmouseover="this.style.borderColor='var(--purple)';this.style.transform='translateY(-2px)'" onmouseout="this.style.borderColor='var(--border)';this.style.transform=''">
      <div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#a855f7,#ec4899);display:flex;align-items:center;justify-content:center;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
      </div>
      <div>
        <div style="font-size:1.1rem;font-weight:700;color:var(--text-1);margin-bottom:6px;">OpenJARVIS</div>
        <div style="font-size:.875rem;color:var(--text-2);line-height:1.5;">Production API server with /v1/* endpoints, auth, billing, connectors, and mobile-ready WebSocket streaming.</div>
      </div>
      <div style="margin-top:auto;font-size:.8rem;font-weight:600;color:var(--purple);letter-spacing:.05em;">OPEN JARVIS →</div>
    </a>

  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     STATEMENT 1 — Privacy
════════════════════════════════════════════════════════════════════════════ -->
<div class="statement">
  <h2>AI built for work where<br><span class="grad-text">privacy isn't optional.</span><br><em>Healthcare. Legal. Finance.</em></h2>
</div>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     FEATURE — Healthcare
════════════════════════════════════════════════════════════════════════════ -->
<section id="features" class="feature-scene" style="background:var(--void);">
  <div class="feature-copy">
    <div class="scene-tag">Healthcare</div>
    <h2>HIPAA-ready<br>from day one.</h2>
    <p>Patient records, clinical notes, appointment scheduling, and insurance claims — managed by AI that never leaves your machine.</p>
    <div class="cta-pair">
      <a href="/healthcare/app" class="cta-secondary">Explore Healthcare</a>
    </div>
  </div>
  <div class="feature-visual" style="background: linear-gradient(135deg, #0a0c14 0%, #0f0814 100%);">
    <div class="chat-mockup">
      <div class="chat-header">
        <div class="chat-avatar">🏥</div>
        Orchestra Health
        <span style="margin-left:auto;font-size:11px;color:var(--green);background:rgba(52,211,153,.12);padding:3px 10px;border-radius:100px;font-weight:600;">HIPAA</span>
      </div>
      <div class="chat-body">
        <div class="chat-bubble bubble-user">Summarize today's patient encounters and flag any incomplete SOAP notes.</div>
        <div class="chat-bubble bubble-ai">Found 4 encounters today. 3 notes are complete. <strong style="color:var(--text-1);">Patient #2847</strong> is missing the Assessment section — I've drafted it based on the visit data. Want me to send it for your review?</div>
        <div class="chat-bubble bubble-user">Yes, and check if her Rx needs renewal.</div>
        <div class="chat-bubble bubble-ai">Metformin 500mg — last filled 82 days ago, 30-day supply. Renewal due. Shall I prepare the prior auth form?</div>
      </div>
      <div class="chat-input-row">
        <div class="chat-input-fake">Message Orchestra Health…</div>
        <div class="chat-send-fake">↑</div>
      </div>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     FEATURE — Legal (flipped)
════════════════════════════════════════════════════════════════════════════ -->
<section class="feature-scene flip" style="background:var(--deep);">
  <div class="feature-copy">
    <div class="scene-tag">Legal</div>
    <h2>Privilege-safe.<br><span class="grad-text-warm">Always.</span></h2>
    <p>Client matters, time entries, invoice generation, and AI-assisted drafting — all air-gapped by default. Attorney-client privilege preserved at the architecture level.</p>
    <div class="cta-pair">
      <a href="/legal/app" class="cta-secondary">Explore Legal</a>
    </div>
  </div>
  <div class="feature-visual" style="background: linear-gradient(135deg, #0c0a14 0%, #0f0c0a 100%);">
    <div class="data-mockup">
      <div class="data-mockup-header">
        <span>Active Matters</span>
        <span class="badge">3 unbilled hrs</span>
      </div>
      <div class="data-row header"><span>Matter</span><span>Hours</span><span>Value</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Meridian v. Apex</span><span style="color:var(--text-2);">12.5h</span><span style="color:var(--green);">$3,125</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Estate of Harmon</span><span style="color:var(--text-2);">6.0h</span><span style="color:var(--green);">$1,500</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Reeves IP Filing</span><span style="color:var(--text-2);">8.75h</span><span style="color:var(--green);">$2,187</span></div>
      <div class="data-row" style="background:rgba(91,138,240,.04);padding:14px 20px;">
        <span style="color:var(--text-2);font-size:12px;">AI summary</span>
        <span style="grid-column:span 2;text-align:left;font-size:12px;color:var(--text-2);padding-left:20px;">Meridian deadline: <span style="color:var(--rose);">3 days</span></span>
      </div>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     FEATURE — Finance
════════════════════════════════════════════════════════════════════════════ -->
<section class="feature-scene" style="background:var(--void);">
  <div class="feature-copy">
    <div class="scene-tag">Finance</div>
    <h2>Audit-ready<br><span class="grad-text-green">intelligence.</span></h2>
    <p>Double-entry accounting, portfolio analytics, P&amp;L reporting, and AI-driven transaction categorization — built for quants, family offices, and PE teams.</p>
    <div class="cta-pair">
      <a href="/finance/app" class="cta-secondary">Explore Finance</a>
    </div>
  </div>
  <div class="feature-visual" style="background: linear-gradient(135deg, #080c0a 0%, #0a0c14 100%);">
    <div class="data-mockup">
      <div class="data-mockup-header">
        <span>Portfolio Overview</span>
        <span class="badge">+4.2% MTD</span>
      </div>
      <div class="data-row header"><span>Position</span><span>Alloc</span><span>Return</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">US Equities</span><span style="color:var(--text-2);">42%</span><span class="data-pos">+6.1%</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Fixed Income</span><span style="color:var(--text-2);">28%</span><span class="data-pos">+1.8%</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Int'l Equity</span><span style="color:var(--text-2);">18%</span><span class="data-neg">-0.4%</span></div>
      <div class="data-row"><span style="color:var(--text-1);font-weight:500;">Alternatives</span><span style="color:var(--text-2);">12%</span><span class="data-pos">+9.3%</span></div>
      <div class="data-row" style="background:rgba(52,211,153,.04);">
        <span style="color:var(--text-3);font-size:12px;">AI insight</span>
        <span style="grid-column:span 2;font-size:12px;color:var(--green);padding-left:20px;text-align:left;">Alts outperforming — rebalance?</span>
      </div>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     FEATURE — Code Agent (flipped)
════════════════════════════════════════════════════════════════════════════ -->
<section class="feature-scene flip" style="background:var(--deep);">
  <div class="feature-copy">
    <div class="scene-tag">Engineering</div>
    <h2>Autonomous.<br>No hand-holding.</h2>
    <p>A full agentic loop: read files, run shell commands, write code, plan multi-step tasks — all in a persistent session with complete context memory.</p>
    <div class="cta-pair">
      <a href="/app" class="cta-secondary">Open Code Agent</a>
    </div>
  </div>
  <div class="feature-visual" style="background: linear-gradient(135deg, #060a0c 0%, #080c0f 100%);">
    <div class="mockup">
      <div class="mockup-bar">
        <span class="mock-dot"></span><span class="mock-dot"></span><span class="mock-dot"></span>
        <span style="flex:1;text-align:center;font-size:11px;color:var(--text-3);font-family:var(--mono);">orchestra agent</span>
      </div>
      <div class="mockup-body" id="code-terminal">
        <div class="mock-line"><span class="mock-prompt">$</span><span class="mock-cmd" id="code-cmd"></span></div>
        <div id="code-output"></div>
      </div>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     STATEMENT 2 — Local
════════════════════════════════════════════════════════════════════════════ -->
<div class="statement" style="background:var(--void);">
  <h2><span class="grad-text">Your data never leaves</span><br>your machine.<br><em>Not our server. Yours.</em></h2>
</div>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     MODELS
════════════════════════════════════════════════════════════════════════════ -->
<section id="models" class="models-scene">
  <div class="scene-tag">Models</div>
  <h2 style="font-size:clamp(36px,5.5vw,68px);font-weight:700;letter-spacing:-2px;line-height:1.08;color:var(--text-1);">Every frontier model.<br>One interface.</h2>
  <p style="font-size:17px;color:var(--text-2);margin-top:18px;max-width:44ch;">Configure your own API keys. Route to any model. Switch without changing anything else.</p>

  <div class="models-grid">
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#5b8af0;box-shadow:0 0 8px #5b8af0;"></div>
      <div>
        <div class="model-pill-name">Claude Sonnet 4.6</div>
        <div class="model-pill-sub">Default · Anthropic</div>
      </div>
    </div>
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#a855f7;box-shadow:0 0 8px #a855f7;"></div>
      <div>
        <div class="model-pill-name">Claude Haiku 4.5</div>
        <div class="model-pill-sub">Fast · Anthropic</div>
      </div>
    </div>
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#00c8e8;box-shadow:0 0 8px #00c8e8;"></div>
      <div>
        <div class="model-pill-name">Claude 3 Opus</div>
        <div class="model-pill-sub">Powerful · Anthropic</div>
      </div>
    </div>
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#34d399;box-shadow:0 0 8px #34d399;"></div>
      <div>
        <div class="model-pill-name">GPT-4o</div>
        <div class="model-pill-sub">Vision · OpenAI</div>
      </div>
    </div>
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#f472b6;box-shadow:0 0 8px #f472b6;"></div>
      <div>
        <div class="model-pill-name">Claude 3.5 Sonnet</div>
        <div class="model-pill-sub">Code specialist · Anthropic</div>
      </div>
    </div>
    <div class="model-pill">
      <div class="model-pill-dot" style="background:#fb923c;box-shadow:0 0 8px #fb923c;"></div>
      <div>
        <div class="model-pill-name">Ollama (any model)</div>
        <div class="model-pill-sub">Air-gapped · Local</div>
      </div>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     LIVE DEMO
════════════════════════════════════════════════════════════════════════════ -->
<section id="demo" class="demo-scene">
  <div class="scene-tag">Try it now</div>
  <h2 style="font-size:clamp(36px,5vw,64px);font-weight:700;letter-spacing:-2px;color:var(--text-1);">Ask Orchestra anything.</h2>
  <p style="font-size:17px;color:var(--text-2);margin-top:16px;max-width:40ch;">Live — connected to the real API. Your query, your chosen model, your answer.</p>

  <div class="demo-box">
    <div class="demo-topbar">
      <span>Orchestra · Live Query</span>
      <select class="demo-model-pick" id="demo-model">
        <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
        <option value="claude-haiku-4-5-20251001">Claude Haiku 4.5</option>
        <option value="gpt-4o">GPT-4o</option>
      </select>
    </div>
    <div id="demo-messages">
      <div class="dmsg dmsg-ai">
        <div class="dmsg-av">🎼</div>
        <div class="dmsg-text">Ask me anything — healthcare compliance, a legal question, a finance concept, or a coding task. I'm live.</div>
      </div>
    </div>
    <div class="demo-row">
      <input class="demo-inp" id="demo-inp" placeholder="e.g. What does HIPAA say about AI-generated clinical notes?" />
      <button class="demo-go" id="demo-go">Ask →</button>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     SECURITY
════════════════════════════════════════════════════════════════════════════ -->
<section class="security-scene">
  <div class="scene-tag">Security</div>
  <h2 style="font-size:clamp(32px,4.5vw,60px);font-weight:700;letter-spacing:-1.5px;color:var(--text-1);">Zero-trust by default.</h2>
  <p style="font-size:17px;color:var(--text-2);margin-top:16px;max-width:40ch;">Every layer of Orchestra is hardened for high-stakes professional use.</p>
  <div class="security-checks">
    <div class="security-chip"><span class="check">✓</span> JWT authentication</div>
    <div class="security-chip"><span class="check">✓</span> CSRF protection</div>
    <div class="security-chip"><span class="check">✓</span> Per-user data isolation</div>
    <div class="security-chip"><span class="check">✓</span> Rate limiting</div>
    <div class="security-chip"><span class="check">✓</span> Brute-force lockout</div>
    <div class="security-chip"><span class="check">✓</span> 30-min idle timeout</div>
    <div class="security-chip"><span class="check">✓</span> Secure cookies</div>
    <div class="security-chip"><span class="check">✓</span> Encrypted key storage</div>
    <div class="security-chip"><span class="check">✓</span> Local SQLite — no cloud DB</div>
    <div class="security-chip"><span class="check">✓</span> HTTPS enforced</div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     PRICING
════════════════════════════════════════════════════════════════════════════ -->
<section id="pricing" class="pricing-scene">
  <div class="scene-tag">Pricing</div>
  <h2 style="font-size:clamp(36px,5vw,64px);font-weight:700;letter-spacing:-2px;color:var(--text-1);">Simple. Transparent.<br>No markup on AI costs.</h2>
  <p style="font-size:17px;color:var(--text-2);margin-top:16px;max-width:42ch;">Bring your own API keys. You pay your AI provider directly — Orchestra never touches that bill.</p>

  <div class="pricing-grid">
    <div class="p-card">
      <div class="p-tier">Free</div>
      <div class="p-price"><sup>$</sup>0</div>
      <div class="p-per">forever</div>
      <ul class="p-items">
        <li>Orchestra platform — full access</li>
        <li>Bring your own API keys</li>
        <li>Healthcare, Legal & Finance modules</li>
        <li>Code agent sessions</li>
        <li>Local SQLite — your machine</li>
        <li>Community support</li>
      </ul>
      <a href="/signup" class="p-cta p-cta-outline">Get started free</a>
    </div>

    <div class="p-card featured">
      <div class="p-badge">Most popular</div>
      <div class="p-tier">Pro</div>
      <div class="p-price"><sup>$</sup>19</div>
      <div class="p-per">per month</div>
      <ul class="p-items">
        <li>Everything in Free</li>
        <li>Managed API key storage</li>
        <li>Priority model routing</li>
        <li>Session history & export</li>
        <li>HIPAA idle timeout (30 min)</li>
        <li>Email support</li>
      </ul>
      <a href="/signup?plan=pro" class="p-cta p-cta-fill">Start Pro trial</a>
    </div>

    <div class="p-card">
      <div class="p-tier">Enterprise</div>
      <div class="p-price"><sup>$</sup>99</div>
      <div class="p-per">per month</div>
      <ul class="p-items">
        <li>Everything in Pro</li>
        <li>Self-hosted deployment</li>
        <li>SSO / SAML</li>
        <li>Audit logging & compliance</li>
        <li>Custom model integration</li>
        <li>Dedicated support</li>
      </ul>
      <a href="mailto:ashtonfritz3@gmail.com?subject=Orchestra%20Enterprise" class="p-cta p-cta-outline">Contact us</a>
    </div>
  </div>
</section>

<div class="hairline"></div>


<!-- ══════════════════════════════════════════════════════════════════════════
     FINALE CTA
════════════════════════════════════════════════════════════════════════════ -->
<section class="finale">
  <h2><span class="grad-text">Ready to orchestrate?</span></h2>
  <p>Your AI, your machine, your rules. Free to start — no credit card required.</p>
  <div class="cta-pair">
    <a href="/signup" class="cta-primary">Create free account</a>
    <a href="/app" class="cta-secondary">Open the app</a>
  </div>
</section>


<!-- ══════════════════════════════════════════════════════════════════════════
     FOOTER
════════════════════════════════════════════════════════════════════════════ -->
<footer>
  <div class="footer-row">
    <div class="footer-brand">
      <a href="/" class="nav-logo" style="font-size:16px;">
        <svg viewBox="0 0 28 28" width="24" height="24" fill="none">
          <rect width="28" height="28" rx="7" fill="#0f1117"/>
          <line x1="7" y1="5.5" x2="7" y2="22.5" stroke="#5b8af0" stroke-width="1.4"/>
          <line x1="10.5" y1="3.5" x2="10.5" y2="24.5" stroke="#7a9df5" stroke-width="1.4"/>
          <line x1="14" y1="3" x2="14" y2="25" stroke="#a855f7" stroke-width="1.6"/>
          <line x1="17.5" y1="3.5" x2="17.5" y2="24.5" stroke="#7a9df5" stroke-width="1.4"/>
          <line x1="21" y1="5.5" x2="21" y2="22.5" stroke="#5b8af0" stroke-width="1.4"/>
          <ellipse cx="14" cy="14" rx="2" ry="2" fill="#00c8e8"/>
        </svg>
        Orchestra
      </a>
      <p>Autonomous AI for professionals who need privacy. Local-first, multi-model, built for high-stakes work.</p>
    </div>
    <div class="footer-col">
      <h5>Product</h5>
      <ul>
        <li><a href="/app">Launch app</a></li>
        <li><a href="#features">Features</a></li>
        <li><a href="#models">Models</a></li>
        <li><a href="#pricing">Pricing</a></li>
        <li><a href="/docs">API docs</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <h5>Verticals</h5>
      <ul>
        <li><a href="/healthcare/app">Healthcare</a></li>
        <li><a href="/legal/app">Legal</a></li>
        <li><a href="/finance/app">Finance</a></li>
        <li><a href="/app">Code Agent</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <h5>Account</h5>
      <ul>
        <li><a href="/login">Sign in</a></li>
        <li><a href="/signup">Create account</a></li>
        <li><a href="/settings">Settings</a></li>
        <li><a href="/forgot-password">Reset password</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <p>Copyright © 2026 Orchestra / Horizon Orchestra. All rights reserved.</p>
    <p><a href="https://horizon-orchestra.com">horizon-orchestra.com</a></p>
  </div>
</footer>


<!-- ══════════════════════════════════════════════════════════════════════════
     SCRIPTS
════════════════════════════════════════════════════════════════════════════ -->
<script>
// ── Mobile nav drawer ────────────────────────────────────────────────────────
function toggleDrawer() {
  const d = document.getElementById('navDrawer');
  const b = document.getElementById('navHamburger');
  d.classList.toggle('open');
  b.classList.toggle('open');
  document.body.style.overflow = d.classList.contains('open') ? 'hidden' : '';
}
function closeDrawer() {
  document.getElementById('navDrawer').classList.remove('open');
  document.getElementById('navHamburger').classList.remove('open');
  document.body.style.overflow = '';
}
// Close drawer on escape
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

// ── Nav opacity on scroll ────────────────────────────────────────────────────
window.addEventListener('scroll', () => {
  document.getElementById('nav').style.background =
    window.scrollY > 40 ? 'rgba(0,0,0,0.88)' : 'rgba(0,0,0,0.72)';
}, { passive: true });

// ── Hero glow parallax ───────────────────────────────────────────────────────
(function () {
  const glows = document.querySelectorAll('.hero-glow');
  document.addEventListener('mousemove', (e) => {
    const cx = window.innerWidth / 2, cy = window.innerHeight / 2;
    const dx = (e.clientX - cx) / cx, dy = (e.clientY - cy) / cy;
    glows.forEach((g, i) => {
      const s = (i + 1) * 16;
      g.style.transform = `translate(${dx * s}px, ${dy * s}px)`;
    });
  }, { passive: true });
})();

// ── Code agent terminal typewriter ───────────────────────────────────────────
(function () {
  const lines = [
    { type: 'cmd', text: 'orchestra run "refactor auth to use JWT refresh tokens"' },
    { type: 'out', text: '  ✦  Reading src/auth/session.py…', cls: 'hi' },
    { type: 'out', text: '  ✦  Planning 4-step task…', cls: 'hi' },
    { type: 'out', text: '  ✎  Writing auth/jwt.py', cls: '' },
    { type: 'out', text: '  ✎  Updating session middleware', cls: '' },
    { type: 'out', text: '  ✦  Running tests… 24 passed', cls: 'ok' },
    { type: 'out', text: '  ✓  Done in 8.4s — 3 files changed', cls: 'ok' },
  ];
  const cmdEl = document.getElementById('code-cmd');
  const outEl = document.getElementById('code-output');
  if (!cmdEl) return;
  let li = 0, ci = 0;

  function tick() {
    if (li >= lines.length) {
      setTimeout(() => { outEl.innerHTML = ''; cmdEl.textContent = ''; li = 0; ci = 0; tick(); }, 3500);
      return;
    }
    const l = lines[li];
    if (l.type === 'cmd') {
      if (ci < l.text.length) { cmdEl.textContent = l.text.slice(0, ++ci); setTimeout(tick, 22); }
      else { li++; ci = 0; setTimeout(tick, 350); }
    } else {
      const d = document.createElement('div');
      d.className = 'mock-out' + (l.cls ? ' ' + l.cls : '');
      d.textContent = l.text;
      outEl.appendChild(d);
      li++;
      setTimeout(tick, 160);
    }
  }
  setTimeout(tick, 900);
})();

// ── Live query demo ──────────────────────────────────────────────────────────
(function () {
  const inp = document.getElementById('demo-inp');
  const go  = document.getElementById('demo-go');
  const box = document.getElementById('demo-messages');
  const mdl = document.getElementById('demo-model');
  if (!inp) return;

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
  }
  function addMsg(role, text) {
    const d = document.createElement('div');
    d.className = 'dmsg dmsg-' + role;
    d.innerHTML = `<div class="dmsg-av">${role === 'user' ? '👤' : '🎼'}</div><div class="dmsg-text">${esc(text)}</div>`;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
    return d;
  }
  function addTyping() {
    const d = document.createElement('div');
    d.className = 'dmsg dmsg-ai'; d.id = '_typing';
    d.innerHTML = `<div class="dmsg-av">🎼</div><div class="dmsg-text"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
    box.appendChild(d); box.scrollTop = box.scrollHeight;
  }

  async function send() {
    const q = inp.value.trim(); if (!q) return;
    inp.value = ''; go.disabled = true;
    addMsg('user', q);
    addTyping();
    try {
      const r = await fetch('/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: q, model: mdl.value, temperature: 0.7, max_tokens: 400 }),
      });
      const j = await r.json();
      document.getElementById('_typing')?.remove();
      addMsg('ai', (j.data && j.data.response) || j.response || 'No response.');
    } catch {
      document.getElementById('_typing')?.remove();
      addMsg('ai', 'Could not reach Orchestra API — is the server running?');
    } finally { go.disabled = false; inp.focus(); }
  }

  go.addEventListener('click', send);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
})();
</script>
</body>
</html>"""
