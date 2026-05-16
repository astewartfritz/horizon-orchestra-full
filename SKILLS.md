# Orchesta Skills System

The skills system enables the agent to **discover, store, retrieve, and reuse**
procedural knowledge across tasks. It uses reinforcement learning and semantic
search to improve as tasks are completed.

## Architecture

```
Agent Task
  → SkillManager retrieves relevant skills
  → Agent executes with skill context in messages
  → On completion, trajectory is distilled into a new skill
  → Skills are stored in SQLite with semantic embeddings
```

## Database Files

| File | Purpose |
|------|---------|
| `.agent-skills.db` | V1 skill storage (SQLite) |
| `.agent-skills-v2.db` | V2 skill storage with RL metadata |
| `.agent-skills-eval.db` | Evaluation results |
| `.agent-credit.db` | Credit assignment history |

## Skill Data Model

```python
@dataclass
class Skill:
    id: int              # Auto-increment primary key
    body: str            # The procedural steps (3-5 numbered steps)
    tags: list[str]      # Categorization tags
    embedding: list[float]  # 128-dim vector for semantic search
    usage_count: int     # Times used
    success_count: int   # Times resulted in success
    total_reward: float  # Cumulative reward
```

Each skill is stored as a row in SQLite. Search is done via cosine similarity
on the embedding vector.

## Embedding

The `Embedder` class supports three modes, auto-selected based on availability:

| Mode | Provider | Requirement | Quality |
|------|----------|-------------|---------|
| **hash** (default, CPU) | MD5 word hashing | None | Low |
| **sentence-transformers** (GPU) | `all-MiniLM-L6-v2` | `pip install sentence-transformers` + GPU | High |
| **transformers** (GPU fallback) | HuggingFace model | `pip install transformers` + GPU | High |

Set `EMBEDDING_PROVIDER=sentence-transformers` and optionally
`EMBEDDING_MODEL=all-MiniLM-L6-v2` in your environment.

## CLI Commands

### V1 Skills

```bash
# List all skills
code-agent skill list

# Show a skill by ID
code-agent skill show 1

# Search skills semantically
code-agent skill search "refactor code"

# Add a skill manually
code-agent skill add --body "1. Read the file first. 2. Make changes. 3. Verify." --tags "editing,verification"

# Remove a skill
code-agent skill remove 5

# Seed library with 20+ predefined skills
code-agent skill seed

# View credit signals
code-agent skill credit
```

### V2 Skills (RL-based meta-policy)

```bash
# Run a full 4-phase episode (query → rerank → act → distill)
code-agent skillv2 episode "Refactor this function" --provider ollama

# Benchmark skills against eval set
code-agent skillv2 benchmark

# Train RL policy
code-agent skillv2 train

# Show skill library statistics
code-agent skillv2 stats

# List skills (V2 library)
code-agent skillv2 list
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/skillsv2/stats` | Library stats |
| GET | `/api/skillsv2/list?limit=50` | List skills |
| POST | `/api/skillsv2/seed` | Seed 20+ predefined skills |
| POST | `/api/skillsv2/prune` | Remove low-performers |
| DELETE | `/api/skillsv2/skill/{id}` | Remove a skill |

## The 4-Phase V2 Episode Lifecycle

```
Phase 1: QUERY    → LLM generates a search query from the task
Phase 2: RERANK   → LLM selects best skill from candidates
Phase 3: ACT      → Agent uses the skill to perform the task
Phase 4: DISTILL  → LLM creates improved skill from the trajectory
```

Each episode records credit signals:
- **Selection** — how well the skill selection policy performs
- **Utilization** — immediate task reward
- **Distillation** — how much the skill improved from the experience

## Predefined Skills

Run `code-agent skill seed` to populate the library with 20+ predefined skills:

1. Understanding a new codebase
2. Finding a function/class definition
3. Debugging error tracebacks
4. Editing files safely
5. Adding a new feature
6. Fixing a bug
7. Adding tests
8. Running tests effectively
9. Committing changes
10. Creating pull requests
11. Adding dependencies
12. Renaming symbols
13. Extracting functions
14. Reviewing code
15. Writing documentation
16. Debugging performance
17. Security auditing
18. Project setup
19. Data analysis
20. Debugging async code
21. Creating FastAPI endpoints
22. Debugging with print statements

## GPU Enablement

When an NVIDIA GPU is detected:

1. **Embeddings** switch from hash-based to `sentence-transformers` (set
   `EMBEDDING_PROVIDER=sentence-transformers` to enable).
2. **Skill distillation** runs faster (LLM inference on GPU).
3. **Agent main loop** re-enables (tool-calling with fast inference).
4. **Evaluation** runs meaningful benchmarks (eval steps complete quickly).

## Metrics & Observability

- `/api/metrics` — Prometheus metrics including `llm_calls_total`,
  `llm_tokens_total`, `tool_calls_total` labeled by provider/model/tool.
- `/observability` — Live dashboard auto-refreshing every 5 seconds.
- `/api/langfuse` — LangFuse LLM observability (when configured).
