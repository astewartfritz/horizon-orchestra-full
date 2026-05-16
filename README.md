# Code Agent

A modular AI-powered autonomous coding agent with CLI, API, web UI, MCP, orchestrator, sandbox, scaffolding, benchmarking, and code review.

## Quick Install

```bash
pip install -e ".[all]"
export OPENAI_API_KEY=sk-...
code-agent run "List all Python files and count lines"
```

## CLI Commands

| Command | Description |
|---|---|
| `code-agent run` | Run an autonomous agent on a task |
| `code-agent run` | Run an autonomous agent on a task |
| `code-agent tui` | Launch Textual TUI (terminal UI) |
| `code-agent repl` | Interactive REPL session |
| `code-agent review` | Review code/diffs with AI |
| `code-agent serve` | Launch web UI (HTMX) |
| `code-agent scaffold` | Generate project from template |
| `code-agent session` | List/view/resume sessions |
| `code-agent benchmark` | Run performance benchmarks |
| `code-agent mcp` | Connect to MCP server |
| `code-agent analyze` | AST-based code analysis |
| `code-agent vector` | Semantic code search |
| `code-agent testgen` | Auto-generate tests |
| `code-agent watch` | File watching |
| `code-agent cost` | Token/cost tracking |
| `code-agent plugins` | Load external tool plugins |
| `code-agent tools` | List all available tools |
| `code-agent init` | Create config file |

## Features

- **13 built-in tools**: read, write, edit, glob, grep, bash, websearch, webfetch, git, diff, patch, apply_edit, task, scaffold, sandbox
- **Multi-LLM**: OpenAI, Anthropic, Ollama, OpenAI-compatible APIs
- **Caching**: Disk-based LLM response cache (saves tokens)
- **Web UI**: HTMX-based chat interface (via `code-agent serve`)
- **Session management**: Save/load/resume conversations
- **Orchestrator**: Sequential, parallel, and voting multi-agent execution
- **MCP support**: Connect to Model Context Protocol servers
- **Sandbox**: Docker-based isolated command execution
- **Scaffolding**: Generate projects from templates (python, typescript, fastapi, web)
- **Benchmarking**: Run and report agent performance metrics
- **Code review**: Automated PR, diff, and file review
- **Auto-retry**: Transient error recovery in tool execution

## Web UI

```bash
code-agent serve
# Open http://localhost:8000
```

## Multi-Agent Orchestration

```python
from code_agent import ParallelOrchestrator, AgentConfig

orch = ParallelOrchestrator()
results = await orch.run_map(
    "Refactor the following file: {item}",
    ["src/main.py", "src/utils.py"],
)
```

## MCP Integration

```bash
code-agent mcp path/to/mcp-config.json
```

## Extending

```python
from code_agent import Agent, Tool, ToolResult, ToolSpec

class MyTool(Tool):
    spec = ToolSpec(name="my_tool", description="Does something", parameters={})
    async def __call__(self) -> ToolResult:
        return ToolResult(output="done")

agent = Agent(AgentConfig(), custom_tools=[MyTool()])
```
