# Code Architectures for Building an Advanced Perplexity Computer with Kimi K2.5

## Executive Summary

Kimi K2.5 is a 1T-parameter MoE model (32B activated) with an OpenAI-compatible API, native multimodal capabilities, and Agent Swarm orchestration for up to 100 parallel sub-agents. Its architecture maps directly to every core pattern Perplexity Computer uses — meta-routing, sub-agent decomposition, tool calling, persistent memory, and citation grounding — at a fraction of the cost (76% cheaper than Claude Opus 4.5).

Below are five production-ready architectures, ordered from simplest to most advanced, each designed to replicate and extend Perplexity Computer's capabilities.

---

## Architecture 1: Meta-Router + Hybrid Model Orchestrator

**What Perplexity Does:** A meta-router classifies incoming queries by type (search, code, math, creative) and dispatches to the best-fit model among 19 options.

**How to Build It with Kimi K2.5:**

Kimi K2.5 serves as your primary workhorse for 80-90% of tasks (agentic workflows, code gen, multimodal reasoning), with fallback routing to specialized models when needed.

```
┌─────────────────────────────────────────────┐
│              INCOMING REQUEST               │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │   TASK CLASSIFIER   │
         │  (lightweight LLM   │
         │   or rule engine)   │
         └─────────┬──────────┘
                   │
    ┌──────────────┼──────────────┬───────────────┐
    │              │              │               │
    ▼              ▼              ▼               ▼
┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│ Kimi   │  │ Kimi     │  │ Kimi     │  │ Claude/GPT   │
│ K2.5   │  │ K2.5     │  │ K2.5     │  │ Fallback     │
│ Instant│  │ Thinking │  │ Agent    │  │ (complex     │
│        │  │          │  │          │  │  tool calls) │
└────────┘  └──────────┘  └──────────┘  └──────────────┘
```

### Core Implementation

```python
# meta_router.py
from openai import OpenAI
from enum import Enum
from dataclasses import dataclass

class TaskMode(Enum):
    INSTANT = "instant"       # Fast Q&A, formatting, extraction
    THINKING = "thinking"     # Multi-step reasoning, math, debugging
    AGENT = "agent"           # Tool-augmented workflows (200-300 calls)
    AGENT_SWARM = "swarm"     # Parallel decomposition (100 sub-agents)
    FALLBACK = "fallback"     # Claude/GPT for edge cases

@dataclass
class RouteDecision:
    mode: TaskMode
    model: str
    base_url: str
    extra_body: dict | None = None

class MetaRouter:
    """Classifies tasks and routes to optimal Kimi K2.5 mode or fallback."""

    def __init__(self, moonshot_key: str, fallback_key: str):
        self.kimi_client = OpenAI(
            api_key=moonshot_key,
            base_url="https://api.moonshot.ai/v1"
        )
        self.fallback_client = OpenAI(api_key=fallback_key)

        # Classification prompt — keep tool surface small per Trilogy's guidance
        self.classifier_prompt = """Classify this task into exactly one mode:
        - INSTANT: simple Q&A, formatting, summarization, extraction
        - THINKING: math, logic puzzles, debugging, step-by-step analysis
        - AGENT: needs tools (search, code execution, file I/O, browsing)
        - SWARM: parallelizable research across 5+ independent subtasks
        - FALLBACK: requires >8 specialized tools or mission-critical precision

        Respond with just the mode name."""

    def classify(self, user_message: str) -> RouteDecision:
        response = self.kimi_client.chat.completions.create(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": self.classifier_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=20,
            extra_body={"thinking": {"type": "disabled"}}  # Instant mode for speed
        )
        mode_str = response.choices[0].message.content.strip().upper()
        return self._build_route(TaskMode[mode_str])

    def _build_route(self, mode: TaskMode) -> RouteDecision:
        routes = {
            TaskMode.INSTANT: RouteDecision(
                mode=mode, model="kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
                extra_body={"thinking": {"type": "disabled"}}
            ),
            TaskMode.THINKING: RouteDecision(
                mode=mode, model="kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
                extra_body=None  # Thinking mode enabled by default
            ),
            TaskMode.AGENT: RouteDecision(
                mode=mode, model="kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
                extra_body=None
            ),
            TaskMode.AGENT_SWARM: RouteDecision(
                mode=mode, model="kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
                extra_body=None
            ),
            TaskMode.FALLBACK: RouteDecision(
                mode=mode, model="claude-sonnet-4-20250514",
                base_url="https://api.anthropic.com/v1",
                extra_body=None
            ),
        }
        return routes[mode]
```

