// Orchestra — Mock data (loaded as global `MOCK`)
(function () {
  const MOCK = {};

  MOCK.user = {
    name: 'Ashton Kemerling',
    email: 'ashton@orchestra.ai',
    plan: 'Max — $250/mo',
    initials: 'AK',
  };

  MOCK.metrics = {
    activeAgents: 24,
    tasksToday: 147,
    verticals: 9,
    testsPassing: 1450,
  };

  MOCK.health = {
    cpu: 45,
    gpu: 78,
    memory: 62,
    network: 34,
  };

  MOCK.verticals = [
    { id: 'healthcare', name: 'Healthcare', icon: 'medical', color: '#F0596A', agents: 4 },
    { id: 'legal',      name: 'Legal',      icon: 'gavel',   color: '#F5B971', agents: 3 },
    { id: 'logistics',  name: 'Logistics',  icon: 'truck',   color: '#6E6EF5', agents: 2 },
    { id: 'financial',  name: 'Financial',  icon: 'wallet',  color: '#34D399', agents: 3 },
    { id: 'manufact',   name: 'Manufacturing', icon: 'factory', color: '#00C9B8', agents: 2 },
    { id: 'retail',     name: 'Retail',     icon: 'shop',    color: '#C792EA', agents: 2 },
    { id: 'energy',     name: 'Energy',     icon: 'bolt',    color: '#F5B971', agents: 2 },
    { id: 'realestate', name: 'Real Estate',icon: 'building',color: '#89DDFF', agents: 2 },
    { id: 'nursing',    name: 'Nursing',    icon: 'nursing', color: '#00C9B8', agents: 2 },
  ];

  MOCK.agents = [
    { id: 'onco-nav', vertical: 'healthcare', name: 'OncoNavigator', desc: 'Coordinates oncology care pathways, scheduling, and clinical-trial matching.', tools: 18, status: 'online', icon: 'medical', color: '#F0596A' },
    { id: 'rx-check', vertical: 'healthcare', name: 'RxCheck', desc: 'Medication reconciliation and drug-interaction screening across patient records.', tools: 12, status: 'online', icon: 'beaker', color: '#F0596A' },
    { id: 'clinicsched', vertical: 'healthcare', name: 'ClinicScheduler', desc: 'Optimizes appointment windows and panel balancing for multi-specialty clinics.', tools: 9, status: 'busy', icon: 'calendar', color: '#F0596A' },
    { id: 'genomix', vertical: 'healthcare', name: 'GenomIX', desc: 'Variant annotation pipeline for clinical genomics reporting.', tools: 14, status: 'online', icon: 'dna', color: '#F0596A' },

    { id: 'contract-r', vertical: 'legal', name: 'ContractReview', desc: 'MSA, NDA, and SaaS agreement review with risk-weighted redlines.', tools: 11, status: 'online', icon: 'file', color: '#F5B971' },
    { id: 'compliance', vertical: 'legal', name: 'ComplianceAudit', desc: 'Maps obligations across GDPR, CCPA, HIPAA, and SOC 2 for gap analysis.', tools: 15, status: 'online', icon: 'shield', color: '#F5B971' },
    { id: 'case-brief', vertical: 'legal', name: 'CaseBriefer', desc: 'Summarizes precedent and prepares litigation briefs with citation trails.', tools: 8, status: 'online', icon: 'gavel', color: '#F5B971' },

    { id: 'route-opt', vertical: 'logistics', name: 'RouteOptimizer', desc: 'Multi-stop routing with time windows, DOT compliance, and fuel cost.', tools: 10, status: 'online', icon: 'truck', color: '#6E6EF5' },
    { id: 'stock-watch', vertical: 'logistics', name: 'InventoryWatch', desc: 'Detects anomalies in stock flow and recommends replenishment orders.', tools: 7, status: 'busy', icon: 'activity', color: '#6E6EF5' },

    { id: 'risk-m', vertical: 'financial', name: 'RiskModeler', desc: 'Monte Carlo exposure simulations with live market factor updates.', tools: 16, status: 'online', icon: 'graph', color: '#34D399' },
    { id: 'recon-ai', vertical: 'financial', name: 'ReconAI', desc: 'Daily bank reconciliation, variance explanations, and flagged write-offs.', tools: 9, status: 'online', icon: 'wallet', color: '#34D399' },
    { id: 'kyc-sent', vertical: 'financial', name: 'KYCSentinel', desc: 'AML and KYC screening across global sanctions and PEP lists.', tools: 13, status: 'online', icon: 'shield', color: '#34D399' },

    { id: 'line-twin', vertical: 'manufact', name: 'LineTwin', desc: 'Digital twin of production lines; predicts throughput under load shifts.', tools: 11, status: 'online', icon: 'factory', color: '#00C9B8' },
    { id: 'qc-vision', vertical: 'manufact', name: 'QCVision', desc: 'Real-time defect detection via vision pipelines and SPC charts.', tools: 8, status: 'online', icon: 'beaker', color: '#00C9B8' },

    { id: 'merchai', vertical: 'retail', name: 'MerchAI', desc: 'Assortment planning and markdown optimization across SKUs.', tools: 10, status: 'online', icon: 'shop', color: '#C792EA' },
    { id: 'voc', vertical: 'retail', name: 'VOCMiner', desc: 'Voice-of-customer extraction from reviews, support tickets, and chat.', tools: 6, status: 'online', icon: 'chat', color: '#C792EA' },

    { id: 'grid-sense', vertical: 'energy', name: 'GridSense', desc: 'Load forecasting and outage correlation across distribution networks.', tools: 12, status: 'online', icon: 'bolt', color: '#F5B971' },
    { id: 'methane-w', vertical: 'energy', name: 'MethaneWatch', desc: 'Satellite-fed emissions anomaly detection for operations sites.', tools: 7, status: 'online', icon: 'activity', color: '#F5B971' },

    { id: 're-val', vertical: 'realestate', name: 'ValueLens', desc: 'Automated valuation model with comparables and cap-rate sensitivity.', tools: 9, status: 'online', icon: 'graph', color: '#89DDFF' },
    { id: 'deal-flow', vertical: 'realestate', name: 'DealFlow', desc: 'Pipeline tracker for CRE acquisitions with underwriting aids.', tools: 8, status: 'busy', icon: 'building', color: '#89DDFF' },

    { id: 'shift-bal', vertical: 'nursing', name: 'ShiftBalancer', desc: 'Fair-rotation scheduler with acuity-based patient assignment.', tools: 7, status: 'online', icon: 'nursing', color: '#00C9B8' },
    { id: 'safe-sign', vertical: 'nursing', name: 'SafeSign', desc: 'Monitors vitals feeds and triggers tiered escalations.', tools: 10, status: 'online', icon: 'shield', color: '#00C9B8' },
  ];

  // Recent activity feed
  MOCK.activity = [
    { icon: 'medical', color: '#F0596A', who: 'OncoNavigator', op: 'completed', what: 'trial matching for patient cohort 2041', time: '2m ago' },
    { icon: 'file',    color: '#F5B971', who: 'ContractReview', op: 'flagged', what: '3 risks in NorthPeak MSA revision 7', time: '5m ago' },
    { icon: 'truck',   color: '#6E6EF5', who: 'RouteOptimizer', op: 'reshaped', what: 'Tuesday route cluster — saved 312 mi', time: '11m ago' },
    { icon: 'shield',  color: '#34D399', who: 'KYCSentinel', op: 'cleared', what: '147 counterparties in overnight batch', time: '23m ago' },
    { icon: 'graph',   color: '#34D399', who: 'RiskModeler', op: 'updated', what: 'P&L attribution for FX book', time: '41m ago' },
    { icon: 'factory', color: '#00C9B8', who: 'LineTwin', op: 'predicted', what: '4h downtime on Line B — escalated', time: '1h ago' },
    { icon: 'beaker',  color: '#F0596A', who: 'RxCheck', op: 'detected', what: 'interaction warning (warfarin + azithromycin)', time: '1h ago' },
    { icon: 'nursing', color: '#00C9B8', who: 'ShiftBalancer', op: 'published', what: 'Week 48 rotation across 12 units', time: '2h ago' },
    { icon: 'wallet',  color: '#34D399', who: 'ReconAI', op: 'reconciled', what: '1,248 transactions; 3 variances flagged', time: '3h ago' },
    { icon: 'bolt',    color: '#F5B971', who: 'GridSense', op: 'forecast', what: 'peak demand +7% vs baseline Thursday', time: '4h ago' },
  ];

  // Quick launch tiles
  MOCK.tiles = [
    { id: 'chat', title: 'Chat', desc: 'Converse with Orchestra and route to any agent.', icon: 'chat', tint: 'rgba(110,110,245,0.18)', href: '#/chat' },
    { id: 'healthcare', title: 'Healthcare Suite', desc: 'Oncology, genomics, and clinic ops agents.', icon: 'medical', tint: 'rgba(240,89,106,0.18)', href: '#/agents?v=healthcare' },
    { id: 'legal', title: 'Legal Suite', desc: 'Contract review, compliance, and case briefing.', icon: 'gavel', tint: 'rgba(245,185,113,0.18)', href: '#/agents?v=legal' },
    { id: 'research', title: 'AutoResearch', desc: 'Multi-source synthesis with traceable citations.', icon: 'beaker', tint: 'rgba(0,201,184,0.18)', href: '#/tasks' },
    { id: 'redteam', title: 'Red Team', desc: 'Adversarial evaluation harness for prompts and agents.', icon: 'shield', tint: 'rgba(240,89,106,0.18)', href: '#/tasks' },
    { id: 'staffing', title: 'Staffing', desc: 'Acuity-based nursing rotations and coverage gap alerts.', icon: 'users', tint: 'rgba(110,110,245,0.18)', href: '#/agents?v=nursing' },
  ];

  // Favorites (right panel)
  MOCK.favorites = [
    { icon: 'chat', label: 'Orchestra chat', href: '#/chat' },
    { icon: 'medical', label: 'Oncology trial matching', href: '#/tasks' },
    { icon: 'file', label: 'NorthPeak MSA review', href: '#/tasks' },
    { icon: 'graph', label: 'Weekly KPI snapshot', href: '#/' },
    { icon: 'beaker', label: 'Variant pipeline run', href: '#/tasks' },
  ];

  // Running tasks (right panel + tasks page)
  MOCK.runningTasks = [
    {
      id: 'T-7041',
      title: 'Re-balance Tuesday route cluster',
      agent: 'RouteOptimizer',
      progress: 0.62,
      elapsed: '3m 14s',
      eta: '1m 20s',
      steps: [
        { text: 'Load stop manifest (218 stops)', status: 'done' },
        { text: 'Cross-check DOT hours', status: 'done' },
        { text: 'Solve VRP with time windows', status: 'working' },
        { text: 'Validate driver assignments', status: 'pending' },
        { text: 'Publish to dispatch queue', status: 'pending' },
      ],
      terminal: [
        { kind: 'cmd', text: 'orchestra run route-optimizer --cluster tuesday --drivers 18' },
        { kind: 'out', text: 'Loaded 218 stops across 6 zones' },
        { kind: 'out', text: 'Applied DOT 11h rule; 3 drivers near cap' },
        { kind: 'ok',  text: '✓ VRP solver initialized (OR-Tools)' },
        { kind: 'out', text: 'Search: 2s | best: 1,412mi | improved x6' },
        { kind: 'out', text: 'Search: 5s | best: 1,288mi | improved x11' },
      ],
    },
    {
      id: 'T-7042',
      title: 'Annotate variants for CG-882-A',
      agent: 'GenomIX',
      progress: 0.24,
      elapsed: '1m 02s',
      eta: '4m 10s',
      steps: [
        { text: 'Fetch BAM from cold storage', status: 'done' },
        { text: 'Call variants (DeepVariant)', status: 'working' },
        { text: 'Annotate with ClinVar + gnomAD', status: 'pending' },
        { text: 'Generate clinical report', status: 'pending' },
      ],
      terminal: [
        { kind: 'cmd', text: 'orchestra run genomix --sample CG-882-A' },
        { kind: 'out', text: 'BAM retrieved (22.4 GB) from s3://genomix-cold' },
        { kind: 'out', text: 'DeepVariant: chr1..7 complete' },
        { kind: 'out', text: 'DeepVariant: chr8..14 in progress' },
      ],
    },
    {
      id: 'T-7043',
      title: 'Review NorthPeak MSA rev 7',
      agent: 'ContractReview',
      progress: 0.88,
      elapsed: '4m 55s',
      eta: '20s',
      steps: [
        { text: 'Parse and section MSA', status: 'done' },
        { text: 'Diff against rev 6', status: 'done' },
        { text: 'Risk-score 42 clauses', status: 'done' },
        { text: 'Generate redlines', status: 'working' },
        { text: 'Render negotiation memo', status: 'pending' },
      ],
      terminal: [
        { kind: 'cmd', text: 'orchestra run contract-review --file northpeak-msa-r7.docx' },
        { kind: 'out', text: 'Parsed 42 clauses across 9 sections' },
        { kind: 'out', text: 'Detected 3 material changes vs rev 6' },
        { kind: 'ok',  text: '✓ Risk score: 64/100 (moderate)' },
      ],
    },
  ];

  MOCK.completedTasks = [
    { id: 'T-7028', title: 'Monthly bank reconciliation', agent: 'ReconAI', status: 'success', duration: '7m 18s', when: '2h ago' },
    { id: 'T-7027', title: 'Week 48 nursing rotation',    agent: 'ShiftBalancer', status: 'success', duration: '2m 06s', when: '3h ago' },
    { id: 'T-7026', title: 'Line B throughput forecast',   agent: 'LineTwin', status: 'success', duration: '5m 41s', when: '4h ago' },
    { id: 'T-7025', title: 'KYC batch screening',          agent: 'KYCSentinel', status: 'success', duration: '12m 09s', when: '5h ago' },
    { id: 'T-7024', title: 'MSA redline draft',            agent: 'ContractReview', status: 'failed',  duration: '1m 03s', when: '6h ago' },
    { id: 'T-7023', title: 'Variant annotation batch',     agent: 'GenomIX', status: 'success', duration: '18m 47s', when: '7h ago' },
  ];

  // MILES suggestions (right panel)
  MOCK.milesSuggestions = [
    { title: 'Re-run failed MSA redline', body: 'T-7024 failed at parse step. A schema fix is available — retry now?' },
    { title: 'Consolidate 3 similar trials', body: 'OncoNavigator found 3 trials matching cohort 2041 with overlapping criteria.' },
    { title: 'Export weekly KPI pack', body: 'Your Friday KPI report is due in 4 hours. One-click generate.' },
  ];

  // Chat messages (preloaded conversation)
  MOCK.messages = [
    {
      role: 'user',
      text: 'Build me an Orchestra middleware that rate-limits agent calls per tenant. Use token-bucket with Redis. Give me the TypeScript implementation and tests.',
      time: '10:42 AM',
    },
    {
      role: 'assistant',
      time: '10:42 AM',
      blocks: [
        { type: 'md', content: `I'll build a **token-bucket rate limiter** for per-tenant agent calls, backed by Redis and wrapped as an Orchestra middleware. Plan:\n\n1. Sketch the contract (\`RateLimitOptions\`, \`RateLimitResult\`)\n2. Implement the Lua script for atomic bucket refill + consume\n3. Wire the Orchestra middleware\n4. Add Jest tests covering burst, refill, and per-tenant isolation` },
        { type: 'tool-calls', calls: [
          { icon: 'file', label: 'Reading src/middleware/index.ts', state: 'done' },
          { icon: 'terminal', label: 'Initializing TypeScript project', state: 'done' },
          { icon: 'folder', label: 'Scaffolding src/rateLimiter/', state: 'done' },
        ]},
        { type: 'code', lang: 'typescript', title: 'src/rateLimiter/tokenBucket.ts',
          code:
`import type { Redis } from 'ioredis';

export interface RateLimitOptions {
  capacity: number;        // max tokens in the bucket
  refillPerSec: number;    // tokens added per second
  keyPrefix?: string;
}

export interface RateLimitResult {
  allowed: boolean;
  remaining: number;
  retryAfterMs: number;
}

// Atomic refill + consume in a single round-trip.
const SCRIPT = \`
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local bucket = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(bucket[1]) or cap
local ts = tonumber(bucket[2]) or now
local delta = math.max(0, now - ts) / 1000
tokens = math.min(cap, tokens + delta * rate)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil((cap / rate) * 1000) + 1000)
return { allowed, tokens, cost }
\`;

export function createTokenBucket(redis: Redis, opts: RateLimitOptions) {
  const prefix = opts.keyPrefix ?? 'orch:rl';
  return async function consume(tenantId: string, cost = 1): Promise<RateLimitResult> {
    const [allowed, remaining] = (await redis.eval(
      SCRIPT, 1, \`\${prefix}:\${tenantId}\`,
      opts.capacity, opts.refillPerSec, Date.now(), cost
    )) as [number, number, number];
    const retryAfterMs = allowed
      ? 0
      : Math.ceil(((cost - remaining) / opts.refillPerSec) * 1000);
    return { allowed: allowed === 1, remaining, retryAfterMs };
  };
}`,
        },
        { type: 'md', content: `Now the middleware that slots into Orchestra's agent invocation chain:` },
        { type: 'code', lang: 'typescript', title: 'src/rateLimiter/middleware.ts',
          code:
`import type { OrchestraMiddleware, AgentContext } from '@orchestra/core';
import { createTokenBucket, RateLimitOptions } from './tokenBucket';
import type { Redis } from 'ioredis';

export function rateLimitMiddleware(
  redis: Redis,
  opts: RateLimitOptions
): OrchestraMiddleware {
  const consume = createTokenBucket(redis, opts);
  return async (ctx: AgentContext, next) => {
    const tenant = ctx.tenant?.id ?? 'anonymous';
    const r = await consume(tenant, 1);
    if (!r.allowed) {
      ctx.respond({
        status: 429,
        headers: { 'Retry-After': String(Math.ceil(r.retryAfterMs / 1000)) },
        body: { error: 'rate_limited', retryAfterMs: r.retryAfterMs },
      });
      return;
    }
    ctx.metrics.set('ratelimit.remaining', r.remaining);
    await next();
  };
}`,
        },
        { type: 'md', content: `And a focused test suite that exercises burst and refill semantics:` },
        { type: 'code', lang: 'typescript', title: 'src/rateLimiter/tokenBucket.test.ts',
          code:
`import { createTokenBucket } from './tokenBucket';
import Redis from 'ioredis-mock';

describe('token bucket', () => {
  const redis = new Redis();
  const consume = createTokenBucket(redis as any, {
    capacity: 5, refillPerSec: 1,
  });

  afterEach(() => redis.flushall());

  it('allows the first N calls up to capacity', async () => {
    for (let i = 0; i < 5; i++) {
      const r = await consume('tenant-a');
      expect(r.allowed).toBe(true);
    }
    const blocked = await consume('tenant-a');
    expect(blocked.allowed).toBe(false);
    expect(blocked.retryAfterMs).toBeGreaterThan(0);
  });

  it('refills tokens over time', async () => {
    for (let i = 0; i < 5; i++) await consume('tenant-b');
    await new Promise(r => setTimeout(r, 1100));
    const r = await consume('tenant-b');
    expect(r.allowed).toBe(true);
  });

  it('isolates tenants', async () => {
    for (let i = 0; i < 5; i++) await consume('tenant-c');
    const other = await consume('tenant-d');
    expect(other.allowed).toBe(true);
  });
});`,
        },
        { type: 'md', content: `### What this gets you\n\n- **Atomic**: refill + consume in a single Lua call, so concurrent workers cannot double-spend.\n- **Tenant-scoped**: key prefix isolates every tenant's bucket.\n- **Backpressure signal**: \`Retry-After\` header lets clients queue gracefully.\n\n> Want me to add sliding-window fairness or a circuit-breaker fallback when Redis is unreachable?` },
      ],
    },
    {
      role: 'user',
      text: 'Add a circuit-breaker fallback for Redis outages — fail open with local in-memory limiter.',
      time: '10:48 AM',
    },
    {
      role: 'assistant',
      time: '10:48 AM',
      running: true,            // animated "running" message
      blocks: [
        { type: 'thinking', text: 'Drafting circuit breaker with half-open probe' },
        { type: 'checklist', title: 'Plan', items: [
          { text: 'Add CircuitBreaker with open/half/closed states', status: 'done' },
          { text: 'Build in-memory token bucket as fallback', status: 'done' },
          { type: 'default', text: 'Wire breaker into middleware', status: 'working' },
          { text: 'Write tests for outage + recovery', status: 'pending' },
          { text: 'Instrument metrics and log events', status: 'pending' },
        ]},
        { type: 'tool-calls', calls: [
          { icon: 'globe', label: 'Searching web: "circuit breaker half-open pattern"', state: 'done' },
          { icon: 'file', label: 'Editing src/rateLimiter/middleware.ts', state: 'working' },
        ]},
        { type: 'diff', path: 'src/rateLimiter/middleware.ts',
          adds: 14, rems: 3,
          lines: [
            { kind: 'ctx', n: 3, text: `import { createTokenBucket, RateLimitOptions } from './tokenBucket';` },
            { kind: 'add', n: 4, text: `import { CircuitBreaker } from './breaker';` },
            { kind: 'add', n: 5, text: `import { createLocalBucket } from './localBucket';` },
            { kind: 'ctx', n: 6, text: `import type { Redis } from 'ioredis';` },
            { kind: 'ctx', n: 7, text: `` },
            { kind: 'ctx', n: 8, text: `export function rateLimitMiddleware(` },
            { kind: 'ctx', n: 9, text: `  redis: Redis,` },
            { kind: 'ctx', n: 10, text: `  opts: RateLimitOptions` },
            { kind: 'ctx', n: 11, text: `): OrchestraMiddleware {` },
            { kind: 'rem', n: 12, text: `  const consume = createTokenBucket(redis, opts);` },
            { kind: 'add', n: 12, text: `  const remote = createTokenBucket(redis, opts);` },
            { kind: 'add', n: 13, text: `  const local  = createLocalBucket(opts);` },
            { kind: 'add', n: 14, text: `  const breaker = new CircuitBreaker({ failureThreshold: 5, cooldownMs: 2000 });` },
            { kind: 'ctx', n: 15, text: `  return async (ctx, next) => {` },
            { kind: 'rem', n: 16, text: `    const r = await consume(ctx.tenant.id, 1);` },
            { kind: 'add', n: 16, text: `    const r = await breaker.exec(` },
            { kind: 'add', n: 17, text: `      () => remote(ctx.tenant.id, 1),` },
            { kind: 'add', n: 18, text: `      () => local(ctx.tenant.id, 1), // fail-open fallback` },
            { kind: 'add', n: 19, text: `    );` },
          ],
        },
        { type: 'terminal', title: 'orchestra test',
          lines: [
            { kind: 'cmd', text: 'pnpm test -- rateLimiter' },
            { kind: 'out', text: 'PASS  src/rateLimiter/tokenBucket.test.ts' },
            { kind: 'out', text: 'PASS  src/rateLimiter/breaker.test.ts' },
            { kind: 'ok',  text: 'Tests: 14 passed, 14 total' },
            { kind: 'ok',  text: 'Time:  2.41s' },
          ],
        },
      ],
    },
  ];

  // Chat suggested prompts for empty state
  MOCK.chatPrompts = [
    { title: 'Draft an incident report', sub: 'Pull the last 24h of PagerDuty and summarize impact.' },
    { title: 'Reconcile yesterday\'s ledger', sub: 'Run ReconAI on the 11/18 ledger and flag variances.' },
    { title: 'Summarize NorthPeak MSA', sub: 'Highlight indemnification and SLA changes vs rev 6.' },
    { title: 'Forecast Tuesday demand', sub: 'Use GridSense with NOAA overlay and 7-day window.' },
  ];

  // Models
  MOCK.models = [
    { id: 'kimi-25', name: 'Kimi K2.5',  desc: 'Long-context reasoning, 1M tokens',    selected: true },
    { id: 'claude-opus', name: 'Claude Opus 4',  desc: 'Best for agentic coding' },
    { id: 'gpt-54', name: 'GPT-5.4',     desc: 'General purpose, fast' },
    { id: 'gemma-4', name: 'Gemma 4 Pro', desc: 'Open weights, local fallback' },
  ];

  // Integrations (settings page)
  MOCK.integrations = [
    { name: 'GitHub', icon: 'github', status: 'Connected · orchestra-ai', connected: true },
    { name: 'Gmail',  icon: 'mail',   status: 'Connected · ashton@orchestra.ai', connected: true },
    { name: 'Calendar', icon: 'calendar', status: 'Connected', connected: true },
    { name: 'Slack',  icon: 'slack',  status: 'Connected · #orchestra-ops', connected: true },
    { name: 'Notion', icon: 'notion', status: 'Not connected', connected: false },
    { name: 'Figma',  icon: 'figma',  status: 'Not connected', connected: false },
  ];

  // Audit ledger preview
  MOCK.audit = [
    { t: '10:48:22', who: 'agent:ContractReview', what: 'opened northpeak-msa-r7.docx',   level: 'info' },
    { t: '10:48:11', who: 'agent:RouteOptimizer', what: 'published 218-stop plan',         level: 'info' },
    { t: '10:47:58', who: 'user:ashton',         what: 'approved PR #2041',                level: 'info' },
    { t: '10:47:22', who: 'agent:KYCSentinel',   what: 'flagged counterparty GR-884 (PEP)', level: 'warn' },
    { t: '10:46:40', who: 'system',              what: 'Redis primary failover (2s)',      level: 'warn' },
    { t: '10:45:02', who: 'agent:GenomIX',       what: 'denied retry — quota exceeded',    level: 'err' },
  ];

  window.MOCK = MOCK;
})();
