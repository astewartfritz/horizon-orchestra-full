from __future__ import annotations


# ---------------------------------------------------------------------------
# Login page — HTMX form targeting /v1/auth/login.  On success the server
# sets an httpOnly cookie and the client redirects to /app.
# ---------------------------------------------------------------------------

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign In — Orchestra</title>
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<style>
:root {
  --bg-primary: #0d1117; --bg-secondary: #161b22; --bg-tertiary: #1c2128;
  --border: #30363d; --text-primary: #e6edf3; --text-secondary: #8b949e;
  --text-link: #58a6ff; --accent-blue: #1f6feb; --accent-blue-hover: #388bfd;
  --accent-green: #238636; --accent-green-hover: #2ea043; --accent-red: #da3633;
  --radius-md: 8px; --radius-lg: 12px;
  --font-sans: 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-sans); background: var(--bg-primary); color: var(--text-primary);
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
}
.card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 40px; width: 100%; max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.logo { text-align: center; margin-bottom: 32px; }
.logo h1 { font-size: 28px; font-weight: 700; background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.logo p { color: var(--text-secondary); font-size: 14px; margin-top: 4px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 13px; font-weight: 500; color: var(--text-secondary); margin-bottom: 6px; }
.form-group input {
  width: 100%; padding: 10px 14px; background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-primary); font-size: 14px;
  font-family: var(--font-sans); outline: none; transition: border-color 0.15s;
}
.form-group input:focus { border-color: var(--accent-blue); }
.btn-primary {
  width: 100%; padding: 12px; background: var(--accent-blue); color: #fff;
  border: none; border-radius: var(--radius-md); font-size: 15px; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.btn-primary:hover { background: var(--accent-blue-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.error {
  background: rgba(218,54,51,0.12); border: 1px solid rgba(218,54,51,0.3);
  color: #f85149; padding: 10px 14px; border-radius: var(--radius-md);
  font-size: 13px; margin-bottom: 16px; display: none;
}
.footer { text-align: center; margin-top: 24px; font-size: 13px; color: var(--text-secondary); }
.footer a { color: var(--text-link); text-decoration: none; }
.footer a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>Orchestra</h1>
    <p>Sign in to your account</p>
  </div>
  <div id="auth-error" class="error"></div>
  <form hx-post="/v1/auth/login"
        hx-on::before-request="document.getElementById('auth-error').style.display='none'"
        hx-on::after-request="
          const r=JSON.parse(event.detail.xhr.responseText);
          if(event.detail.successful && r.data && r.data.access_token) {
            window.location.href='/getting-started?email='+encodeURIComponent(r.data.user.email);
          } else {
            const d=document.getElementById('auth-error');
            d.textContent=r.error||'Login failed';
            d.style.display='block';
          }
        ">
    <div class="form-group">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" placeholder="you@example.com" required autocomplete="email">
    </div>
    <div class="form-group">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" placeholder="Enter your password" required autocomplete="current-password">
    </div>
    <button type="submit" class="btn-primary">Sign In</button>
  </form>
  <div class="footer">
    <a href="/forgot-password" style="display:block;margin-bottom:8px">Forgot your password?</a>
    Don't have an account? <a href="/signup">Create one</a>
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Signup page — HTMX form targeting /v1/auth/register.
# ---------------------------------------------------------------------------

SIGNUP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Create Account — Orchestra</title>
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<style>
:root {
  --bg-primary: #0d1117; --bg-secondary: #161b22; --bg-tertiary: #1c2128;
  --border: #30363d; --text-primary: #e6edf3; --text-secondary: #8b949e;
  --text-link: #58a6ff; --accent-blue: #1f6feb; --accent-blue-hover: #388bfd;
  --accent-green: #238636; --accent-green-hover: #2ea043; --accent-red: #da3633;
  --radius-md: 8px; --radius-lg: 12px;
  --font-sans: 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-sans); background: var(--bg-primary); color: var(--text-primary);
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
}
.card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 40px; width: 100%; max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.logo { text-align: center; margin-bottom: 32px; }
.logo h1 { font-size: 28px; font-weight: 700; background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.logo p { color: var(--text-secondary); font-size: 14px; margin-top: 4px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 13px; font-weight: 500; color: var(--text-secondary); margin-bottom: 6px; }
.form-group input {
  width: 100%; padding: 10px 14px; background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-primary); font-size: 14px;
  font-family: var(--font-sans); outline: none; transition: border-color 0.15s;
}
.form-group input:focus { border-color: var(--accent-blue); }
.btn-primary {
  width: 100%; padding: 12px; background: var(--accent-blue); color: #fff;
  border: none; border-radius: var(--radius-md); font-size: 15px; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.btn-primary:hover { background: var(--accent-blue-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.password-hint { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.error {
  background: rgba(218,54,51,0.12); border: 1px solid rgba(218,54,51,0.3);
  color: #f85149; padding: 10px 14px; border-radius: var(--radius-md);
  font-size: 13px; margin-bottom: 16px; display: none;
}
.footer { text-align: center; margin-top: 24px; font-size: 13px; color: var(--text-secondary); }
.footer a { color: var(--text-link); text-decoration: none; }
.footer a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>Orchestra</h1>
    <p>Create your free account</p>
  </div>
  <div id="auth-error" class="error"></div>
  <form hx-post="/v1/auth/register"
        hx-on::before-request="document.getElementById('auth-error').style.display='none'"
        hx-on::after-request="
          const r=JSON.parse(event.detail.xhr.responseText);
          if(event.detail.successful && r.data && r.data.access_token) {
            window.location.href='/getting-started?email='+encodeURIComponent(r.data.user.email);
          } else {
            const d=document.getElementById('auth-error');
            d.textContent=r.error||'Registration failed';
            d.style.display='block';
          }
        ">
    <div class="form-group">
      <label for="name">Full Name</label>
      <input type="text" id="name" name="name" placeholder="Your name" required>
    </div>
    <div class="form-group">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" placeholder="you@example.com" required autocomplete="email">
    </div>
    <div class="form-group">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" placeholder="At least 8 characters" required minlength="8" autocomplete="new-password">
      <div class="password-hint">Must be at least 8 characters</div>
    </div>
    <button type="submit" class="btn-primary" id="signup-btn">Create Account</button>
  </form>
  <div class="footer">
    Already have an account? <a href="/login">Sign in</a>
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Forgot-password page — requests a reset code by email.
# ---------------------------------------------------------------------------

FORGOT_PASSWORD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reset Password — Orchestra</title>
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<style>
:root {
  --bg-primary:#0d1117;--bg-secondary:#161b22;--bg-tertiary:#1c2128;
  --border:#30363d;--text-primary:#e6edf3;--text-secondary:#8b949e;
  --text-link:#58a6ff;--accent-blue:#1f6feb;--accent-blue-hover:#388bfd;
  --accent-green:#238636;--accent-red:#da3633;
  --radius-md:8px;--radius-lg:12px;
  --font-sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font-sans);background:var(--bg-primary);color:var(--text-primary);min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-lg);padding:40px;width:100%;max-width:420px;box-shadow:0 8px 32px rgba(0,0,0,.5)}
.logo{text-align:center;margin-bottom:32px}
.logo h1{font-size:28px;font-weight:700;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.logo p{color:var(--text-secondary);font-size:14px;margin-top:4px}
.form-group{margin-bottom:20px}
.form-group label{display:block;font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px}
.form-group input{width:100%;padding:10px 14px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-md);color:var(--text-primary);font-size:14px;outline:none;transition:border-color .15s}
.form-group input:focus{border-color:var(--accent-blue)}
.btn-primary{width:100%;padding:12px;background:var(--accent-blue);color:#fff;border:none;border-radius:var(--radius-md);font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}
.btn-primary:hover{background:var(--accent-blue-hover)}
.msg{padding:12px 14px;border-radius:var(--radius-md);font-size:13px;margin-bottom:16px;display:none}
.msg.error{background:rgba(218,54,51,.12);border:1px solid rgba(218,54,51,.3);color:#f85149}
.msg.success{background:rgba(35,134,54,.12);border:1px solid rgba(35,134,54,.3);color:#3fb950}
.footer{text-align:center;margin-top:24px;font-size:13px;color:var(--text-secondary)}
.footer a{color:var(--text-link);text-decoration:none}
#step2{display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><h1>Orchestra</h1><p>Reset your password</p></div>
  <div id="msg" class="msg"></div>

  <div id="step1">
    <form id="reqForm">
      <div class="form-group">
        <label for="email">Email address</label>
        <input type="email" id="email" name="email" placeholder="you@example.com" required autocomplete="email">
      </div>
      <button type="submit" class="btn-primary">Send Reset Code</button>
    </form>
  </div>

  <div id="step2">
    <form id="resetForm">
      <div class="form-group">
        <label for="code">Reset Code</label>
        <input type="text" id="code" name="code" placeholder="6-digit code from email" required maxlength="6" inputmode="numeric">
      </div>
      <div class="form-group">
        <label for="newpw">New Password</label>
        <input type="password" id="newpw" name="newpw" placeholder="At least 8 characters" required autocomplete="new-password">
      </div>
      <button type="submit" class="btn-primary">Set New Password</button>
    </form>
  </div>

  <div class="footer"><a href="/login">Back to Sign In</a></div>
</div>
<script>
function showMsg(text, type) {
  const m = document.getElementById('msg');
  m.textContent = text; m.className = 'msg ' + type; m.style.display = 'block';
}
document.getElementById('reqForm').addEventListener('submit', async e => {
  e.preventDefault();
  const email = document.getElementById('email').value;
  const r = await fetch('/v1/auth/forgot-password', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email})
  });
  const d = await r.json();
  if (d.data) {
    showMsg('Check your email for a 6-digit code.', 'success');
    document.getElementById('step1').style.display = 'none';
    document.getElementById('step2').style.display = 'block';
  } else {
    showMsg(d.error || 'Something went wrong', 'error');
  }
});
document.getElementById('resetForm').addEventListener('submit', async e => {
  e.preventDefault();
  const code = document.getElementById('code').value;
  const password = document.getElementById('newpw').value;
  const r = await fetch('/v1/auth/reset-password', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({code, password})
  });
  const d = await r.json();
  if (d.data) {
    showMsg('Password updated! Redirecting to login…', 'success');
    setTimeout(() => window.location.href = '/login', 1500);
  } else {
    showMsg(d.error || 'Invalid or expired code', 'error');
  }
});
// Pre-fill code from URL ?code=
const params = new URLSearchParams(location.search);
if (params.get('code')) {
  document.getElementById('code').value = params.get('code');
  document.getElementById('step1').style.display = 'none';
  document.getElementById('step2').style.display = 'block';
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Getting-started page — shown after first login to walk through setup.
# ---------------------------------------------------------------------------

GETTING_STARTED_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Getting Started — Orchestra</title>
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<style>
:root {
  --bg-primary: #0d1117; --bg-secondary: #161b22; --bg-tertiary: #1c2128;
  --border: #30363d; --text-primary: #e6edf3; --text-secondary: #8b949e;
  --text-link: #58a6ff; --accent-blue: #1f6feb; --accent-blue-hover: #388bfd;
  --accent-green: #238636; --accent-green-hover: #2ea043; --accent-red: #da3633;
  --accent-purple: #a371f7; --accent-orange: #d29922;
  --radius-md: 8px; --radius-lg: 12px;
  --font-sans: 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --font-mono: 'SF Mono','Fira Code','JetBrains Mono',monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-sans); background: var(--bg-primary); color: var(--text-primary);
  min-height: 100vh;
}
/* Nav bar */
.nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 32px; border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}
.nav-brand { font-weight: 700; font-size: 18px; }
.nav-brand span { background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.nav-user { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--text-secondary); }
.nav-user a { color: var(--text-link); text-decoration: none; }
.nav-user a:hover { text-decoration: underline; }
/* Main content */
.container { max-width: 800px; margin: 0 auto; padding: 48px 24px; }
h1 { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
.subtitle { color: var(--text-secondary); font-size: 16px; margin-bottom: 40px; }
/* Steps */
.step { display: flex; gap: 20px; margin-bottom: 36px; }
.step-number {
  flex-shrink: 0; width: 48px; height: 48px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700; color: #fff;
}
.step-number.s1 { background: var(--accent-blue); }
.step-number.s2 { background: var(--accent-green); }
.step-number.s3 { background: var(--accent-purple); }
.step-number.s4 { background: var(--accent-orange); }
.step-content { padding-top: 12px; }
.step-content h3 { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.step-content p { color: var(--text-secondary); font-size: 14px; line-height: 1.6; }
.step-content code {
  font-family: var(--font-mono); font-size: 13px; background: var(--bg-tertiary);
  padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border);
}
.action-card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 24px; margin-top: 20px;
}
.action-card h4 { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.badge {
  display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
  border-radius: 12px; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-done { background: rgba(35,134,54,0.2); color: var(--accent-green); }
.badge-next { background: rgba(31,111,235,0.2); color: var(--accent-blue); }
.next-steps { margin-top: 48px; padding-top: 32px; border-top: 1px solid var(--border); }
.next-steps h2 { font-size: 22px; margin-bottom: 16px; }
.next-steps ul { list-style: none; }
.next-steps li { padding: 8px 0; display: flex; align-items: center; gap: 10px; color: var(--text-secondary); font-size: 14px; }
.next-steps li::before { content: '\u2192'; color: var(--accent-blue); font-weight: 700; }
</style>
</head>
<body>
<nav class="nav">
  <div class="nav-brand"><span>Orchestra</span></div>
  <div class="nav-user">
    <span id="user-email"></span>
    <a href="/app">Go to App</a>
    <a href="/logout">Sign Out</a>
  </div>
</nav>
<div class="container">
  <h1>Welcome to Orchestra</h1>
  <p class="subtitle">You're all set. Here's what you can do next.</p>

  <div class="step">
    <div class="step-number s1">1</div>
    <div class="step-content">
      <h3>Run your first analysis <span class="badge badge-done">Done</span></h3>
      <p>Start a chat in the <a href="/app" style="color:var(--text-link)">Orchestra app</a> — ask it to analyze a molecule, search literature, or run a scientific workflow.</p>
    </div>
  </div>

  <div class="step">
    <div class="step-number s2">2</div>
    <div class="step-content">
      <h3>Choose your plan <span class="badge badge-next">Next</span></h3>
      <p>Your free tier includes the <strong>Nova Small</strong> (free) and <strong>OpenCode</strong> models. Upgrade to Builder or Pro for GPT-4o, Claude Opus, and priority compute.</p>
      <div class="action-card">
        <h4>Available Plans</h4>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;">
          <div>
            <div style="font-weight:600">Maker (Free)</div>
            <div style="font-size:12px;color:var(--text-secondary);">5 analyses/day, 1 agent</div>
          </div>
          <div>
            <div style="font-weight:600">Builder</div>
            <div style="font-size:12px;color:var(--text-secondary);">100 analyses/day, 5 agents</div>
          </div>
          <div>
            <div style="font-weight:600">Pro</div>
            <div style="font-size:12px;color:var(--text-secondary);">Unlimited, 25 agents, priority</div>
          </div>
          <div>
            <div style="font-weight:600">Enterprise</div>
            <div style="font-size:12px;color:var(--text-secondary);">Self-hosted, SSO, audit logs</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="step">
    <div class="step-number s3">3</div>
    <div class="step-content">
      <h3>Connect your data</h3>
      <p>Upload scientific data files (FASTA, VCF, SDF, HDF5) or connect to PubChem, arXiv, and NCBI databases for live retrieval.</p>
    </div>
  </div>

  <div class="step">
    <div class="step-number s4">4</div>
    <div class="step-content">
      <h3>Build a workflow</h3>
      <p>Create multi-step DAG workflows combining data ingestion, analysis, and reporting. Workflows can reuse agents across steps.</p>
    </div>
  </div>

  <div class="next-steps">
    <h2>Quick Links</h2>
    <ul>
      <li><a href="/app" style="color:var(--text-link);text-decoration:none;">Open the App</a> — start a conversation</li>
      <li>View your <a href="/profile" style="color:var(--text-link);text-decoration:none;">profile &amp; billing</a></li>
      <li>Read the <a href="/docs" style="color:var(--text-link);text-decoration:none;">documentation</a></li>
    </ul>
  </div>
</div>
<script>
const params = new URLSearchParams(window.location.search);
const name = params.get('name');
const emailEl = document.getElementById('user-email');
if (name) emailEl.textContent = name;
else if (params.get('email')) emailEl.textContent = params.get('email');
</script>
</body>
</html>"""