**Key Insight from Trilogy AI:** Limit Kimi K2.5's tool surface to 5-8 tools per agent. When it sees too many tools, it confuses tool selection. Use structured reference tables (not paragraphs) for tool guidance. Source: [Trilogy AI](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25)

---

## Architecture 2: Sub-Agent Decomposition Engine

**What Perplexity Does:** Complex queries spawn specialized sub-agents (research, analysis, code execution) with dependency management between them.

**How to Build It with Kimi K2.5:**

Leverage K2.5's native Agent Swarm capability — no need to hand-wire agent graphs. The orchestrator dynamically creates domain-specific agents and manages parallelism.

```
┌──────────────────────────────────────────────────────┐
│                   ORCHESTRATOR                        │
│            (Kimi K2.5 Agent Swarm)                   │
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐             │
│  │ Planner │──│Decompose│──│ Merge   │             │
│  └─────────┘  └────┬────┘  └────▲────┘             │
│                    │             │                    │
│         ┌──────────┼──────────┐  │                    │
│         │          │          │  │                    │
│    ┌────▼───┐ ┌────▼───┐ ┌───▼──┴──┐               │
│    │Sub-Agt │ │Sub-Agt │ │Sub-Agt  │               │
│    │Research│ │Analysis│ │CodeExec │               │
│    │(100    │ │(100    │ │(100     │               │
│    │ steps) │ │ steps) │ │ steps)  │               │
│    └────────┘ └────────┘ └─────────┘               │
└──────────────────────────────────────────────────────┘
```

### Core Implementation

