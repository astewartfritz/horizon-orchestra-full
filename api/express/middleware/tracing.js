const { v4: uuidv4 } = require('uuid');

function tracingMiddleware(req, res, next) {
  const traceId = req.headers['x-trace-id'] || uuidv4();
  req.traceId = traceId;
  res.setHeader('x-trace-id', traceId);
  next();
}

module.exports = { tracingMiddleware };
