from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import click

from orchestra.code_agent import Agent, AgentConfig


def safe_echo(msg: str, nl: bool = True, err: bool = False) -> None:
    """Echo text safely on Windows consoles that don't support Unicode."""
    try:
        click.echo(msg, nl=nl, err=err)
    except UnicodeEncodeError:
        ascii_safe = msg.encode("ascii", "replace").decode("ascii")
        click.echo(ascii_safe, nl=nl, err=err)

import os as _SYS_ENVIRON
from orchestra.code_agent.config import LLMConfig



@click.group()
def main():
    """Code Agent - Autonomous AI-powered software engineering assistant."""


@main.command()
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="Model name")
@click.option("--stream/--no-stream", default=True, help="Stream tokens live")
def chat(provider, model, stream):
    """Interactive chat session with the agent."""
    import sys
    from orchestra.code_agent.llm.base import LLM, Message

    llm = LLM(provider=provider, model=model)
    safe_echo(f"Orchestra chat ({provider}/{model}) — Ctrl+C or type /exit to quit")
    safe_echo("")

    messages = []
    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            safe_echo("")
            break

        if user_input.lower() in ("/exit", "/quit", ""):
            break

        messages.append(Message(role="user", content=user_input))

        try:
            if stream:
                safe_echo("Agent: ", nl=False)
                response = asyncio.run(llm.chat(messages, stream=True))
                safe_echo("")
            else:
                response = asyncio.run(llm.chat(messages))
                safe_echo(f"Agent: {response.content}")

            if response.content:
                messages.append(Message(role="assistant", content=response.content))

        except KeyboardInterrupt:
            safe_echo("\n[Interrupted]")
            break
        except Exception as e:
            safe_echo(f"Error: {e}")

    safe_echo("Bye!")


# ═══════════════════════════════════════════════════════════════
# Shell Completions
# ═══════════════════════════════════════════════════════════════

@main.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish", "powershell"]))
def completion(shell):
    """Generate shell completion scripts."""
    import subprocess, sys

    if shell == "powershell":
        script = """
# Orchestra CLI PowerShell completion
Register-ArgumentCompleter -Native -CommandName code-agent -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    code-agent completion powershell-inner | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }
}
"""
        safe_echo(script.strip())
    else:
        # Use Click's built-in completion for bash/zsh/fish
        env = {**dict(_SYS_ENVIRON), "_CODE_AGENT_COMPLETE": f"{shell}_source"}
        r = subprocess.run([sys.executable, "-m", "code_agent.cli"], capture_output=True, text=True, env=env)
        safe_echo(r.stdout)


# ═══════════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════════

@main.command()
def version():
    """Show version information."""
    try:
        from importlib.metadata import version as _v
        v = _v("code-agent")
    except Exception:
        v = "1.0.0"
    safe_echo(f"Orchestra v{v}")
    safe_echo("Autonomous AI software engineering assistant")


if __name__ == "__main__":
    main()
