"""Predefined skills for the agent skill library.

Run:  python -c "from orchestra.code_agent.skills.seed import seed_library; seed_library()"
"""

from orchestra.code_agent.skills.base import Skill, SkillLibrary
from orchestra.code_agent.skills.manager import Embedder
from orchestra.code_agent.skills.v2 import SkillLibraryV2, SkillV2

PREDEFINED_SKILLS = [
    # === Code Reading & Navigation ===
    Skill(body="To understand a new codebase: 1) Read the project README or CLAUDE.md for conventions. "
               "2) Glob the top-level directory structure. 3) Read __init__.py files for public API. "
               "4) Read the main entry point (cli.py, main.py, server.py). 5) Trace one complete "
               "feature flow from entry to completion.",
           tags=["code-reading", "onboarding", "navigation"]),

    Skill(body="To find where a function/class is defined: 1) Use grep with the exact name and "
               "`def ` or `class ` prefix. 2) Read the file to understand the definition context. "
               "3) Check __init__.py exports to confirm it's the public symbol.",
           tags=["code-reading", "search", "grep"]),

    Skill(body="To understand an error traceback: 1) Read the last line first (root cause). "
               "2) Trace upward through the stack to see how the error was reached. "
               "3) Use grep to find the exact line in the source. 4) Check variable values "
               "at that point. 5) Formulate a fix hypothesis before editing.",
           tags=["debugging", "error-reading"]),

    # === Code Modification ===
    Skill(body="To edit a file safely: 1) Read the file first to understand context. "
               "2) Use the edit tool with exact old_string/new_string matching. "
               "3) Re-read the file after edit to verify. 4) Run relevant tests.",
           tags=["editing", "code-modification"]),

    Skill(body="To add a new feature: 1) Find the right file by grep/searching for similar features. "
               "2) Read the surrounding code for patterns. 3) Write the new code following "
               "existing conventions. 4) Export from __init__.py if needed. 5) Add tests. "
               "6) Run existing tests to verify nothing broke.",
           tags=["feature", "code-modification", "development"]),

    Skill(body="To fix a bug: 1) Reproduce the bug with a minimal test case. "
               "2) Use grep to find all related code paths. 3) Add logging or read the logic carefully. "
               "4) Identify the root cause. 5) Make the minimal fix. 6) Add a regression test. "
               "7) Run all tests.",
           tags=["bug-fix", "debugging", "testing"]),

    # === Testing ===
    Skill(body="To add tests for a function: 1) Read the function to understand its contract. "
               "2) Find the test file (same path under tests/). 3) Add test cases covering: "
               "normal case, edge case, error case. 4) Run the specific test file first. "
               "5) Run the full test suite.",
           tags=["testing", "test-generation"]),

    Skill(body="To run tests effectively: 1) Use pytest -x to stop on first failure. "
               "2) Use pytest -k to match specific test names. 3) Use pytest --tb=short "
               "for concise tracebacks. 4) Run tests from the project root. "
               "5) Always run relevant tests after any code change.",
           tags=["testing", "pytest", "verification"]),

    # === Git & Version Control ===
    Skill(body="To commit changes: 1) Run 'git status' to see all changes. "
               "2) Run 'git diff' to review unstaged changes. "
               "3) Run 'git log --oneline -5' to see recent commit style. "
               "4) Add files with 'git add'. 5) Commit with a descriptive message. "
               "6) Verify with 'git status'.",
           tags=["git", "version-control", "committing"]),

    Skill(body="To create a pull request: 1) Create a branch for the change. "
               "2) Make commits on the branch. 3) Push with 'git push -u origin BRANCH'. "
               "4) Use 'gh pr create' with a title and body. 5) Verify the PR URL.",
           tags=["git", "pull-request", "github"]),

    # === Dependency Management ===
    Skill(body="To add a dependency: 1) Understand what the library does and which version is needed. "
               "2) Add to pyproject.toml under [project.dependencies] or [project.optional-dependencies]. "
               "3) Run 'pip install -e .[EXTRA]' to install. 4) Verify the import works. "
               "5) Update any documentation or config files.",
           tags=["dependencies", "pip", "python-packaging"]),

    # === Refactoring ===
    Skill(body="To rename a symbol across the project: 1) Use grep to find ALL occurrences. "
               "2) Categorize: definitions, references, string literals, comments. "
               "3) Rename definitions first (write/edit). 4) Update references. "
               "5) Update __init__.py exports if it's a public symbol. "
               "6) Run tests. 7) Update documentation if needed.",
           tags=["refactoring", "rename", "code-quality"]),

    Skill(body="To extract a function from inline code: 1) Read the code block to extract. "
               "2) Identify inputs (parameters) and outputs (return value). "
               "3) Write the new function with a clear name and docstring. "
               "4) Replace the inline code with a function call. "
               "5) Re-read the calling context to verify it still makes sense.",
           tags=["refactoring", "extract-method", "code-quality"]),

    # === Code Review ===
    Skill(body="To review code changes: 1) Read the diff to understand what changed. "
               "2) Check for: logic errors, edge cases, naming conventions, test coverage. "
               "3) Verify the change matches the stated purpose. "
               "4) Check for security issues (injection, path traversal, secrets). "
               "5) Suggest improvements with specific examples.",
           tags=["code-review", "quality", "verification"]),

    # === Documentation ===
    Skill(body="To write good documentation: 1) Start with the 'what' and 'why' not the 'how'. "
               "2) Include a minimal working example. 3) Document parameters and return values. "
               "4) Add edge cases and error handling notes. 5) Keep it concise — one page max. "
               "6) Link to related documentation.",
           tags=["documentation", "writing", "api-docs"]),

    # === Performance ===
    Skill(body="To debug a performance issue: 1) Measure first — never optimize blind. "
               "2) Use time.perf_counter or cProfile to find bottlenecks. "
               "3) Focus on the hottest path (the code executed most often). "
               "4) Try: caching, vectorization, lazy loading, algorithmic improvement. "
               "5) Re-measure to confirm improvement. 6) Document the trade-off.",
           tags=["performance", "optimization", "profiling"]),

    # === Security ===
    Skill(body="To check for common security issues: 1) Look for hardcoded secrets/keys. "
               "2) Verify all file paths are sanitized (no path traversal). "
               "3) Check shell commands for injection (use subprocess with list args). "
               "4) Validate user inputs before using them. "
               "5) Use parameterized queries for SQL. 6) Set secure defaults.",
           tags=["security", "audit", "best-practices"]),

    # === Project Setup ===
    Skill(body="To set up a Python project: 1) Create pyproject.toml with project metadata. "
               "2) Set up src-layout under src/PROJECT_NAME/. "
               "3) Add __init__.py files to expose the public API. "
               "4) Set up tests/ with pytest configuration. "
               "5) Add CLAUDE.md or AGENTS.md for conventions. "
               "6) Initialize git and make first commit.",
           tags=["project-setup", "python", "scaffolding"]),

    # === Data Analysis ===
    Skill(body="To analyze data: 1) Load the data and check shape, types, missing values. "
               "2) Compute summary statistics (mean, median, std, quartiles). "
               "3) Visualize distributions with histograms or box plots. "
               "4) Check for correlations between key variables. "
               "5) Formulate hypotheses based on patterns. "
               "6) Test hypotheses with statistical tests.",
           tags=["data-analysis", "statistics", "visualization"]),

    # === Debugging with Print ===
    Skill(body="To debug with print statements: 1) Add print() at entry/exit of the suspect function. "
               "2) Print the types and values of key variables. "
               "3) Use f-strings for formatting: f'var={var}'. "
               "4) Add prints inside loops to track iteration progress. "
               "5) Remove all debug prints after fixing.",
           tags=["debugging", "print-debugging", "quick-fix"]),

    # === Web Development ===
    Skill(body="To create a FastAPI endpoint: 1) Define a Pydantic model for the request body. "
               "2) Create an async handler with @app.post/get/etc. "
               "3) Use HTTPException for error responses. "
               "4) Return Pydantic models or dicts (FastAPI serializes automatically). "
               "5) Add the route to the app in the main server file. "
               "6) Test with curl or Invoke-WebRequest.",
           tags=["web", "fastapi", "api-development"]),

    # === Asynchronous Programming ===
    Skill(body="To debug async code: 1) Check if the function is declared with 'async def'. "
               "2) Verify all await calls have proper await syntax. "
               "3) Use asyncio.create_task for fire-and-forget. "
               "4) Use asyncio.wait_for with timeouts to prevent hangs. "
               "5) Check for shared mutable state between tasks. "
               "6) Use an asyncio.Queue for producer-consumer patterns.",
           tags=["async", "asyncio", "concurrency", "debugging"]),
]


def seed_library(clear: bool = False) -> int:
    """Insert predefined skills into the skill library. Returns count added."""
    lib = SkillLibrary()
    embedder = Embedder()
    count = 0
    if clear:
        for s in lib.list_all():
            lib.remove(s.id)
    existing = {s.body[:80] for s in lib.list_all()}
    for skill in PREDEFINED_SKILLS:
        if skill.body[:80] in existing:
            continue
        skill.embedding = embedder.embed(skill.body)
        skill.id = lib.add(skill)
        count += 1
    # Also seed V2 library
    v2_count = 0
    try:
        v2_lib = SkillLibraryV2()
        v2_existing = {s.body[:80] for s in v2_lib.list_all()}
        for skill in PREDEFINED_SKILLS:
            if skill.body[:80] in v2_existing:
                continue
            v2_skill = SkillV2(body=skill.body, tags=skill.tags, embedding=embedder.embed(skill.body))
            v2_skill.id = v2_lib.add(v2_skill)
            v2_count += 1
        v2_total = v2_lib.count()
    except Exception as e:
        print(f"Note: V2 seed skipped ({e})")
        v2_total = 0
    print(f"Seeded {count} skills (V1: {lib.count()}, V2: {v2_total})")
    return count