```python
# sub_agent_engine.py
import asyncio
import json
from openai import AsyncOpenAI
from dataclasses import dataclass, field

@dataclass
class SubTask:
    id: str
    description: str
    tools: list[dict]         # Max 5-8 tools per sub-agent
    dependencies: list[str] = field(default_factory=list)
    result: str | None = None

@dataclass
class AgentPlan:
    subtasks: list[SubTask]
    synthesis_prompt: str

class SubAgentEngine:
    """Decomposes tasks into parallel sub-agents with dependency management."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.moonshot.ai/v1"
        )

    async def decompose(self, task: str) -> AgentPlan:
        """Use Kimi K2.5 Thinking mode to plan the decomposition."""
        response = await self.client.chat.completions.create(
            model="kimi-k2.5",
            messages=[{
                "role": "system",
                "content": """You are a task decomposition planner. Given a complex task,
                break it into independent subtasks that can run in parallel.
                Output JSON: {
                    "subtasks": [
                        {"id": "t1", "description": "...", "tools": ["search", "browse"],
                         "dependencies": []},
                        {"id": "t2", "description": "...", "tools": ["code_exec"],
                         "dependencies": ["t1"]}
                    ],
                    "synthesis_prompt": "How to merge results into final output"
                }"""
            }, {
                "role": "user",
                "content": task
            }],
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        plan_data = json.loads(response.choices[0].message.content)
        return AgentPlan(
            subtasks=[SubTask(**st) for st in plan_data["subtasks"]],
            synthesis_prompt=plan_data["synthesis_prompt"]
        )

    async def execute_subtask(self, subtask: SubTask,
                               context: dict[str, str]) -> str:
        """Execute a single sub-agent with its dedicated tool surface."""
        # Inject dependency results into context
        dep_context = "\n".join(
            f"[Result from {dep}]: {context[dep]}"
            for dep in subtask.dependencies if dep in context
        )

        # Build tool definitions — keep to 5-8 max
        tools = self._build_tools(subtask.tools)

        messages = [{
            "role": "system",
            "content": f"""You are a specialized sub-agent.
            Task: {subtask.description}
            Prior context: {dep_context}

            ## Tool Selection Rules
            | I want to...           | Use this tool |
            |------------------------|---------------|
            | Search the web         | web_search    |
            | Execute Python code    | code_exec     |
            | Read a file            | file_read     |
            | Browse a webpage       | browser       |
            | Write/save output      | file_write    |
            """
        }, {
            "role": "user",
            "content": subtask.description
        }]

        # Agent loop — up to 100 steps per sub-agent
        for step in range(100):
            response = await self.client.chat.completions.create(
                model="kimi-k2.5",
                messages=messages,
                tools=tools,
                max_tokens=4096
            )
            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    result = await self._execute_tool(tc)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result
                    })
            else:
                return msg.content

        return messages[-1]["content"] if messages else "Max steps reached"

    async def run(self, task: str) -> str:
        """Full pipeline: decompose → parallel execute → synthesize."""
        plan = await self.decompose(task)
        results: dict[str, str] = {}

        # Topological execution with parallelism
        while len(results) < len(plan.subtasks):
            ready = [
                st for st in plan.subtasks
                if st.id not in results
                and all(d in results for d in st.dependencies)
            ]
            completed = await asyncio.gather(*[
                self.execute_subtask(st, results) for st in ready
            ])
            for st, result in zip(ready, completed):
                results[st.id] = result

        # Synthesize with Kimi K2.5 Thinking mode
        synthesis = await self.client.chat.completions.create(
            model="kimi-k2.5",
            messages=[{
                "role": "system",
                "content": plan.synthesis_prompt
            }, {
                "role": "user",
                "content": json.dumps(results, indent=2)
            }],
            max_tokens=8192
        )
        return synthesis.choices[0].message.content

    def _build_tools(self, tool_names: list[str]) -> list[dict]:
        """Return OpenAI-format tool definitions for the given names."""
        tool_registry = {
            "web_search": {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web and return results with URLs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"}
                        },
                        "required": ["query"]
                    }
                }
            },
            "code_exec": {
                "type": "function",
                "function": {
                    "name": "code_exec",
                    "description": "Execute Python code in a sandboxed environment",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Python code"}
                        },
                        "required": ["code"]
                    }
                }
            },
            "browser": {
                "type": "function",
                "function": {
                    "name": "browser",
                    "description": "Navigate to a URL and extract content",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "action": {"type": "string", "enum": ["read", "click", "fill"]}
                        },
                        "required": ["url", "action"]
                    }
                }
            },
            "file_read": {
                "type": "function",
                "function": {
                    "name": "file_read",
                    "description": "Read contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"}
                        },
                        "required": ["path"]
                    }
                }
            },
            "file_write": {
                "type": "function",
                "function": {
                    "name": "file_write",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"}
                        },
                        "required": ["path", "content"]
                    }
                }
            }
        }
        return [tool_registry[name] for name in tool_names if name in tool_registry]

    async def _execute_tool(self, tool_call) -> str:
        """Route tool calls to actual implementations."""
        # Implement your actual tool backends here
        raise NotImplementedError("Wire up your tool backends")
```

---

## Architecture 3: Search-Grounded Citation Engine (Sonar Equivalent)

**What Perplexity Does:** Every factual claim is grounded with inline citations from real-time web search, using Sonar's citation-first architecture.

**How to Build It with Kimi K2.5 + Perplexity Sonar API:**

Use Sonar for retrieval and citation extraction, Kimi K2.5 for reasoning and synthesis. This is cheaper than using Sonar for the full generation.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   User      │────▶│  Sonar API   │────▶│  Kimi K2.5      │
│   Query     │     │  (Retrieval  │     │  (Synthesis +   │
│             │     │  + Citations)│     │   Reasoning)    │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Cited Response  │
                                          │  with inline     │
                                          │  [source](url)   │
                                          └─────────────────┘
