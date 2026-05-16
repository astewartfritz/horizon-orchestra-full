namespace OrchestraApi.Models;

public class IndexSchema
{
    public string Name { get; set; } = "";
    public List<FieldDefinition> Fields { get; set; } = new();
}

public class FieldDefinition
{
    public string Name { get; set; } = "";
    public string Type { get; set; } = "Edm.String";
    public bool Key { get; set; }
    public bool Searchable { get; set; }
    public bool Filterable { get; set; }
    public bool Retrievable { get; set; }
    public bool Sortable { get; set; }
    public bool Facetable { get; set; }
    public List<FieldDefinition>? Fields { get; set; } // nested for ComplexType
}

public class SearchRequest
{
    public string? Query { get; set; }
    public string? Filter { get; set; }
    public int Top { get; set; } = 10;
    public List<string>? Facets { get; set; }
    public List<Dictionary<string, string>>? ConversationHistory { get; set; }
}

public class SearchResponse
{
    public string IndexName { get; set; } = "";
    public string? Query { get; set; }
    public int Count { get; set; }
    public List<Dictionary<string, object>> Results { get; set; } = new();
    public Dictionary<string, List<FacetValue>>? Facets { get; set; }
    public string TraceId { get; set; } = "";
}

public class FacetValue
{
    public string Value { get; set; } = "";
    public int Count { get; set; }
}

public class Account
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Plan { get; set; } = "basic";
    public string Status { get; set; } = "active";
    public decimal Balance { get; set; }
    public string Created { get; set; } = "";
}

public class ActionDefinition
{
    public string Name { get; set; } = "";
    public string Method { get; set; } = "";
    public string Path { get; set; } = "";
    public string Description { get; set; } = "";
    public Dictionary<string, object>? Parameters { get; set; }
}
