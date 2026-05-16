const express = require('express');
const router = express.Router();

// In-memory index storage (replace with DB in production)
const indexes = {};
const documents = {};

// POST /search/indexes/{indexName}/query — main search endpoint
router.post('/indexes/:indexName/query', (req, res) => {
  const { indexName } = req.params;
  const { query, filter, top = 10, facets, conversation_history } = req.body;
  const traceId = req.traceId;

  const index = indexes[indexName];
  if (!index) return res.status(404).json({ error: `Index '${indexName}' not found`, trace_id: traceId });

  const docs = documents[indexName] || [];
  let results = [...docs];

  // Full-text search across searchable fields
  if (query) {
    const q = query.toLowerCase();
    const searchableFields = index.fields.filter(f => f.searchable).map(f => f.name);
    results = results.filter(doc =>
      searchableFields.some(field => {
        const val = doc[field];
        return val && String(val).toLowerCase().includes(q);
      })
    );
  }

  // OData-style filter parsing (simplified)
  if (filter) {
    try {
      results = applyFilter(results, filter);
    } catch (e) {
      return res.status(400).json({ error: `Invalid filter: ${e.message}`, trace_id: traceId });
    }
  }

  const totalCount = results.length;
  const topResults = results.slice(0, top);

  // Facet counts
  let facetResults = {};
  if (facets && Array.isArray(facets)) {
    facets.forEach(facetField => {
      const counts = {};
      docs.forEach(doc => {
        const val = doc[facetField];
        if (val !== undefined) {
          const key = String(val);
          counts[key] = (counts[key] || 0) + 1;
        }
      });
      facetResults[facetField] = Object.entries(counts).map(([value, count]) => ({ value, count }));
    });
  }

  res.json({
    indexName,
    query,
    count: totalCount,
    results: topResults,
    facets: facetResults,
    trace_id: traceId,
    conversation_history: conversation_history || [],
  });
});

// GET /search/indexes/{indexName}/documents/{id}
router.get('/indexes/:indexName/documents/:id', (req, res) => {
  const { indexName, id } = req.params;
  const docs = documents[indexName] || [];
  const doc = docs.find(d => d.id === id || d[getKeyField(indexName)] === id);
  if (!doc) return res.status(404).json({ error: 'Document not found', trace_id: req.traceId });
  res.json({ document: doc, trace_id: req.traceId });
});

// POST /search/indexes/{indexName}/documents — bulk index documents
router.post('/indexes/:indexName/documents', (req, res) => {
  const { indexName } = req.params;
  const { documents: newDocs } = req.body;
  if (!Array.isArray(newDocs)) return res.status(400).json({ error: 'documents must be an array' });

  if (!documents[indexName]) documents[indexName] = [];
  newDocs.forEach(doc => {
    const existingIdx = documents[indexName].findIndex(d =>
      d.id === doc.id || d[getKeyField(indexName)] === doc[getKeyField(indexName)]
    );
    if (existingIdx >= 0) {
      documents[indexName][existingIdx] = { ...documents[indexName][existingIdx], ...doc };
    } else {
      documents[indexName].push(doc);
    }
  });

  res.json({ indexed: newDocs.length, trace_id: req.traceId });
});

function applyFilter(docs, filter) {
  // Simple OData-like filter parser: field eq 'value' or field gt 5
  const eqMatch = filter.match(/(\w+)\s+eq\s+'([^']+)'/);
  if (eqMatch) return docs.filter(d => String(d[eqMatch[1]]) === eqMatch[2]);

  const gtMatch = filter.match(/(\w+)\s+gt\s+(\d+)/);
  if (gtMatch) return docs.filter(d => Number(d[gtMatch[1]]) > Number(gtMatch[2]));

  const ltMatch = filter.match(/(\w+)\s+lt\s+(\d+)/);
  if (ltMatch) return docs.filter(d => Number(d[ltMatch[1]]) < Number(ltMatch[2]));

  const containsMatch = filter.match(/contains\((\w+),\s*'([^']+)'\)/);
  if (containsMatch) return docs.filter(d => String(d[containsMatch[1]]).includes(containsMatch[2]));

  return docs;
}

function getKeyField(indexName) {
  const index = indexes[indexName];
  if (!index) return 'id';
  const keyField = index.fields.find(f => f.key);
  return keyField ? keyField.name : 'id';
}

module.exports = router;
