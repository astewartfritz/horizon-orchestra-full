namespace OrchestraApi.Middleware;

public class TracingMiddleware
{
    private readonly RequestDelegate _next;
    public TracingMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context)
    {
        var traceId = context.Request.Headers["x-trace-id"].FirstOrDefault();
        if (string.IsNullOrEmpty(traceId))
            traceId = Guid.NewGuid().ToString("N")[..12];

        context.Response.OnStarting(() =>
        {
            context.Response.Headers["x-trace-id"] = traceId;
            return Task.CompletedTask;
        });

        context.Items["TraceId"] = traceId;
        await _next(context);
    }
}
