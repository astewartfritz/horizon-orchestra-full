using Microsoft.AspNetCore.Mvc;
using OrchestraApi.Models;

namespace OrchestraApi.Controllers;

[ApiController]
[Route("indexes")]
public class IndexesController : ControllerBase
{
    private readonly InMemoryIndexStore _store;
    public IndexesController(InMemoryIndexStore store) => _store = store;

    [HttpPost]
    public IActionResult Create([FromBody] IndexSchema schema)
    {
        var traceId = GetTraceId();
        if (string.IsNullOrEmpty(schema.Name))
            return BadRequest(new { error = "Index name required", trace_id = traceId });
        if (schema.Fields.Count(f => f.Key) != 1)
            return BadRequest(new { error = "Exactly one key field required", trace_id = traceId });

        _store.Indexes[schema.Name] = schema;
        return CreatedAtAction(nameof(Get), new { indexName = schema.Name }, new { schema, trace_id = traceId });
    }

    [HttpGet]
    public IActionResult List()
    {
        var list = _store.Indexes.Select(kv => new
        {
            kv.Value.Name,
            Fields = kv.Value.Fields.Select(f => new { f.Name, f.Type, f.Key, f.Searchable }),
            DocumentCount = _store.Documents.GetOrAdd(kv.Key, _ => new()).Count,
        }).ToList();
        return Ok(new { indexes = list, count = list.Count, trace_id = GetTraceId() });
    }

    [HttpGet("{indexName}")]
    public IActionResult Get(string indexName)
    {
        if (!_store.Indexes.TryGetValue(indexName, out var schema))
            return NotFound(new { error = "Index not found", trace_id = GetTraceId() });
        return Ok(new { schema, trace_id = GetTraceId() });
    }

    [HttpDelete("{indexName}")]
    public IActionResult Delete(string indexName)
    {
        if (!_store.Indexes.TryRemove(indexName, out _))
            return NotFound(new { error = "Index not found", trace_id = GetTraceId() });
        return Ok(new { deleted = true, index = indexName, trace_id = GetTraceId() });
    }

    private string GetTraceId() =>
        HttpContext.Request.Headers["x-trace-id"].FirstOrDefault() ?? Guid.NewGuid().ToString("N")[..12];
}
