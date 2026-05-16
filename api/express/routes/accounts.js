const express = require('express');
const router = express.Router();

// In-memory account store
const ACCOUNTS = {
  'acc-001': { id: 'acc-001', name: 'Acme Corp', plan: 'enterprise', status: 'active', balance: 12500, created: '2024-01-15' },
  'acc-002': { id: 'acc-002', name: 'Globex Inc', plan: 'pro', status: 'active', balance: 3400, created: '2024-03-22' },
  'acc-003': { id: 'acc-003', name: 'Initech', plan: 'basic', status: 'suspended', balance: 0, created: '2023-11-01' },
};

// GET /accounts/{id} — retrieve account for RAG-grounded responses
router.get('/:id', (req, res) => {
  const { id } = req.params;
  const account = ACCOUNTS[id];
  if (!account) return res.status(404).json({ error: 'Account not found', trace_id: req.traceId });
  res.json({ account, trace_id: req.traceId });
});

// GET /accounts — list all accounts
router.get('/', (req, res) => {
  const list = Object.values(ACCOUNTS);
  res.json({ accounts: list, count: list.length, trace_id: req.traceId });
});

// POST /accounts — create account
router.post('/', (req, res) => {
  const { id, name, plan = 'basic' } = req.body;
  if (!id || !name) return res.status(400).json({ error: 'id and name required', trace_id: req.traceId });
  ACCOUNTS[id] = { id, name, plan, status: 'active', balance: 0, created: new Date().toISOString().split('T')[0] };
  res.status(201).json({ account: ACCOUNTS[id], trace_id: req.traceId });
});

// Action schema for agents: POST /customer/{id}/orders
router.post('/:id/orders', (req, res) => {
  const { id } = req.params;
  const { items, total } = req.body;
  const account = ACCOUNTS[id];
  if (!account) return res.status(404).json({ error: 'Account not found', trace_id: req.traceId });

  const order = {
    order_id: `ORD-${Date.now()}`,
    account_id: id,
    items: items || [],
    total: total || 0,
    status: 'confirmed',
    created: new Date().toISOString(),
  };
  res.status(201).json({ order, trace_id: req.traceId });
});

module.exports = router;
