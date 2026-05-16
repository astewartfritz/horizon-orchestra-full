using System.Collections.Concurrent;
using OrchestraApi.Models;

namespace OrchestraApi.Models;

public class InMemoryIndexStore
{
    public ConcurrentDictionary<string, IndexSchema> Indexes { get; } = new();
    public ConcurrentDictionary<string, List<Dictionary<string, object>>> Documents { get; } = new();
}

public class InMemoryAccountStore
{
    public ConcurrentDictionary<string, Account> Accounts { get; } = new();

    public void Seed()
    {
        var data = new[]
        {
            new Account { Id = "acc-001", Name = "Acme Corp", Plan = "enterprise", Status = "active", Balance = 12500, Created = "2024-01-15" },
            new Account { Id = "acc-002", Name = "Globex Inc", Plan = "pro", Status = "active", Balance = 3400, Created = "2024-03-22" },
            new Account { Id = "acc-003", Name = "Initech", Plan = "basic", Status = "suspended", Balance = 0, Created = "2023-11-01" },
        };
        foreach (var a in data) Accounts.TryAdd(a.Id, a);
    }
}
