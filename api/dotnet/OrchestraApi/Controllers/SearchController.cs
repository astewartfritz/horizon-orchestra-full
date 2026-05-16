using Microsoft.AspNetCore.Mvc;
using OrchestraApi.Models;

namespace OrchestraApi.Controllers;

[ApiController]
[Route("search")]
public class SearchController : ControllerBase
{
    private readonly InMemoryIndexStore _store;

    public SearchController(InMemoryIndexStore store) => _store = store;

    [HttpPost("indexes/{indexName}/query")]
    public IActionResult Query(string indexName, [FromBody] SearchRequest req)
    {
        var traceId = GetTraceId();
        if (!_store.Indexes.TryGetValue(indexName, out var index))
            return NotFound(new { error = $"Index '{indexName}' not found", trace_id = traceId });

        var docs = _store.Documents.GetOrAdd(indexName, _ => new());
        var results = docs.AsEnumerable();

        if (!string.IsNullOrEmpty(req.Query))
        {
            var q = req.Query.ToLower();
            var searchable = index.Fields.Where(f => f.Searchable).Select(f => f.Name).ToHashSet();
            results = results.Where(d => searchable.Any(f =>
                d.TryGetValue(f, out var val) && val?.ToString()?.ToLower().Contains(q) == true));
        }

        if (!string.IsNullOrEmpty(req.Filter))
            results = ApplyFilter(results, req.Filter);

        var list = results.Take(req.Top).ToList();
        var count = results.Count();

        return Ok(new SearchResponse
        {
            IndexName = indexName,
            Query = req.Query,
            Count = count,
            Results = list,
            TraceId = traceId,
        });
    }

    private IEnumerable<Dictionary<string, object>> ApplyFilter(IEnumerable<Dictionary<string, object>> docs, string filter)
    {
        var eqMatch = System.Text.RegularExpressions.Regex.Match(filter, @"(\w+)\s+eq\s+'([^']+)'");
        if (eqMatch.Success)
            return docs.Where(d => d.GetValueOrDefault(eqMatch.Groups[1].Value)?.ToString() == eqMatch.Groups[2].Value);
        return docs;
    }

    private string GetTraceId() =>
        HttpContext.Request.Headers["x-trace-id"].FirstOrDefault() ?? Guid.NewGuid().ToString("N")[..12];
}
