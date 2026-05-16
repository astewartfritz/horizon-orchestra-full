/**
 * Orchestra Finance — TypeScript Orchestration Layer
 *
 * Routes AI calls, manages formula evaluation, and bridges the Python
 * finance engine to the web dashboard.
 *
 * Architecture:
 *   Web UI  ←→  TS Orchestrator (REST + WS)  ←→  Python Finance Engine
 *                                               ←→  Event Bus (Kafka/Pulsar)
 */

import express from 'express';
import { EventEmitter } from 'events';

// ── Types ─────────────────────────────────────

interface FinanceConfig {
  pythonApiUrl: string;
  kafkaBrokers?: string[];
  wsEnabled: boolean;
  cacheTTL: number;
}

interface FormulaRequest {
  formula: string;
  cellRef?: string;
  sheetData?: Record<string, any>;
}

interface TransactionRequest {
  date: string;
  description: string;
  entries: Array<{ accountId: string; amount: number; direction: 'debit' | 'credit' }>;
  tags?: string[];
}

interface AIQueryRequest {
  prompt: string;
  context?: Record<string, any>;
}

// ── Finance Orchestrator ──────────────────────

export class FinanceOrchestrator {
  private app: express.Application;
  private eventBus: EventEmitter;
  private config: FinanceConfig;
  private cache: Map<string, { data: any; expiry: number }>;

  constructor(config: Partial<FinanceConfig> = {}) {
    this.config = {
      pythonApiUrl: config.pythonApiUrl || 'http://127.0.0.1:8000',
      wsEnabled: config.wsEnabled ?? true,
      cacheTTL: config.cacheTTL ?? 300,
    };
    this.app = express();
    this.eventBus = new EventEmitter();
    this.cache = new Map();
    this.setupRoutes();
    this.setupEventHandlers();
  }

  // ── Routes ───────────────────────────────────

  private setupRoutes(): void {
    this.app.use(express.json());

    // Health
    this.app.get('/finance/health', (_req, res) => {
      res.json({ status: 'ok', service: 'finance-orchestrator', cacheSize: this.cache.size });
    });

    // Formula evaluation
    this.app.post('/finance/formula/evaluate', async (req, res) => {
      try {
        const body: FormulaRequest = req.body;
        const result = await this.evaluateFormula(body);
        res.json(result);
      } catch (err: any) {
        res.status(400).json({ error: err.message });
      }
    });

    // Bulk formula evaluation (for recalculation)
    this.app.post('/finance/formula/bulk', async (req, res) => {
      try {
        const formulas: FormulaRequest[] = req.body.formulas || [];
        const results = await Promise.all(formulas.map(f => this.evaluateFormula(f)));
        res.json({ results, count: results.length });
      } catch (err: any) {
        res.status(400).json({ error: err.message });
      }
    });

    // Transaction recording
    this.app.post('/finance/transactions', async (req, res) => {
      try {
        const body: TransactionRequest = req.body;
        const result = await this.recordTransaction(body);
        res.status(201).json(result);
      } catch (err: any) {
        res.status(400).json({ error: err.message });
      }
    });

    // Transaction query
    this.app.get('/finance/transactions', async (req, res) => {
      const accountId = req.query.accountId as string;
      const dateFrom = req.query.dateFrom as string;
      const dateTo = req.query.dateTo as string;
      const result = await this.queryTransactions(accountId, dateFrom, dateTo);
      res.json(result);
    });

    // AI query (CFO copilot)
    this.app.post('/finance/ai/query', async (req, res) => {
      try {
        const body: AIQueryRequest = req.body;
        const result = await this.aiQuery(body.prompt, body.context);
        res.json(result);
      } catch (err: any) {
        res.status(400).json({ error: err.message });
      }
    });

    // Financial statements
    this.app.get('/finance/statements', async (_req, res) => {
      const result = await this.getStatements();
      res.json(result);
    });

    // Insights
    this.app.get('/finance/insights', async (_req, res) => {
      const result = await this.getInsights();
      res.json(result);
    });

    // Event bus stats
    this.app.get('/finance/events/stats', (_req, res) => {
      res.json({
        eventCount: this.eventBus.eventNames().length,
        listeners: this.eventBus.listenerCount('*'),
      });
    });
  }

  // ── Core Methods ─────────────────────────────

