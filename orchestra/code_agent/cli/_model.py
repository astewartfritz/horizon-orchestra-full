"""CLI commands — model."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def model():
    """Manage models and serving infrastructure."""


@model.command("list")
@click.option("--provider", help="Filter by provider (openai, anthropic, ollama)")
@click.option("--capability", help="Filter by capability (chat, streaming, structured, tools, vision, code, reasoning)")
def model_list(provider, capability):
    """List registered models with their capabilities."""
    from orchestra.code_agent.serving.registry import ModelRegistry, ModelCapability
    registry = ModelRegistry()
    cap = ModelCapability(capability) if capability else None
    models = registry.list_models(provider=provider, capability=cap)
    if not models:
        click.echo("No models found.")
        return
    click.echo(f"{'Model ID':30} {'Provider':12} {'Capabilities':40} {'Cost (in/out)':20} {'Health':10}")
    click.echo("-" * 112)
    for m in models:
        caps = ", ".join(sorted(c.value for c in m.capabilities))[:38]
        cost = f"${m.cost_per_million_input:.2f}/${m.cost_per_million_output:.2f}"
        health = m.health_status or "unknown"
        click.echo(f"{m.model_id:30} {m.provider:12} {caps:40} {cost:20} {health:10}")


@model.command("register")
@click.argument("model_id")
@click.argument("provider")
@click.option("--capabilities", "-c", multiple=True, help="Capabilities (chat, streaming, structured, tools, vision, code, reasoning)")
@click.option("--context-window", default=8192, type=int, help="Context window size")
@click.option("--max-output", default=4096, type=int, help="Max output tokens")
@click.option("--cost-in", default=0.0, type=float, help="Cost per million input tokens")
@click.option("--cost-out", default=0.0, type=float, help="Cost per million output tokens")
@click.option("--alias", multiple=True, help="Model aliases")
def model_register(model_id, provider, capabilities, context_window, max_output, cost_in, cost_out, alias):
    """Register a new model in the registry."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    entry = registry.register(
        model_id=model_id,
        provider=provider,
        capabilities=list(capabilities) if capabilities else ["chat"],
        context_window=context_window,
        max_output_tokens=max_output,
        cost_per_million_input=cost_in,
        cost_per_million_output=cost_out,
        aliases=list(alias) if alias else [],
    )
    click.echo(f"Registered: {entry.model_id} ({entry.provider})")
    click.echo(f"  Capabilities: {', '.join(sorted(c.value for c in entry.capabilities))}")


@model.command("unregister")
@click.argument("model_id")
def model_unregister(model_id):
    """Remove a model from the registry."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    if registry.unregister(model_id):
        click.echo(f"Unregistered: {model_id}")
    else:
        click.echo(f"Model not found: {model_id}")


@model.command("info")
@click.argument("model_id")
def model_info(model_id):
    """Show detailed information about a registered model."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    entry = registry.get(model_id)
    if not entry:
        click.echo(f"Model not found: {model_id}")
        return
    click.echo(f"Model ID:     {entry.model_id}")
    click.echo(f"Provider:     {entry.provider}")
    click.echo(f"Capabilities: {', '.join(sorted(c.value for c in entry.capabilities))}")
    click.echo(f"Context:      {entry.context_window:,} tokens")
    click.echo(f"Max Output:   {entry.max_output_tokens:,} tokens")
    click.echo(f"Cost (in):    ${entry.cost_per_million_input:.4f}/M tokens")
    click.echo(f"Cost (out):   ${entry.cost_per_million_output:.4f}/M tokens")
    click.echo(f"Health:       {entry.health_status}")
    click.echo(f"Aliases:      {', '.join(entry.aliases) if entry.aliases else '(none)'}")
    click.echo(f"Tags:         {entry.tags}")


@model.command("probe")
@click.argument("provider")
@click.argument("model")
@click.option("--timeout", default=10.0, type=float, help="Probe timeout in seconds")
def model_probe(provider, model, timeout):
    """Check if a model provider is healthy."""
    import asyncio
    from orchestra.code_agent.serving.health import ModelHealthChecker
    checker = ModelHealthChecker()
    result = asyncio.run(checker.probe(provider, model, timeout))
    status = "[OK] Healthy" if result.healthy else "[FAIL] Unhealthy"
    safe_echo(f"Provider: {result.provider}")
    safe_echo(f"Model:    {result.model}")
    safe_echo(f"Status:   {status}")
    safe_echo(f"Latency:  {result.latency_ms:.1f}ms")
    if result.error:
        click.echo(f"Error:    {result.error}")


@model.command("route")
@click.argument("prompt")
@click.option("--strategy", default="fallback", help="Routing strategy: fallback, cheapest, fastest, round_robin, weighted")
@click.option("--capability", help="Required capability")
def model_route(prompt, strategy, capability):
    """Route a prompt through the model router and return the response."""
    import asyncio
    from orchestra.code_agent.llm.base import Message
    from orchestra.code_agent.serving.registry import ModelRegistry, ModelCapability
    from orchestra.code_agent.serving.router import ModelRouter, RouterRule, RouteTarget, RoutingStrategy

    registry = ModelRegistry()
    cap = ModelCapability(capability) if capability else None
    targets = [RouteTarget(provider=m.provider, model=m.model_id) for m in registry.list_models()]
    rule = RouterRule(
        name="cli-route",
        strategy=RoutingStrategy(strategy),
        targets=targets or [RouteTarget(provider="openai", model="gpt-4o")],
        required_capability=cap,
    )
    router = ModelRouter(registry, rules=[rule])
    messages = [Message(role="user", content=prompt)]
    result = asyncio.run(router.route_chat(messages, task=prompt))

    if result.success:
        safe_echo(f"\n[OK] Routed to: {result.provider}/{result.model}")
        safe_echo(f"Latency: {result.total_latency:.2f}s")
        safe_echo(f"Attempts: {len(result.attempts)}")
        safe_echo(f"\nResponse:\n{result.output[:2000]}")
    else:
        safe_echo(f"\n[FAIL] All routing attempts failed:")
        for a in result.attempts:
            safe_echo(f"  - {a['provider']}/{a['model']}: {a.get('error', 'unknown')}")


@model.command("health")
def model_health():
    """Show health summary for all probed models."""
    import asyncio
    from orchestra.code_agent.serving.health import ModelHealthChecker
    from orchestra.code_agent.serving.registry import ModelRegistry

    registry = ModelRegistry()
    checker = ModelHealthChecker()
    for m in registry.list_models():
        checker.register(m.provider, m.model_id, interval=300)
    results = asyncio.run(checker.probe_all())

    if not results:
        click.echo("No probe results. Use 'model probe' to check specific models.")
        return

    click.echo(f"{'Model':30} {'Health':10} {'Latency':10}")
    click.echo("-" * 50)
    for key, r in sorted(results.items()):
        status = "[OK]" if r.healthy else "[FAIL]"
        safe_echo(f"{key:30} {status + ' healthy':10} {r.latency_ms:>8.1f}ms")


