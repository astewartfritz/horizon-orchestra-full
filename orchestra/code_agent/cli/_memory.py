"""CLI commands — memory."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def memory():
    """Manage agent memory, retrieval, and consolidation."""


@memory.command("store")
@click.argument("content")
@click.option("--tier", default="normal", help="Tier: critical, important, normal, low")
@click.option("--importance", default=0.5, type=float, help="Importance 0.0-1.0")
@click.option("--source", default="cli", help="Source label")
def memory_store(content, tier, importance, source):
    """Store a memory."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    mid = mgr.remember(content=content, tier=tier, importance=importance, source=source)
    click.echo(f"Stored memory #{mid}")


@memory.command("search")
@click.argument("query")
@click.option("--top-k", default=10, type=int, help="Number of results")
@click.option("--type", "memory_type", help="Filter by type: working, episodic, semantic, long_term")
def memory_search(query, top_k, memory_type):
    """Search memories by semantic similarity."""
    import asyncio
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    results = mgr.search_memories(query, top_k=top_k, memory_type=memory_type)
    if not results:
        click.echo("No matching memories found.")
        return
    click.echo(f"Found {len(results)} memories:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.tier:10}][{r.source:15}] ({r.score:.3f}) {r.content[:120]}...")


@memory.command("recall")
@click.argument("query")
@click.option("--top-k", default=5, type=int, help="Number of context snippets")
def memory_recall(query, top_k):
    """Retrieve relevant memory context for a query."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    context = mgr.get_context(query, max_tokens=top_k * 2000)
    if not context:
        click.echo("No relevant memories found.")
        return
    click.echo(context)


@memory.command("recent")
@click.option("--limit", default=20, type=int)
def memory_recent(limit):
    """Show most recent memories."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    results = mgr.recall_recent(limit=limit)
    if not results:
        click.echo("No recent memories.")
        return
    click.echo(f"Recent {len(results)} memories:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.tier:10}] ({time.strftime('%H:%M:%S', time.localtime(r.created_at))}) {r.content[:150]}...")


@memory.command("forget")
@click.argument("memory_id", type=int)
def memory_forget(memory_id):
    """Delete a specific memory by ID."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    if mgr.forget(memory_id):
        click.echo(f"Forgot memory #{memory_id}")
    else:
        click.echo(f"Memory #{memory_id} not found")


@memory.command("stats")
def memory_stats():
    """Show memory system statistics."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    stats = mgr.stats()
    ss = stats.get("store", {})
    bs = stats.get("buffer", {})
    gs = stats.get("graph", {})
    click.echo("Memory Statistics:")
    click.echo(f"  Store: {ss.get('total_memories', 0):>6} memories ({ss.get('total_tokens', 0):>8} tokens)")
    click.echo(f"    By type: {ss.get('by_type', {})}")
    click.echo(f"    By tier: {ss.get('by_tier', {})}")
    click.echo(f"  Buffer: {bs.get('total_entries', 0):>6} entries ({bs.get('utilization', 0)}% full)")
    click.echo(f"  Entities: {gs.get('total_entities', 0)} in graph")


@memory.command("consolidate")
@click.option("--session-id", help="Also summarize this session")
def memory_consolidate(session_id):
    """Run memory consolidation (dedup, tier migration, cleanup)."""
    import asyncio
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    reports = asyncio.run(mgr.consolidate(session_id=session_id))
    click.echo("Consolidation complete:\n")
    for r in reports:
        click.echo(f"  [{r.operation}] {r.summary} ({r.tokens_saved} tokens, {r.duration_ms:.0f}ms)")


@memory.command("entities")
@click.argument("name", required=False)
@click.option("--depth", default=2, type=int, help="Graph traversal depth")
def memory_entities(name, depth):
    """Show entity graph. With NAME, show entity network centered on that entity."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    if name:
        network = mgr.get_entity_network(name, depth=depth)
        click.echo(f"Entity Network: {name}")
        click.echo(f"  Nodes: {len(network.get('nodes', []))}")
        click.echo(f"  Edges: {len(network.get('edges', []))}")
        for edge in network.get("edges", [])[:10]:
            click.echo(f"    {edge['source']} --[{edge['relation']}]--> {edge['target']}")
    else:
        stats = mgr.stats()
        gs = stats.get("graph", {})
        click.echo(f"Total entities: {gs.get('total_entities', 0)}")
        for t, c in gs.get("by_type", {}).items():
            click.echo(f"  {t}: {c}")


@memory.command("clear")
@click.option("--force", is_flag=True, help="Confirm clearing all memories")
def memory_clear(force):
    """Clear all memories (requires --force)."""
    if not force:
        click.echo("Use --force to confirm clearing all memories.")
        return
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    mgr.clear()
    click.echo("All memories cleared.")


@main.group()
def knowledge():
    """Manage agent knowledge base (persistent memory)."""


@knowledge.command("store")
@click.argument("content")
@click.option("-k", "--key", default="", help="Memory key")
@click.option("--source", default="cli", help="Source label")
@click.option("--tags", default="", help="Comma-separated tags")
def knowledge_store(content, key, source, tags):
    """Store content in knowledge base."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    if not key:
        import time
        key = f"cli_{int(time.time() * 1000)}"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    kb.store(key, content, source=source, tags=tag_list)
    click.echo(f"Stored: {key}")


@knowledge.command("search")
@click.argument("query")
@click.option("-k", "--top-k", default=5, type=int)
@click.option("--tag", default="", help="Filter by tag")
def knowledge_search(query, top_k, tag):
    """Search knowledge base."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    results = kb.search(query, top_k=top_k, tag_filter=tag)
    if not results:
        click.echo("(no results)")
        return
    for r in results:
        e = r.entry
        click.echo(f"\n  [{r.score:.3f}] {e.key} ({e.source})")
        click.echo(f"         {e.content[:120].strip()}")


@knowledge.command("stats")
def knowledge_stats():
    """Show knowledge base stats."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    for k, v in kb.stats().items():
        click.echo(f"  {k}: {v}")


