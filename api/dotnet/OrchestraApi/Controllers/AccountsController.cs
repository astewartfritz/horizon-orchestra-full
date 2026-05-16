using Microsoft.AspNetCore.Mvc;
using OrchestraApi.Models;

namespace OrchestraApi.Controllers;

[ApiController]
[Route("accounts")]
public class AccountsController : ControllerBase
{
    private readonly InMemoryAccountStore _store;
    public AccountsController(InMemoryAccountStore store) => _store = store;

    [HttpGet("{id}")]
    public IActionResult Get(string id)
    {
        if (!_store.Accounts.TryGetValue(id, out var account))
            return NotFound(new { error = "Account not found", trace_id = GetTraceId() });
        return Ok(new { account, trace_id = GetTraceId() });
    }

    [HttpGet]
    public IActionResult List()
    {
        var list = _store.Accounts.Values.ToList();
        return Ok(new { accounts = list, count = list.Count, trace_id = GetTraceId() });
    }

    [HttpPost]
    public IActionResult Create([FromBody] Account account)
    {
        if (string.IsNullOrEmpty(account.Id) || string.IsNullOrEmpty(account.Name))
            return BadRequest(new { error = "id and name required", trace_id = GetTraceId() });

        account.Created = DateTime.Now.ToString("yyyy-MM-dd");
        _store.Accounts[account.Id] = account;
        return CreatedAtAction(nameof(Get), new { id = account.Id }, new { account, trace_id = GetTraceId() });
    }

    [HttpPost("{id}/orders")]
    public IActionResult CreateOrder(string id, [FromBody] OrderRequest req)
    {
        if (!_store.Accounts.TryGetValue(id, out _))
            return NotFound(new { error = "Account not found", trace_id = GetTraceId() });

        var order = new
        {
            order_id = $"ORD-{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}",
            account_id = id,
            items = req.Items ?? new List<object>(),
            total = req.Total,
            status = "confirmed",
            created = DateTime.UtcNow.ToString("o"),
        };
        return CreatedAtAction(nameof(Get), new { id }, new { order, trace_id = GetTraceId() });
    }

    private string GetTraceId() =>
        HttpContext.Request.Headers["x-trace-id"].FirstOrDefault() ?? Guid.NewGuid().ToString("N")[..12];
}

public class OrderRequest
{
    public List<object>? Items { get; set; }
    public decimal Total { get; set; }
}