```

### Core Implementation

```python
# citation_engine.py
from openai import OpenAI
import httpx
from dataclasses import dataclass

@dataclass
class Citation:
    text: str
    url: str
    title: str

@dataclass
class GroundedResponse:
    answer: str
    citations: list[Citation]
    reasoning: str | None = None

class CitationEngine:
    """Combines Perplexity Sonar retrieval with Kimi K2.5 synthesis."""

    def __init__(self, sonar_key: str, moonshot_key: str):
        self.sonar = OpenAI(
            api_key=sonar_key,
            base_url="https://api.perplexity.ai"
        )
        self.kimi = OpenAI(
            api_key=moonshot_key,
            base_url="https://api.moonshot.ai/v1"
        )

    def retrieve_with_citations(self, query: str) -> dict:
        """Use Sonar to get search-grounded passages with citations."""
        response = self.sonar.chat.completions.create(
            model="sonar-pro",  # or sonar-reasoning-pro for chain-of-thought
            messages=[{"role": "user", "content": query}]
        )
        return {
            "passages": response.choices[0].message.content,
            "citations": getattr(response, "citations", []),
            "raw": response
        }

    def synthesize(self, query: str, retrieval: dict,
                   think: bool = True) -> GroundedResponse:
        """Use Kimi K2.5 to reason over retrieved passages and produce
        a cited response."""
        system_prompt = """You are a research synthesis engine.
        Given retrieved passages with source citations, produce a
        comprehensive answer with INLINE citations in [Source Title](url) format.

        Rules:
        - Every factual claim MUST have an inline citation
        - Cite the source immediately after the relevant sentence
        - Use the exact URLs provided — never fabricate URLs
        - If sources conflict, note the disagreement and cite both
        - Structure with clear headers for readability"""

        extra_body = None if think else {"thinking": {"type": "disabled"}}

        response = self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Query: {query}

                Retrieved Sources:
                {retrieval['passages']}

                Source URLs: {retrieval['citations']}"""}
            ],
            max_tokens=8192,
            extra_body=extra_body
        )

        return GroundedResponse(
            answer=response.choices[0].message.content,
            citations=[
                Citation(text="", url=c, title="")
                for c in retrieval.get("citations", [])
            ],
            reasoning=getattr(
                response.choices[0].message, "reasoning_content", None
            )
        )

    def query(self, user_query: str, deep: bool = False) -> GroundedResponse:
        """Full pipeline: retrieve → synthesize with citations."""
        # Step 1: Sonar retrieval
        retrieval = self.retrieve_with_citations(user_query)

        # Step 2: Kimi synthesis with reasoning
        return self.synthesize(user_query, retrieval, think=deep)
```

---

## Architecture 4: MCP-Native Tool Mesh

**What Perplexity Does:** Connects to 100+ enterprise tools via connectors (Gmail, Slack, Notion, GitHub, CRM, etc.).

**How to Build It with Kimi K2.5 + MCP:**

MCP (Model Context Protocol) is the standard for connecting LLMs to external tools. Build an MCP server mesh where each service is an MCP server, and Kimi K2.5 acts as the MCP client that discovers and calls tools dynamically.

```
┌─────────────────────────────────────────────────────────────┐
│                    KIMI K2.5 (MCP CLIENT)                   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              MCP Client Manager                       │   │
│  │  - Discovers available MCP servers                    │   │
│  │  - Routes tool calls to correct server                │   │
│  │  - Manages auth tokens per connection                 │   │
│  └──────────┬───────────┬──────────────┬────────────────┘   │
│             │           │              │                     │
└─────────────┼───────────┼──────────────┼─────────────────────┘
              │           │              │
     ┌────────▼───┐ ┌─────▼─────┐ ┌─────▼──────┐
     │ MCP Server │ │MCP Server │ │ MCP Server │
     │   Gmail    │ │  GitHub   │ │   Slack    │  ...
     │            │ │           │ │            │
     │ - search   │ │ - issues  │ │ - messages │
     │ - send     │ │ - PRs     │ │ - channels │
     │ - draft    │ │ - commits │ │ - files    │
     └────────────┘ └───────────┘ └────────────┘
```

### Core Implementation

```python
# mcp_tool_mesh.py
import json
import subprocess
from openai import OpenAI
from dataclasses import dataclass

@dataclass
class MCPServer:
    name: str
    command: str           # e.g., "npx @anthropic/mcp-gmail"
    args: list[str]
    env: dict[str, str]    # Auth tokens, API keys
    tools: list[dict] = None  # Populated after discovery

class MCPToolMesh:
    """Manages MCP servers and exposes their tools to Kimi K2.5."""

    def __init__(self, moonshot_key: str):
        self.kimi = OpenAI(
            api_key=moonshot_key,
            base_url="https://api.moonshot.ai/v1"
        )
        self.servers: dict[str, MCPServer] = {}
        self._tool_to_server: dict[str, str] = {}

    def register_server(self, server: MCPServer):
        """Register an MCP server and discover its tools."""
        self.servers[server.name] = server
        # Launch the MCP server process and call tools/list
        tools = self._discover_tools(server)
        server.tools = tools
        for tool in tools:
            self._tool_to_server[tool["function"]["name"]] = server.name

    def _discover_tools(self, server: MCPServer) -> list[dict]:
        """Call the MCP server's tools/list endpoint."""
        # In production, use the MCP SDK's client transport
        # This is a simplified representation
        proc = subprocess.Popen(
            [server.command] + server.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**server.env}
        )
        # Send JSON-RPC tools/list request
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        })
        proc.stdin.write(request.encode() + b"\n")
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
        # Convert MCP tool format to OpenAI function format
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{server.name}__{tool['name']}",
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {})
                }
            }
            for tool in response.get("result", {}).get("tools", [])
        ]

    def get_available_tools(self, max_per_agent: int = 8) -> list[dict]:
        """Return all registered tools (paginated for Kimi's 5-8 tool limit)."""
        all_tools = []
        for server in self.servers.values():
            all_tools.extend(server.tools or [])
        return all_tools[:max_per_agent]

    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Route a tool call to the correct MCP server."""
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            return f"Error: Unknown tool {tool_name}"

        server = self.servers[server_name]
        # Strip server prefix from tool name
        raw_name = tool_name.replace(f"{server_name}__", "")

        # Send JSON-RPC tools/call to the MCP server
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": raw_name, "arguments": arguments},
            "id": 2
        })
        # In production, maintain persistent connections per server
        proc = subprocess.Popen(
            [server.command] + server.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**server.env}
        )
        proc.stdin.write(request.encode() + b"\n")
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
        return json.dumps(response.get("result", {}))

    async def agent_loop(self, user_message: str, max_steps: int = 200):
        """Run the Kimi K2.5 agent loop with MCP tools."""
        tools = self.get_available_tools()

        # Build tool guidance table for Kimi
        tool_table = "## Tool Selection Rules\n| I want to... | Use this tool |\n|---|---|\n"
        for t in tools:
            fn = t["function"]
            tool_table += f"| {fn['description'][:50]} | **{fn['name']}** |\n"

        messages = [
            {"role": "system", "content": f"""You are an advanced AI agent with
            access to external tools via MCP. Use tools to accomplish tasks.

            {tool_table}
            """},
            {"role": "user", "content": user_message}
        ]

        for step in range(max_steps):
            response = self.kimi.chat.completions.create(
                model="kimi-k2.5",
                messages=messages,
                tools=tools,
                max_tokens=4096
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content

            messages.append(msg)
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self.execute_tool(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })

        return "Max steps reached"


# Example: Register Gmail and GitHub MCP servers
mesh = MCPToolMesh(moonshot_key="your-key")

mesh.register_server(MCPServer(
    name="gmail",
    command="npx",
    args=["@anthropic/mcp-gmail"],
    env={"GMAIL_TOKEN": "..."}
))

mesh.register_server(MCPServer(
    name="github",
    command="npx",
    args=["@anthropic/mcp-github"],
    env={"GITHUB_TOKEN": "..."}
))
```

---

## Architecture 5: Full Autonomous Agent OS (The Endgame)

**What Perplexity Does:** Persistent memory, scheduled tasks, background execution, multi-model orchestration, sub-agent spawning, tool mesh, citation grounding — all unified.

**How to Build the Complete System:**

This is the full architecture combining all four patterns above, plus persistent memory and cron scheduling.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AGENT OS LAYER                              │
│                                                                     │
│  ┌───────────┐  ┌────────────┐  ┌───────────┐  ┌───────────────┐  │
│  │  Memory   │  │   Cron     │  │  Session  │  │  Event Bus    │  │
│  │  Store    │  │  Scheduler │  │  Manager  │  │  (pub/sub)    │  │
│  │ (Redis/PG)│  │  (APSched) │  │           │  │               │  │
│  └─────┬─────┘  └─────┬──────┘  └─────┬─────┘  └───────┬───────┘  │
│        │              │              │                │           │
│  ┌─────▼──────────────▼──────────────▼────────────────▼─────────┐  │
│  │                    ORCHESTRATOR CORE                           │  │
│  │                                                               │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐  │  │
│  │  │  Meta    │  │  Sub-Agent   │  │  Citation Engine       │  │  │
│  │  │  Router  │  │  Engine      │  │  (Sonar + Kimi K2.5)  │  │  │
│  │  │ (Arch 1) │  │  (Arch 2)   │  │  (Arch 3)             │  │  │
│  │  └──────────┘  └──────────────┘  └────────────────────────┘  │  │
│  │                                                               │  │
│  │  ┌────────────────────────────────────────────────────────┐  │  │
│  │  │              MCP Tool Mesh (Arch 4)                     │  │  │
│  │  │  Gmail | GitHub | Slack | Notion | CRM | DB | ...      │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    EXECUTION SANDBOX                           │  │
│  │  Docker containers | Code interpreter | Browser (Playwright) │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Core Implementation

```python
# agent_os.py
import asyncio
import json
from datetime import datetime
from dataclasses import dataclass, field
from openai import AsyncOpenAI

@dataclass
class Memory:
    """Persistent memory store — use Redis or Postgres in production."""
    facts: dict[str, str] = field(default_factory=dict)
    conversations: list[dict] = field(default_factory=list)

    def store(self, key: str, value: str):
        self.facts[key] = value

    def search(self, query: str) -> list[str]:
        # In production: vector similarity search over embeddings
        return [v for k, v in self.facts.items() if query.lower() in k.lower()]

    def add_turn(self, role: str, content: str):
        self.conversations.append({
            "role": role, "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

class AgentOS:
    """Full autonomous agent operating system powered by Kimi K2.5."""

    def __init__(self, config: dict):
        self.kimi = AsyncOpenAI(
            api_key=config["moonshot_key"],
            base_url="https://api.moonshot.ai/v1"
        )
        self.sonar = AsyncOpenAI(
            api_key=config["sonar_key"],
            base_url="https://api.perplexity.ai"
        )
        self.fallback = AsyncOpenAI(api_key=config.get("anthropic_key", ""))

        self.memory = Memory()
        self.meta_router = MetaRouter(
            config["moonshot_key"], config.get("anthropic_key", "")
        )
        self.sub_engine = SubAgentEngine(config["moonshot_key"])
        self.citation_engine = CitationEngine(
            config["sonar_key"], config["moonshot_key"]
        )
        self.tool_mesh = MCPToolMesh(config["moonshot_key"])
        self.scheduled_tasks: list[dict] = []

    async def process(self, user_message: str) -> str:
        """Main entry point — routes, executes, and returns."""
        # 1. Store in memory
        self.memory.add_turn("user", user_message)

        # 2. Check memory for relevant context
        context = self.memory.search(user_message)

        # 3. Route to optimal mode
        route = self.meta_router.classify(user_message)

        # 4. Execute based on mode
        if route.mode == TaskMode.INSTANT:
            result = await self._instant(user_message, context)
        elif route.mode == TaskMode.THINKING:
            result = await self._thinking(user_message, context)
        elif route.mode == TaskMode.AGENT:
            result = await self._agent(user_message, context)
        elif route.mode == TaskMode.AGENT_SWARM:
            result = await self.sub_engine.run(user_message)
        elif route.mode == TaskMode.FALLBACK:
            result = await self._fallback(user_message, context)

        # 5. Store result and extract durable facts
        self.memory.add_turn("assistant", result)
        await self._extract_and_store_facts(user_message, result)

        return result

    async def _instant(self, msg: str, ctx: list[str]) -> str:
        response = await self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": f"Context: {ctx}"},
                {"role": "user", "content": msg}
            ],
            max_tokens=2048,
            extra_body={"thinking": {"type": "disabled"}}
        )
        return response.choices[0].message.content

    async def _thinking(self, msg: str, ctx: list[str]) -> str:
        response = await self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": f"Context: {ctx}"},
                {"role": "user", "content": msg}
            ],
            max_tokens=8192
        )
        return response.choices[0].message.content

    async def _agent(self, msg: str, ctx: list[str]) -> str:
        """Full agent loop with MCP tools and search grounding."""
        # Check if query needs real-time search grounding
        needs_search = await self._needs_search(msg)
        search_context = ""
        if needs_search:
            grounded = self.citation_engine.query(msg)
            search_context = f"\nSearch Results:\n{grounded.answer}"

        return await self.tool_mesh.agent_loop(
            f"{msg}\n{search_context}\nMemory Context: {ctx}"
        )

    async def _fallback(self, msg: str, ctx: list[str]) -> str:
        """Route to Claude/GPT for edge cases."""
        response = await self.fallback.chat.completions.create(
            model="claude-sonnet-4-20250514",
            messages=[
                {"role": "system", "content": f"Context: {ctx}"},
                {"role": "user", "content": msg}
            ],
            max_tokens=4096
        )
        return response.choices[0].message.content

    async def _needs_search(self, msg: str) -> bool:
        """Quick check if the query needs real-time web data."""
        response = await self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[{
                "role": "user",
                "content": f"Does this need real-time web search? "
                           f"Reply YES or NO only: {msg}"
            }],
            max_tokens=5,
            extra_body={"thinking": {"type": "disabled"}}
        )
        return "YES" in response.choices[0].message.content.upper()

    async def _extract_and_store_facts(self, msg: str, result: str):
        """Extract durable facts from the conversation for memory."""
        response = await self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[{
                "role": "system",
                "content": """Extract durable facts about the user from this
                exchange. Output JSON: {"facts": [{"key": "...", "value": "..."}]}
                Only extract persistent info (name, preferences, projects).
                Return {"facts": []} if none found."""
            }, {
                "role": "user",
                "content": f"User said: {msg}\nAssistant said: {result}"
            }],
            max_tokens=512,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}}
        )
        data = json.loads(response.choices[0].message.content)
        for fact in data.get("facts", []):
            self.memory.store(fact["key"], fact["value"])

    def schedule_task(self, cron_expr: str, task_description: str):
        """Register a recurring background task."""
        # In production: use APScheduler, Celery Beat, or similar
        self.scheduled_tasks.append({
            "cron": cron_expr,
            "task": task_description,
            "created": datetime.utcnow().isoformat()
        })


# ────────────────────────────────────────────
# Usage
# ────────────────────────────────────────────
async def main():
    os = AgentOS({
        "moonshot_key": "your-moonshot-key",
        "sonar_key": "your-perplexity-key",
        "anthropic_key": "your-anthropic-key",  # optional fallback
    })

    # Register MCP tool servers
    os.tool_mesh.register_server(MCPServer(
        name="gmail", command="npx",
        args=["@anthropic/mcp-gmail"],
        env={"GMAIL_TOKEN": "..."}
    ))

    # Process a complex query
    result = await os.process(
        "Research the top 5 open-source LLMs released this month, "
        "compare their benchmarks, and email me a summary"
    )
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Key Design Principles (Lessons from Production)

| Principle | Why It Matters | Source |
|-----------|---------------|--------|
| Limit tool surface to 5-8 per agent | Kimi K2.5 confuses tool selection with too many tools | [Trilogy AI](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25) |
| Use structured tables, not paragraphs, for tool guidance | Tables produce more reliable tool selection than prose | [Trilogy AI](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25) |
| Hybrid model routing with Claude/GPT fallback | Kimi handles 90% of tasks; fallback covers the 10% edge cases | [Trilogy AI](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25) |
| Wrap critical operations in deterministic scripts | Don't let the model touch high-stakes APIs directly | [Trilogy AI](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25) |
| Use Sonar for retrieval, Kimi for synthesis | Cheaper than full Sonar generation; better reasoning with Kimi Thinking | [Perplexity Docs](https://docs.perplexity.ai/docs/sonar/models/sonar-deep-research) |
| Agent Swarm for wide tasks, single agent for deep tasks | Swarm excels at parallelizable research; wastes resources on sequential work | [DataCamp](https://www.datacamp.com/tutorial/kimi-k2-agent-swarm-guide) |
| MCP for tool connectivity | Open standard, model-agnostic, works with any LLM | [Anthropic MCP](https://www.anthropic.com/news/model-context-protocol) |

---

## API Access Points

| Provider | Base URL | Model ID | Best For |
|----------|----------|----------|----------|
| Moonshot (Official) | `https://api.moonshot.ai/v1` | `kimi-k2.5` | Full features, Agent Swarm |
| Together AI | `https://api.together.xyz/v1` | `moonshotai/Kimi-K2.5` | Cost-effective inference |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `moonshotai/kimi-k2.5` | GPU-optimized |
| Perplexity Sonar | `https://api.perplexity.ai` | `sonar-pro` | Search + citation retrieval |
| Claude Code compat | Set `ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic` | `kimi-k2.5` | Drop-in Claude Code replacement |

---

## Sources

- [Codecademy — Kimi K2.5 Complete Guide](https://www.codecademy.com/article/kimi-k-2-5-complete-guide-to-moonshots-ai-model)
- [Trilogy AI — Taming Tool Calling with Kimi K2.5](https://trilogyai.substack.com/p/taming-tool-calling-with-kimi-k25)
- [Moonshot AI — Agent Support Docs](https://platform.moonshot.ai/docs/guide/agent-support.en-US)
- [Together AI — Kimi K2.5 Model Card](https://www.together.ai/models/kimi-k2-5)
- [DataCamp — Agent Swarm Guide](https://www.datacamp.com/tutorial/kimi-k2-agent-swarm-guide)
- [Digital Applied — Perplexity Computer Architecture](https://www.digitalapplied.com/blog/perplexity-computer-multi-model-ai-agent-guide)
- [Forbes — Perplexity Computer](https://www.forbes.com/sites/ronschmelzer/2026/02/27/perplexity-computer-links-ai-agents-to-do-the-work/)
- [Perplexity Docs — Sonar Deep Research](https://docs.perplexity.ai/docs/sonar/models/sonar-deep-research)
- [Geol.ai — Sonar Pro Citation Architecture](https://geol.ai/briefing/perplexitys-sonar-pro-api-advancing-real-time-search-with-enhanced-citation-architecture-comparison)
- [InfoQ — Kimi K2.5 Agent Swarm](https://www.infoq.com/news/2026/02/kimi-k25-swarm/)
- [W&B — MCP Guide](https://wandb.ai/byyoung3/Generative-AI/reports/The-Model-Context-Protocol-MCP-A-guide-for-AI-integration--VmlldzoxMTgzNDgxOQ)