  private async evaluateFormula(req: FormulaRequest): Promise<any> {
    const cacheKey = `formula:${req.formula}`;
    const cached = this.cache.get(cacheKey);
    if (cached && cached.expiry > Date.now()) return cached.data;

    // Forward to Python engine
    try {
      const response = await fetch(`${this.config.pythonApiUrl}/api/finance/formula`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          formula: req.formula,
          cell_ref: req.cellRef,
          sheet_data: req.sheetData,
        }),
      });
      const data = await response.json();
      this.cache.set(cacheKey, { data, expiry: Date.now() + this.config.cacheTTL * 1000 });
      this.eventBus.emit('formula:evaluated', { formula: req.formula, result: data });
      return data;
    } catch (err) {
      // Fallback: client-side formula evaluation
      return this.evaluateLocally(req.formula, req.sheetData);
    }
  }

  private evaluateLocally(formula: string, data?: Record<string, any>): any {
    // Simple client-side fallback for basic formulas
    if (formula.startsWith('=SUM')) {
      const match = formula.match(/=SUM\(([^)]+)\)/);
      if (match) {
        const range = match[1];
        const vals = this.resolveRange(range, data);
        return vals.reduce((a: number, b: number) => a + b, 0);
      }
    }
    if (formula.startsWith('=AVG')) {
      const match = formula.match(/=AVG\(([^)]+)\)/);
      if (match) {
        const vals = this.resolveRange(match[1], data);
        return vals.length ? vals.reduce((a: number, b: number) => a + b, 0) / vals.length : 0;
      }
    }
    return { result: '#N/A', note: 'Evaluated locally (Python engine unavailable)' };
  }

  private resolveRange(range: string, data?: Record<string, any>): number[] {
    // Parse "A1:B5" style ranges
    const match = range.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/);
    if (!match || !data) return [];

    const col = (c: string) => c.charCodeAt(0) - 65;
    const c1 = col(match[1]), r1 = parseInt(match[2]) - 1;
    const c2 = col(match[3]), r2 = parseInt(match[4]) - 1;
    const vals: number[] = [];

    for (let r = r1; r <= r2; r++) {
      for (let c = c1; c <= c2; c++) {
        const ref = String.fromCharCode(65 + c) + (r + 1);
        const raw = data[ref] ?? data[ref.toLowerCase()];
        const num = parseFloat(raw);
        if (!isNaN(num)) vals.push(num);
      }
    }
    return vals;
  }

  private async recordTransaction(tx: TransactionRequest): Promise<any> {
    try {
      const response = await fetch(`${this.config.pythonApiUrl}/api/finance/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(tx),
      });
      const data = await response.json();
      this.eventBus.emit('transaction:recorded', tx);
      this.cache.clear();
      return data;
    } catch (err: any) {
      throw new Error(`Transaction failed: ${err.message}`);
    }
  }

  private async queryTransactions(
    accountId?: string, dateFrom?: string, dateTo?: string,
  ): Promise<any> {
    const params = new URLSearchParams();
    if (accountId) params.set('accountId', accountId);
    if (dateFrom) params.set('dateFrom', dateFrom);
    if (dateTo) params.set('dateTo', dateTo);
    const query = params.toString();

    try {
      const response = await fetch(
        `${this.config.pythonApiUrl}/api/finance/transactions${query ? '?' + query : ''}`,
      );
      return await response.json();
    } catch {
      return { error: 'Backend unavailable' };
    }
  }

  private async aiQuery(prompt: string, context?: Record<string, any>): Promise<any> {
    try {
      const response = await fetch(`${this.config.pythonApiUrl}/api/finance/ai/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, context }),
      });
      return await response.json();
    } catch {
      return { error: 'AI backend unavailable', fallback: true };
    }
  }

  private async getStatements(): Promise<any> {
    try {
      const response = await fetch(`${this.config.pythonApiUrl}/api/finance/statements`);
      return await response.json();
    } catch {
      return { error: 'Backend unavailable' };
    }
  }

  private async getInsights(): Promise<any> {
    try {
      const response = await fetch(`${this.config.pythonApiUrl}/api/finance/insights`);
      return await response.json();
    } catch {
      return { error: 'Backend unavailable' };
    }
  }

  // ── Event Handlers ───────────────────────────

  private setupEventHandlers(): void {
    this.eventBus.on('transaction:recorded', (tx: TransactionRequest) => {
      // Invalidate caches, trigger analytics, push to WebSocket
      this.cache.clear();
    });

    this.eventBus.on('formula:evaluated', ({ formula }: { formula: string }) => {
      // Log formula usage for analytics
    });

    this.eventBus.on('*', (event: string, data: any) => {
      // Global event log
    });
  }

  // ── Public API ───────────────────────────────

  getApp(): express.Application {
    return this.app;
  }

  getEventBus(): EventEmitter {
    return this.eventBus;
  }
}

// ── Exports ────────────────────────────────────

export function createFinanceRouter(config?: Partial<FinanceConfig>): express.Router {
  const orchestrator = new FinanceOrchestrator(config);
  return orchestrator.getApp();
}

export default FinanceOrchestrator;
