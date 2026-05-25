"""CLI commands — swarm."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def swarm():
    """Multi-agent collaboration and debate."""


@swarm.command("debate")
@click.argument("topic")
@click.option("--rounds", default=2, type=int)
def swarm_debate(topic, rounds):
    """Two agents debate a topic."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=topic, mode="debate", rounds=rounds))
    click.echo(result.output or result.error)


@swarm.command("reflect")
@click.argument("task")
def swarm_reflect(task):
    """Agent self-reflects and improves its answer."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=task, mode="reflect"))
    click.echo(result.output or result.error)


@swarm.command("specialists")
@click.argument("task")
@click.option("--roles", default="", help="Comma-separated roles (architect,engineer,reviewer,debugger,docs)")
def swarm_specialists(task, roles):
    """Team of specialists collaborate on a task."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=task, mode="specialists", roles=roles))
    click.echo(result.output or result.error)


