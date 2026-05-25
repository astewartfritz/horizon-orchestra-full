// Orchestra API client — auto-provisions a dev session and exposes query/run
(function () {
  // Relative so this works whether served from port 8000 (production) or any other port
  const BASE = '/v1';

  // ── Session token cache ───────────────────────────────────────────────────
  let _token = sessionStorage.getItem('orchestra_token') || null;

  // Dev credentials — deterministic so the same user is reused across page reloads
  const DEV_EMAIL    = 'miles-gui@orchestra.local';
  const DEV_PASSWORD = 'orchestra-dev-2026';
  const DEV_NAME     = window.MOCK?.user?.name || 'Ashton Fritz';

  async function _ensureToken() {
    if (_token) return _token;

    // Try login first (user may already exist)
    let res = await fetch(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: DEV_EMAIL, password: DEV_PASSWORD }),
    });

    if (!res.ok) {
      // First run — register the dev user
      res = await fetch(`${BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: DEV_EMAIL, password: DEV_PASSWORD, name: DEV_NAME }),
      });
    }

    if (!res.ok) throw new Error(`Auth failed: ${res.status}`);
    const json = await res.json();
    _token = json.data?.access_token || json.data?.token;
    if (_token) sessionStorage.setItem('orchestra_token', _token);
    return _token;
  }

  // ── Core request helper ───────────────────────────────────────────────────
  async function _post(path, body) {
    const token = await _ensureToken();
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      // Token expired — clear and retry once
      _token = null;
      sessionStorage.removeItem('orchestra_token');
      return _post(path, body);
    }
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
    return json.data;
  }

  async function _get(path) {
    const token = await _ensureToken();
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (res.status === 401) {
      _token = null;
      sessionStorage.removeItem('orchestra_token');
      return _get(path);
    }
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
    return json.data;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Send a prompt to a model via /v1/query.
   * Returns the response string.
   *
   * @param {string} prompt
   * @param {object} opts  { model, system, temperature, max_tokens }
   */
  async function query(prompt, opts = {}) {
    const data = await _post('/query', {
      prompt,
      model:       opts.model       || 'claude-3-5-sonnet-20241022',
      system:      opts.system      || 'You are M.I.L.E.S — a concise, intelligent executive assistant powered by Orchestra. Give direct, actionable responses. Use markdown formatting.',
      temperature: opts.temperature ?? 0.7,
      max_tokens:  opts.max_tokens  || 1024,
    });
    return data?.response || '';
  }

  /**
   * Run a task via /v1/run (full agent orchestration).
   * Returns the full result object.
   */
  async function run(task, opts = {}) {
    return _post('/run', {
      task,
      agent_type: opts.agent_type || 'monolithic',
      model:      opts.model      || 'claude-3-5-sonnet-20241022',
      context:    opts.context    || {},
    });
  }

  /** Fetch available models */
  async function listModels() {
    return _get('/models');
  }

  /** Health-check: resolves true if API is reachable and auth works */
  async function ping() {
    try {
      await _ensureToken();
      return true;
    } catch {
      return false;
    }
  }

  // ── Model ID mapping (GUI names → API ids) ────────────────────────────────
  const MODEL_MAP = {
    'kimi-k2.5':   'claude-3-5-sonnet-20241022',  // map to available model
    'claude-opus': 'claude-3-opus-20240229',
    'gpt-5':       'gpt-4o',
    'gemma-4':     'llama-3.3-70b-versatile',
  };

  function resolveModel(guiModelId) {
    return MODEL_MAP[guiModelId] || guiModelId;
  }

  // ── Expose globally ───────────────────────────────────────────────────────
  window.OrchestraAPI = { query, run, listModels, ping, resolveModel };

  // Warm up the token in the background so the first send is instant
  _ensureToken().catch(() => {});
})();
