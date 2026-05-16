using OrchestraApi.Middleware;
using OrchestraApi.Models;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddSingleton<InMemoryIndexStore>();
builder.Services.AddSingleton<InMemoryAccountStore>();

var app = builder.Build();
app.UseMiddleware<TracingMiddleware>();
app.UseSwagger();
app.UseSwaggerUI();
app.MapControllers();

// Seed sample data
var accounts = app.Services.GetRequiredService<InMemoryAccountStore>();
accounts.Seed();

app.Run();
