"""CLI commands — trace."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def trace():
    """Agent trace collection, viewing, and export."""


@trace.command("list")
@click.option("--limit", default=20, type=int, help="Number of traces to show")
def trace_list(limit):
    """List recent agent execution traces."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.list_traces(limit=limit))


@trace.command("show")
@click.argument("trace_id")
@click.option("--waterfall", is_flag=True, help="Show waterfall timeline")
def trace_show(trace_id, waterfall):
    """Show detailed trace with timeline."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    if waterfall:
        click.echo(viewer.waterfall(trace_id))
    else:
        click.echo(viewer.show_trace(trace_id))


@trace.command("search")
@click.argument("query")
@click.option("--limit", default=50, type=int)
def trace_search(query, limit):
    """Search trace events by text."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.search(query, limit=limit))


@trace.command("stats")
def trace_stats():
    """Show trace collection statistics."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.summary())


@trace.command("export")
@click.argument("trace_id", required=False)
@click.option("--format", "fmt", default="md", help="Export format: md, chrome, otel")
@click.option("--output", "-o", help="Output path")
@click.option("--all", "export_all", is_flag=True, help="Export all traces")
def trace_export(trace_id, fmt, output, export_all):
    """Export trace as markdown, Chrome trace, or summary."""
    import asyncio
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.export import TraceExporter
    collector = TraceCollector()
    exporter = TraceExporter(collector)

    if export_all:
        out = exporter.export_all(output or ".agent-trace-export")
        click.echo(f"Exported all traces to {out}")
        return

    if not trace_id:
        click.echo("Provide a trace_id or use --all")
        return

    if fmt == "chrome":
        path = output or f"trace-{trace_id}.json"
        exporter.to_chrome_trace(trace_id, path)
        click.echo(f"Chrome trace exported to {path}")
    elif fmt == "otel":
        path = output or f"trace-{trace_id}.json"
        data = exporter.to_chrome_trace(trace_id, path)
        click.echo(f"Trace exported to {path}")
    else:
        path = output or f"trace-{trace_id}.md"
        exporter.to_markdown(trace_id, path)
        click.echo(f"Trace markdown exported to {path}")


@main.group()
def export():
    """Export agent data."""


@export.command("sessions")
@click.option("-f", "--format", "fmt", default="json", help="json or markdown")
@click.option("-o", "--output", default="session-exports", help="Output directory")
def export_sessions(fmt, output):
    """Export all sessions."""
    from orchestra.code_agent.export.session_export import SessionExporter
    files = SessionExporter.export_all(format=fmt, output_dir=output)
    click.echo(f"Exported {len(files)} sessions to {output}/")


@export.command("archive")
@click.option("-o", "--output", default="", help="Output zip path")
def export_archive(output):
    """Export all agent data as a zip archive."""
    from orchestra.code_agent.export.full_export import FullExporter
    path = FullExporter.export(output_path=output)
    click.echo(f"Exported to: {path}")


@export.command("import")
@click.argument("archive_path")
@click.option("-o", "--output", default=".agent-import", help="Extract directory")
def export_import(archive_path, output):
    """Import agent data from a zip archive."""
    from orchestra.code_agent.export.full_export import FullExporter
    files = FullExporter.import_archive(archive_path, extract_dir=output)
    click.echo(f"Imported {len(files)} files to {output}/")


