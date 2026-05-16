const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const { v4: uuidv4 } = require('uuid');

const searchRoutes = require('./routes/search');
const indexRoutes = require('./routes/indexes');
const accountRoutes = require('./routes/accounts');
const { tracingMiddleware } = require('./middleware/tracing');

const app = express();
const PORT = process.env.ORCHESTRA_API_PORT || 4000;

app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(morgan(':method :url :status :response-time ms - trace::req[x-trace-id]'));
app.use(tracingMiddleware);

app.use('/search', searchRoutes);
app.use('/indexes', indexRoutes);
app.use('/accounts', accountRoutes);

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'orchestra-api', version: '1.0.0', trace_id: req.traceId });
});

app.get('/schemas/:indexName', (req, res) => {
  const { indexName } = req.params;
  const schema = loadSchema(indexName);
  if (!schema) return res.status(404).json({ error: 'Schema not found', trace_id: req.traceId });
  res.json({ schema, trace_id: req.traceId });
});

// Action schema exposure — agents parse this to invoke endpoints dynamically
app.get('/actions', (req, res) => {
  const actions = [
    {
      name: 'searchQuery',
      method: 'POST',
      path: '/search/indexes/{indexName}/query',
      description: 'Query a search index with conversation history',
      parameters: {
        indexName: { type: 'string', required: true, description: 'Index to search' },
        query: { type: 'string', required: true, description: 'Search query text' },
        filter: { type: 'string', required: false, description: 'OData filter expression' },
        top: { type: 'integer', required: false, description: 'Max results', default: 10 },
        facets: { type: 'array', required: false, description: 'Facet fields' },
        conversation_history: { type: 'array', required: false, description: 'Previous turns for context' },
      }
    },
    {
      name: 'getAccount',
      method: 'GET',
      path: '/accounts/{id}',
      description: 'Retrieve account data for RAG-grounded responses',
      parameters: {
        id: { type: 'string', required: true, description: 'Account identifier' },
      }
    },
    {
      name: 'createIndex',
      method: 'POST',
      path: '/indexes',
      description: 'Create a new search index with schema',
      parameters: {
        name: { type: 'string', required: true, description: 'Index name' },
        fields: { type: 'array', required: true, description: 'Field definitions' },
      }
    },
    {
      name: 'listIndexes',
      method: 'GET',
      path: '/indexes',
      description: 'List all available search indexes',
      parameters: {}
    },
    {
      name: 'getSchema',
      method: 'GET',
      path: '/schemas/{indexName}',
      description: 'Get schema for a specific index',
      parameters: {
        indexName: { type: 'string', required: true, description: 'Index name' },
      }
    },
  ];
  res.json({ actions, trace_id: req.traceId });
});

function loadSchema(indexName) {
  try {
    return require(`./schemas/${indexName}.json`);
  } catch (e) {
    return null;
  }
}

app.listen(PORT, () => {
  console.log(`[Orchestra API] running on http://0.0.0.0:${PORT}`);
  console.log(`[Orchestra API] Actions: http://localhost:${PORT}/actions`);
  console.log(`[Orchestra API] Health:   http://localhost:${PORT}/health`);
});
