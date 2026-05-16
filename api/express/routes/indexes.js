const express = require('express');
const router = express.Router();

// In-memory index store (shared with search routes via require cache)
const INDEXES = {};

// POST /indexes — create a new index with schema
router.post('/', (req, res) => {
  const { name, fields } = req.body;
  if (!name) return res.status(400).json({ error: 'Index name required', trace_id: req.traceId });
  if (!fields || !Array.isArray(fields) || fields.length === 0) {
    return res.status(400).json({ error: 'At least one field required', trace_id: req.traceId });
  }

  const keyFields = fields.filter(f => f.key);
  if (keyFields.length !== 1) {
    return res.status(400).json({ error: 'Exactly one key field required', trace_id: req.traceId });
  }

  const schema = { name, fields };
  INDEXES[name] = schema;

  // Persist to schemas directory for agent discovery
  const fs = require('fs');
  const path = require('path');
  const schemaPath = path.join(__dirname, '..', 'schemas', `${name}.json`);
  try { fs.writeFileSync(schemaPath, JSON.stringify(schema, null, 2)); } catch (e) {}

  res.status(201).json({ schema, trace_id: req.traceId });
});

// GET /indexes — list all indexes
router.get('/', (req, res) => {
  const list = Object.entries(INDEXES).map(([name, schema]) => ({
    name,
    fields: schema.fields.map(f => ({ name: f.name, type: f.type, key: f.key || false, searchable: f.searchable || false })),
    document_count: 0,
  }));
  res.json({ indexes: list, count: list.length, trace_id: req.traceId });
});

// GET /indexes/{indexName} — get index details
router.get('/:indexName', (req, res) => {
  const { indexName } = req.params;
  const schema = INDEXES[indexName];
  if (!schema) return res.status(404).json({ error: 'Index not found', trace_id: req.traceId });
  res.json({ schema, trace_id: req.traceId });
});

// DELETE /indexes/{indexName} — delete an index
router.delete('/:indexName', (req, res) => {
  const { indexName } = req.params;
  if (!INDEXES[indexName]) return res.status(404).json({ error: 'Index not found', trace_id: req.traceId });
  delete INDEXES[indexName];
  res.json({ deleted: true, index: indexName, trace_id: req.traceId });
});

module.exports = router;
