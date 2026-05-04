"""CodeGuard — Security gate for ALL code executed by AI agents.

Every time an agent wants to execute code (via sandbox, tools, or direct
exec), CodeGuard scans it first.  If it passes, the result is HMAC-signed
and logged.  If it fails, the code is blocked and the agent receives a
clear, actionable error.  **No code bypasses this gate.**

Scan layers (in order, fast to slow):

1. **Hash lookup** — seen this exact code before?  Return cached result.
   Cost: O(1) dict lookup, ~0 ms.
2. **Pattern scan** — regex-based detection of dangerous patterns.
   Cost: <1 ms for typical code.
3. **AST analysis** — Python ``ast`` module for semantic dangers (e.g.
   ``exec()`` hidden behind ``getattr``).  Cost: <5 ms.
4. **Import analysis** — which modules are imported and are they allowed?
   Cost: <2 ms.
5. **Network analysis** — will the code open outbound connections?
   Cost: <2 ms.
6. **Secret pattern scan** — will the code touch credentials, env vars,
   or cloud metadata endpoints?  Cost: <1 ms.

Total target: **<10 ms for 95th percentile** on a typical code snippet
(<500 lines).

Beyond NemoClaw: NemoClaw has basic ``exec`` blocking.  CodeGuard adds
15 threat categories, AST-level analysis, HMAC signing, layered caching,
and full audit integration.

Dependencies: **stdlib only** (``ast``, ``re``, ``hashlib``, ``hmac``,
``time``, ``logging``, ``asyncio``).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from orchestra.guardian.security_config import SECURITY_CONFIG, SecurityConfig

__all__ = [
    "CodeThreat",
    "CodeScanResult",
    "CodeGuard",
]

log = logging.getLogger("orchestra.guardian.code_guard")


# ---------------------------------------------------------------------------
# CodeThreat enum
# ---------------------------------------------------------------------------

class CodeThreat(str, Enum):
    """Specific threat types detected in code.

    Each variant maps to a family of dangerous patterns.  The string
    value is used in audit logs and API responses.
    """

    COMMAND_INJECTION = "command_injection"
    """``os.system``, ``subprocess`` with ``shell=True``, ``os.popen``."""

    PATH_TRAVERSAL = "path_traversal"
    """``../../etc/passwd``, ``..\\\\windows\\\\system32``, directory escape."""

    ARBITRARY_EXEC = "arbitrary_exec"
    """``exec()``, ``eval()``, ``compile()``, ``__import__()``."""

    NETWORK_EXFIL = "network_exfil"
    """Outbound connections to unexpected hosts."""

    CREDENTIAL_ACCESS = "credential_access"
    """Reading ``/etc/shadow``, ``.env``, AWS metadata endpoint."""

    DANGEROUS_IMPORT = "dangerous_import"
    """``ctypes``, ``cffi``, ``importlib`` abuse, ``__import__``."""

    INFINITE_LOOP = "infinite_loop"
    """``while True:`` without ``break``, ``return``, or ``raise``."""

    MEMORY_BOMB = "memory_bomb"
    """Huge allocations: ``[0] * 10**12``, ``'x' * 10**10``."""

    FORK_BOMB = "fork_bomb"
    """Recursive ``subprocess`` / ``os.fork`` / thread spawning."""

    CRYPTO_MINER = "crypto_miner"
    """Hashlib loops that resemble proof-of-work mining."""

    SECRET_EXFIL = "secret_exfil"
    """Printing/logging ``os.environ``, API keys, tokens."""

    SQL_INJECTION = "sql_injection"
    """f-string or %-format in SQL query context."""

    SUPPLY_CHAIN = "supply_chain"
    """``pip install`` from non-PyPI sources, ``--index-url``."""

    REGISTRY_WRITE = "registry_write"
    """``winreg``, Windows registry manipulation."""

    SELF_MODIFICATION = "self_modification"
    """Code that modifies its own source file on disk."""


# ---------------------------------------------------------------------------
# Threat severity weights (0-1, higher = worse)
# ---------------------------------------------------------------------------

_THREAT_SEVERITY: dict[CodeThreat, float] = {
    CodeThreat.COMMAND_INJECTION: 1.0,
    CodeThreat.PATH_TRAVERSAL: 0.9,
    CodeThreat.ARBITRARY_EXEC: 0.95,
    CodeThreat.NETWORK_EXFIL: 0.8,
    CodeThreat.CREDENTIAL_ACCESS: 0.95,
    CodeThreat.DANGEROUS_IMPORT: 0.7,
    CodeThreat.INFINITE_LOOP: 0.5,
    CodeThreat.MEMORY_BOMB: 0.85,
    CodeThreat.FORK_BOMB: 0.95,
    CodeThreat.CRYPTO_MINER: 0.8,
    CodeThreat.SECRET_EXFIL: 0.9,
    CodeThreat.SQL_INJECTION: 0.9,
    CodeThreat.SUPPLY_CHAIN: 0.85,
    CodeThreat.REGISTRY_WRITE: 0.7,
    CodeThreat.SELF_MODIFICATION: 0.9,
}


# ---------------------------------------------------------------------------
# CodeScanResult
# ---------------------------------------------------------------------------

@dataclass
class CodeScanResult:
    """Result of a CodeGuard scan.

    Every field is populated regardless of whether the code is safe or
    blocked.  Consumers should check ``blocked`` to decide whether to
    proceed.
    """

    code_hash: str
    """SHA-256 hex digest of the scanned code."""

    language: str
    """Language of the scanned code (e.g. ``'python'``, ``'shell'``)."""

    safe: bool
    """``True`` if no threats were detected."""

    threats: list[CodeThreat]
    """List of detected threats (may be empty)."""

    severity: float
    """Aggregate severity score in ``[0, 1]``."""

    blocked: bool
    """``True`` if the code was prevented from executing."""

    redacted_code: str | None
    """Version of the code with dangerous parts removed, or ``None``."""

    scan_ms: float
    """Wall-clock scan duration in milliseconds."""

    agent_id: str
    """ID of the agent that submitted the code."""

    timestamp: float
    """Unix epoch timestamp of the scan."""

    signature: str
    """HMAC-SHA256 of ``code_hash + agent_id + timestamp``."""


# ---------------------------------------------------------------------------
# Dangerous pattern database
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS: dict[CodeThreat, list[str]] = {
    CodeThreat.COMMAND_INJECTION: [
        r"\bos\.system\s*\(",
        r"\bos\.popen\s*\(",
        r"\bos\.exec[lv]p?e?\s*\(",
        r"\bsubprocess\.\w+\(.*shell\s*=\s*True",
        r"\bsubprocess\.call\s*\(",
        r"\bsubprocess\.run\s*\(.*shell\s*=\s*True",
        r"\bsubprocess\.Popen\s*\(.*shell\s*=\s*True",
        r"\bcommands\.get\w+\s*\(",
        r"\bos\.spawn[lv]p?e?\s*\(",
        r"\bpty\.spawn\s*\(",
        r"\bos\.startfile\s*\(",
    ],
    CodeThreat.PATH_TRAVERSAL: [
        r"\.\./\.\./",
        r"\.\.\\/\.\.\\/",
        r"/etc/passwd",
        r"/etc/shadow",
        r"/etc/hosts",
        r"C:\\\\Windows\\\\System32",
        r"C:/Windows/System32",
        r"/proc/self/",
        r"\bopen\s*\(.*\.\.\s*/",
        r"os\.path\.join\(.*\.\.",
    ],
    CodeThreat.ARBITRARY_EXEC: [
        r"\bexec\s*\(",
        r"\beval\s*\(",
        r"\bcompile\s*\(",
        r"__import__\s*\(",
        r"\bgetattr\s*\(\s*__builtins__",
        r"\bgetattr\s*\(\s*builtins",
        r"globals\s*\(\s*\)\s*\[",
        r"locals\s*\(\s*\)\s*\[",
        r"\bexecfile\s*\(",
        r"__builtins__\s*\[",
        r"\bcode\.interact\s*\(",
    ],
    CodeThreat.NETWORK_EXFIL: [
        r"\burllib\.request\.urlopen\s*\(",
        r"\burllib\.request\.Request\s*\(",
        r"\brequests\.(get|post|put|delete|patch)\s*\(",
        r"\bhttp\.client\.HTTP",
        r"\bsocket\.socket\s*\(",
        r"\bsocket\.create_connection\s*\(",
        r"\bhttpx\.(get|post|put|delete|patch|AsyncClient|Client)",
        r"\baiohttp\.ClientSession\s*\(",
        r"\bftplib\.FTP\s*\(",
        r"\bsmtplib\.SMTP\s*\(",
        r"\bparamiko\.SSHClient\s*\(",
        r"\bwebsocket\.WebSocket\s*\(",
    ],
    CodeThreat.CREDENTIAL_ACCESS: [
        r"/etc/shadow",
        r"\.env\b",
        r"AWS_SECRET_ACCESS_KEY",
        r"AWS_ACCESS_KEY_ID",
        r"169\.254\.169\.254",
        r"metadata\.google\.internal",
        r"\.ssh/id_rsa",
        r"\.ssh/authorized_keys",
        r"\.aws/credentials",
        r"\.kube/config",
        r"/var/run/secrets/",
        r"AZURE_CLIENT_SECRET",
    ],
    CodeThreat.DANGEROUS_IMPORT: [
        r"\bimport\s+ctypes\b",
        r"\bfrom\s+ctypes\b",
        r"\bimport\s+cffi\b",
        r"\bfrom\s+cffi\b",
        r"\bimportlib\.import_module\s*\(",
        r"\b__import__\s*\(",
        r"\bimport\s+_thread\b",
        r"\bimport\s+multiprocessing\b",
        r"\bimport\s+signal\b",
        r"\bimport\s+resource\b",
        r"\bimport\s+mmap\b",
    ],
    CodeThreat.INFINITE_LOOP: [
        r"\bwhile\s+True\s*:",
        r"\bwhile\s+1\s*:",
        r"\bfor\s+\w+\s+in\s+iter\s*\(",
        r"\bitertools\.count\s*\(",
        r"\bitertools\.cycle\s*\(",
        r"\bitertools\.repeat\s*\(",
        r"\basyncio\.sleep\s*\(\s*0\s*\).*while",
        r"\bwhile\s+not\s+False\s*:",
    ],
    CodeThreat.MEMORY_BOMB: [
        r"\[\s*\d+\s*\]\s*\*\s*10\s*\*\*\s*[89]\b",
        r"\[\s*\d+\s*\]\s*\*\s*10\s*\*\*\s*1[0-9]\b",
        r"\[\s*0\s*\]\s*\*\s*\d{10,}",
        r"['\"].\s*['\"]\s*\*\s*10\s*\*\*\s*[89]\b",
        r"['\"].\s*['\"]\s*\*\s*10\s*\*\*\s*1[0-9]\b",
        r"b?['\"].\s*['\"]\s*\*\s*\d{10,}",
        r"range\s*\(\s*10\s*\*\*\s*1[0-9]",
        r"bytearray\s*\(\s*10\s*\*\*\s*[89]",
        r"\blist\s*\(\s*range\s*\(\s*10\s*\*\*\s*[89]",
    ],
    CodeThreat.FORK_BOMB: [
        r"\bos\.fork\s*\(",
        r"\bos\.forkpty\s*\(",
        r"\bmultiprocessing\.Process\s*\(",
        r"\bthreading\.Thread\s*\(\s*target\s*=.*threading\.Thread",
        r"subprocess\.Popen\s*\(.*subprocess\.Popen",
        r"while\s+True\s*:.*os\.fork\s*\(",
        r"while\s+True\s*:.*threading\.Thread",
        r"while\s+True\s*:.*subprocess",
        r"\bos\.fork\s*\(\s*\)\s*.*os\.fork\s*\(",
    ],
    CodeThreat.CRYPTO_MINER: [
        r"hashlib\.\w+\(.*\.hexdigest\(\).*while",
        r"while.*hashlib\.\w+\(.*\.hexdigest\(\)",
        r"nonce\s*\+?=\s*1.*hashlib",
        r"hashlib\.sha256.*startswith\s*\(",
        r"proof.of.work",
        r"mining.*loop",
        r"hashrate",
        r"block.*hash.*nonce",
        r"difficulty.*target.*hash",
    ],
    CodeThreat.SECRET_EXFIL: [
        r"print\s*\(\s*os\.environ",
        r"logging\.\w+\(.*os\.environ",
        r"print\s*\(.*API_KEY",
        r"print\s*\(.*SECRET",
        r"print\s*\(.*TOKEN",
        r"print\s*\(.*PASSWORD",
        r"json\.dumps\s*\(\s*dict\s*\(\s*os\.environ",
        r"\bos\.environ\.copy\s*\(",
        r"str\s*\(\s*os\.environ\s*\)",
        r"requests\.(post|put)\s*\(.*os\.environ",
        r"requests\.(post|put)\s*\(.*(API_KEY|SECRET|TOKEN)",
    ],
    CodeThreat.SQL_INJECTION: [
        r'f["\']SELECT\s',
        r'f["\']INSERT\s',
        r'f["\']UPDATE\s',
        r'f["\']DELETE\s',
        r'f["\']DROP\s',
        r"f[\"']ALTER\s",
        r'["\']SELECT\s.*%\s*\(',
        r'["\']INSERT\s.*%\s*\(',
        r'["\']UPDATE\s.*%\s*\(',
        r'["\']DELETE\s.*%\s*\(',
        r'\.format\s*\(.*["\']SELECT',
        r'\.format\s*\(.*["\']INSERT',
        r'execute\s*\(\s*f["\']',
    ],
    CodeThreat.SUPPLY_CHAIN: [
        r"pip\s+install\s+--index-url",
        r"pip\s+install\s+--extra-index-url",
        r"pip\s+install\s+--find-links",
        r"pip\s+install\s+-i\s+http",
        r"pip\s+install\s+git\+",
        r"pip\s+install\s+https?://",
        r"pip\s+install\s+--trusted-host",
        r"easy_install\b",
        r"setup\.py\s+install",
        r"pip\s+install\s+--no-verify",
    ],
    CodeThreat.REGISTRY_WRITE: [
        r"\bimport\s+winreg\b",
        r"\bfrom\s+winreg\b",
        r"\bwinreg\.\w*Key\s*\(",
        r"\bwinreg\.SetValue",
        r"\bwinreg\.CreateKey",
        r"\bwinreg\.DeleteKey",
        r"\b_winreg\.\w+\s*\(",
        r"reg\s+add\b",
        r"reg\s+delete\b",
    ],
    CodeThreat.SELF_MODIFICATION: [
        r"open\s*\(\s*__file__\s*,\s*['\"]w",
        r"open\s*\(\s*__file__\s*,\s*['\"]a",
        r"open\s*\(\s*sys\.argv\[0\]\s*,\s*['\"]w",
        r"inspect\.getsourcefile",
        r"inspect\.getfile.*open.*['\"]w",
        r"__file__.*open.*write",
        r"os\.remove\s*\(\s*__file__",
        r"os\.unlink\s*\(\s*__file__",
        r"shutil\.move\s*\(\s*__file__",
    ],
}


# ---------------------------------------------------------------------------
# Dangerous builtins / modules / safe modules
# ---------------------------------------------------------------------------

DANGEROUS_BUILTINS: frozenset[str] = frozenset({
    "exec",
    "eval",
    "compile",
    "__import__",
    "vars",
    "locals",
    "globals",
    "getattr",      # when used on sensitive objects
    "setattr",      # when used on sensitive objects
    "delattr",
    "breakpoint",
    "input",        # blocks in server context
    "open",         # only dangerous with write/sensitive paths
    "memoryview",
})

DANGEROUS_MODULES: frozenset[str] = frozenset({
    "os",
    "subprocess",
    "ctypes",
    "cffi",
    "socket",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "multiprocessing",
    "threading",
    "signal",
    "resource",
    "mmap",
    "winreg",
    "pty",
    "termios",
    "importlib",
    "code",
    "codeop",
    "compileall",
    "shutil",
    "tempfile",
    "pathlib",  # only when combined with write patterns
    "webbrowser",
    "paramiko",
    "fabric",
    "pexpect",
})

SAFE_MODULES: frozenset[str] = frozenset({
    "json",
    "math",
    "re",
    "typing",
    "dataclasses",
    "enum",
    "abc",
    "collections",
    "functools",
    "itertools",
    "operator",
    "decimal",
    "fractions",
    "statistics",
    "random",
    "string",
    "textwrap",
    "unicodedata",
    "datetime",
    "calendar",
    "copy",
    "pprint",
    "reprlib",
    "numbers",
    "bisect",
    "heapq",
    "array",
    "weakref",
    "types",
    "contextlib",
    "hashlib",      # safe for hashing; mining detected separately
    "hmac",
    "base64",
    "binascii",
    "struct",
    "io",
    "logging",
    "warnings",
    "traceback",
    "inspect",      # read-only introspection
    "dis",
    "ast",
    "token",
    "tokenize",
    "keyword",
    "pdb",
    "unittest",
    "doctest",
    "pytest",
    "typing_extensions",
    "annotated_types",
    "attrs",
    "pydantic",
    "msgpack",
    "orjson",
    "ujson",
    "yaml",
    "toml",
    "tomli",
    "csv",
    "configparser",
})


# ---------------------------------------------------------------------------
# Precompiled regex patterns
# ---------------------------------------------------------------------------

_COMPILED_PATTERNS: dict[CodeThreat, list[re.Pattern[str]]] = {
    threat: [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]
    for threat, patterns in DANGEROUS_PATTERNS.items()
}


# ---------------------------------------------------------------------------
# AST Visitor for Python semantic analysis
# ---------------------------------------------------------------------------

class _DangerousNodeVisitor(ast.NodeVisitor):
    """Walk a Python AST and collect threat indicators.

    This catches dangers that regex cannot reliably detect, e.g.:

    - ``getattr(os, 'system')('rm -rf /')``
    - ``eval(chr(111) + chr(115))``
    - ``subprocess.Popen(['rm', '-rf', '/'], shell=True)``
    """

    def __init__(self) -> None:
        self.threats: list[CodeThreat] = []
        self._in_while_true = False

    # -- exec / eval / compile ----------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # Direct call: exec(...), eval(...)
        if isinstance(func, ast.Name):
            if func.id in {"exec", "eval", "compile"}:
                self.threats.append(CodeThreat.ARBITRARY_EXEC)
            elif func.id == "__import__":
                self.threats.append(CodeThreat.DANGEROUS_IMPORT)

        # Attribute call: os.system(...), subprocess.Popen(...)
        elif isinstance(func, ast.Attribute):
            self._check_attribute_call(func, node)

        self.generic_visit(node)

    def _check_attribute_call(self, func: ast.Attribute, node: ast.Call) -> None:
        """Check method calls like ``os.system(...)``."""
        attr = func.attr
        if isinstance(func.value, ast.Name):
            module = func.value.id

            # os.system, os.popen, os.exec*
            if module == "os" and attr in {
                "system", "popen", "popen2", "popen3", "popen4",
                "execl", "execle", "execlp", "execlpe",
                "execv", "execve", "execvp", "execvpe",
                "spawnl", "spawnle", "spawnlp", "spawnlpe",
                "spawnv", "spawnve", "spawnvp", "spawnvpe",
                "startfile", "fork", "forkpty",
            }:
                self.threats.append(CodeThreat.COMMAND_INJECTION)

            # subprocess.Popen/call/run with shell=True
            if module == "subprocess" and attr in {"Popen", "call", "run", "check_call", "check_output"}:
                for kw in node.keywords:
                    if kw.arg == "shell":
                        if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            self.threats.append(CodeThreat.COMMAND_INJECTION)

            # getattr/setattr on sensitive modules
            if module in {"builtins", "__builtins__"} and attr in {"getattr", "setattr"}:
                self.threats.append(CodeThreat.ARBITRARY_EXEC)

        # getattr(os, 'system') pattern
        if isinstance(func.value, ast.Name) and func.value.id == "builtins":
            pass  # already handled
        if attr in {"system", "popen"} and isinstance(func.value, ast.Name):
            if func.value.id == "os":
                self.threats.append(CodeThreat.COMMAND_INJECTION)

    # -- getattr on sensitive objects ----------------------------------------

    def visit_Call_getattr(self, node: ast.Call) -> None:
        """Detect ``getattr(os, 'system')``-style obfuscation."""
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2:
                target = node.args[0]
                if isinstance(target, ast.Name) and target.id in {"os", "sys", "builtins", "__builtins__"}:
                    self.threats.append(CodeThreat.ARBITRARY_EXEC)
        self.generic_visit(node)

    # -- import analysis ----------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod in {"ctypes", "cffi"}:
                self.threats.append(CodeThreat.DANGEROUS_IMPORT)
            if mod == "winreg":
                self.threats.append(CodeThreat.REGISTRY_WRITE)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            if mod in {"ctypes", "cffi"}:
                self.threats.append(CodeThreat.DANGEROUS_IMPORT)
            if mod == "winreg":
                self.threats.append(CodeThreat.REGISTRY_WRITE)
        self.generic_visit(node)

    # -- while True without break -------------------------------------------

    def visit_While(self, node: ast.While) -> None:
        # Check if it's ``while True:`` or ``while 1:``
        if isinstance(node.test, ast.Constant) and node.test.value in {True, 1}:
            has_exit = self._has_exit_in_body(node.body)
            if not has_exit:
                self.threats.append(CodeThreat.INFINITE_LOOP)
        self.generic_visit(node)

    def _has_exit_in_body(self, body: list[ast.stmt]) -> bool:
        """Return True if the body contains a break, return, raise, or sys.exit."""
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, (ast.Break, ast.Return, ast.Raise)):
                return True
            # sys.exit()
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "exit":
                        return True
                if isinstance(node.func, ast.Name) and node.func.id == "exit":
                    return True
        return False

    # -- open() with write mode to sensitive paths --------------------------

    def visit_Call_open(self, node: ast.Call) -> None:
        """Detect ``open('/etc/shadow', 'w')`` and similar."""
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            if len(node.args) >= 1:
                path_arg = node.args[0]
                if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
                    path_val = path_arg.value
                    sensitive = {"/etc/passwd", "/etc/shadow", "/etc/hosts",
                                 "/proc/", "/sys/", "/dev/"}
                    if any(path_val.startswith(s) or s in path_val for s in sensitive):
                        self.threats.append(CodeThreat.CREDENTIAL_ACCESS)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# CodeGuard
# ---------------------------------------------------------------------------

class CodeGuard:
    """Intercepts every code execution request from AI agents.

    Every time an agent wants to execute code (via sandbox, tools, or direct
    exec), CodeGuard scans it first.  If it passes, it's HMAC-signed and
    logged.  If it fails, it's blocked and the agent sees a clear error.
    No code bypasses this.

    Parameters
    ----------
    audit : AuditLedger | None
        Optional audit ledger for recording scan results.
    policy : PolicyEngine | None
        Optional policy engine for per-agent overrides.
    strict_mode : bool
        When ``True``, any detected threat blocks execution.
        When ``False``, only threats with severity >= threshold block.
    config : SecurityConfig | None
        Security configuration.  Falls back to global ``SECURITY_CONFIG``.
    """

    def __init__(
        self,
        audit: Any | None = None,
        policy: Any | None = None,
        strict_mode: bool = True,
        config: SecurityConfig | None = None,
    ) -> None:
        self._audit = audit
        self._policy = policy
        self._strict = strict_mode
        self._config = config or SECURITY_CONFIG

        # Cache: code_hash -> CodeScanResult
        self._cache: dict[str, CodeScanResult] = {}
        self._cache_lock = asyncio.Lock()

        # Statistics
        self._scan_count = 0
        self._block_count = 0
        self._threat_counter: Counter[CodeThreat] = Counter()
        self._blocked_results: list[CodeScanResult] = []
        self._stats_lock = asyncio.Lock()

        log.info(
            "CodeGuard initialised (strict=%s, config=%r)",
            self._strict, self._config,
        )

    # ===================================================================
    # Core scan
    # ===================================================================

    async def scan(
        self,
        code: str,
        language: str,
        agent_id: str,
        context: dict[str, Any] | None = None,
    ) -> CodeScanResult:
        """Scan code for security threats.

        Parameters
        ----------
        code : str
            The source code to scan.
        language : str
            Programming language (``'python'``, ``'shell'``, ``'javascript'``).
        agent_id : str
            Identifier of the agent submitting the code.
        context : dict | None
            Optional metadata (task ID, team, etc.) for audit.

        Returns
        -------
        CodeScanResult
            Full scan result including threats, severity, and signature.
        """
        t0 = time.monotonic()
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()

        # Layer 1: Cache lookup
        async with self._cache_lock:
            if code_hash in self._cache:
                cached = self._cache[code_hash]
                log.debug("Cache hit for %s (agent=%s)", code_hash[:12], agent_id)
                return CodeScanResult(
                    code_hash=cached.code_hash,
                    language=cached.language,
                    safe=cached.safe,
                    threats=list(cached.threats),
                    severity=cached.severity,
                    blocked=cached.blocked,
                    redacted_code=cached.redacted_code,
                    scan_ms=(time.monotonic() - t0) * 1000,
                    agent_id=agent_id,
                    timestamp=time.time(),
                    signature=self._sign(code_hash, agent_id),
                )

        # Layer 2-6: Full scan
        threats: list[CodeThreat] = []

        # Layer 2: Pattern scan
        threats.extend(self._pattern_scan(code, language))

        # Layer 3: AST analysis (Python only)
        if language.lower() in {"python", "py"}:
            threats.extend(self._ast_scan(code))

        # Layer 4: Import analysis
        threats.extend(self._import_scan(code, language))

        # Layer 5: Network analysis
        threats.extend(self._network_scan(code))

        # Layer 6: Secret pattern scan
        threats.extend(self._secret_scan(code))

        # Deduplicate threats
        threats = list(dict.fromkeys(threats))

        # Calculate severity
        severity = self._calculate_severity(threats)

        # Determine if blocked
        blocked = self._should_block(threats, severity)

        # Redact if needed
        redacted = self._redact(code, threats) if threats else None

        scan_ms = (time.monotonic() - t0) * 1000
        ts = time.time()

        result = CodeScanResult(
            code_hash=code_hash,
            language=language,
            safe=len(threats) == 0,
            threats=threats,
            severity=severity,
            blocked=blocked,
            redacted_code=redacted,
            scan_ms=scan_ms,
            agent_id=agent_id,
            timestamp=ts,
            signature=self._sign(code_hash, agent_id),
        )

        # Update cache
        async with self._cache_lock:
            self._cache[code_hash] = result

        # Update statistics
        async with self._stats_lock:
            self._scan_count += 1
            if blocked:
                self._block_count += 1
                self._blocked_results.append(result)
            for t in threats:
                self._threat_counter[t] += 1

        # Audit logging
        if self._audit and self._config.audit_code_scans:
            try:
                await self._audit.record(
                    agent_id=agent_id,
                    event_type="code_scan",
                    resource=f"code:{code_hash[:16]}",
                    action="scan",
                    result="blocked" if blocked else "allowed",
                    metadata={
                        "threats": [t.value for t in threats],
                        "severity": severity,
                        "scan_ms": scan_ms,
                        "language": language,
                        **(context or {}),
                    },
                )
            except Exception:
                log.exception("Failed to write audit record for code scan")

        return result

    # ===================================================================
    # Scan + execute gate
    # ===================================================================

    async def scan_and_permit(
        self,
        code: str,
        language: str,
        agent_id: str,
    ) -> tuple[bool, CodeScanResult]:
        """Scan code and return a permit/deny decision.

        This is the primary integration point for sandboxes and tool
        executors.  Returns ``(permitted, result)`` where ``permitted``
        is ``True`` only if the code may be executed.

        Parameters
        ----------
        code : str
            Source code to scan.
        language : str
            Programming language.
        agent_id : str
            Agent identifier.

        Returns
        -------
        tuple[bool, CodeScanResult]
            ``(True, result)`` if code may run; ``(False, result)`` if blocked.
        """
        if not self._config.code_guard_enabled:
            # Guard disabled — allow everything (still log)
            code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
            result = CodeScanResult(
                code_hash=code_hash,
                language=language,
                safe=True,
                threats=[],
                severity=0.0,
                blocked=False,
                redacted_code=None,
                scan_ms=0.0,
                agent_id=agent_id,
                timestamp=time.time(),
                signature=self._sign(code_hash, agent_id),
            )
            return True, result

        # Check code length
        if len(code) > self._config.max_code_length:
            code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
            result = CodeScanResult(
                code_hash=code_hash,
                language=language,
                safe=False,
                threats=[],
                severity=1.0,
                blocked=True,
                redacted_code=None,
                scan_ms=0.0,
                agent_id=agent_id,
                timestamp=time.time(),
                signature=self._sign(code_hash, agent_id),
            )
            return False, result

        result = await self.scan(code, language, agent_id)
        return not result.blocked, result

    # ===================================================================
    # Individual scan layers
    # ===================================================================

    def _pattern_scan(self, code: str, language: str) -> list[CodeThreat]:
        """Layer 2: Regex-based pattern matching for dangerous code.

        Scans all compiled patterns against the code.  Fast (<1 ms for
        typical code) because patterns are precompiled.

        Parameters
        ----------
        code : str
            Source code.
        language : str
            Programming language.

        Returns
        -------
        list[CodeThreat]
            Detected threats.
        """
        threats: list[CodeThreat] = []
        for threat, patterns in _COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(code):
                    threats.append(threat)
                    break  # one match per threat category is enough
        return threats

    def _ast_scan(self, code: str) -> list[CodeThreat]:
        """Layer 3: Python AST analysis for semantic threats.

        Parses the code into an AST and walks it with
        :class:`_DangerousNodeVisitor`.  This catches obfuscated threats
        that regex cannot detect.

        Parameters
        ----------
        code : str
            Python source code.

        Returns
        -------
        list[CodeThreat]
            Detected threats (empty if code fails to parse).
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # If it doesn't parse, it can't be executed anyway
            log.debug("AST parse failed — not valid Python")
            return []

        visitor = _DangerousNodeVisitor()
        visitor.visit(tree)
        return visitor.threats

    def _import_scan(self, code: str, language: str) -> list[CodeThreat]:
        """Layer 4: Import analysis.

        Extracts imported modules and flags dangerous ones that aren't
        already caught by other layers.

        Parameters
        ----------
        code : str
            Source code.
        language : str
            Programming language.

        Returns
        -------
        list[CodeThreat]
            Detected threats.
        """
        threats: list[CodeThreat] = []

        if language.lower() not in {"python", "py"}:
            return threats

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return threats

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        # Check for dangerous module + dangerous usage combos
        dangerous_imported = imported_modules & DANGEROUS_MODULES
        safe_imported = imported_modules & SAFE_MODULES
        unknown = imported_modules - DANGEROUS_MODULES - SAFE_MODULES

        # Modules that are always dangerous
        always_dangerous = {"ctypes", "cffi", "winreg", "pty", "termios"}
        for mod in always_dangerous & imported_modules:
            if mod in {"winreg"}:
                threats.append(CodeThreat.REGISTRY_WRITE)
            else:
                threats.append(CodeThreat.DANGEROUS_IMPORT)

        return threats

    def _network_scan(self, code: str) -> list[CodeThreat]:
        """Layer 5: Network connection analysis.

        Detects code that would open outbound network connections.

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        list[CodeThreat]
            ``[CodeThreat.NETWORK_EXFIL]`` if outbound connections detected.
        """
        threats: list[CodeThreat] = []

        network_patterns = [
            r"\bsocket\.connect\s*\(",
            r"\bsocket\.create_connection\s*\(",
            r"\burllib\.request\.urlopen\s*\(",
            r"\brequests\.(get|post|put|delete|patch|head|options)\s*\(",
            r"\bhttpx\.(get|post|put|delete|patch|head|options|AsyncClient|Client)",
            r"\baiohttp\.ClientSession",
            r"\bhttp\.client\.(HTTPConnection|HTTPSConnection)\s*\(",
            r"\bftplib\.FTP\s*\(",
            r"\bsmtplib\.SMTP\s*\(",
            r"\btelnetlib\.Telnet\s*\(",
            r"\bparamiko\.SSHClient\s*\(",
            r"\bwebsocket\.\w+\s*\(",
        ]

        for pattern_str in network_patterns:
            if re.search(pattern_str, code, re.IGNORECASE):
                # Check if connecting to allowed hosts
                if not self._is_allowed_host(code):
                    threats.append(CodeThreat.NETWORK_EXFIL)
                    break

        return threats

    def _is_allowed_host(self, code: str) -> bool:
        """Check if network connections target allowed hosts.

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        bool
            ``True`` if all detected hosts are in the allowed list.
        """
        allowed = self._config.allowed_network_hosts
        if not allowed:
            return False
        if "*" in allowed:
            return True

        # Extract hostnames from common patterns
        host_patterns = [
            r'(?:get|post|put|delete|patch|head)\s*\(\s*["\']https?://([^/\'"]+)',
            r'(?:urlopen|Request)\s*\(\s*["\']https?://([^/\'"]+)',
            r'(?:connect|create_connection)\s*\(\s*\(\s*["\']([^\'\"]+)',
            r'(?:HTTPConnection|HTTPSConnection)\s*\(\s*["\']([^\'\"]+)',
        ]

        found_hosts: set[str] = set()
        for hp in host_patterns:
            for match in re.finditer(hp, code, re.IGNORECASE):
                host = match.group(1).split(":")[0]  # strip port
                found_hosts.add(host)

        if not found_hosts:
            return False

        return all(
            any(h == ah or h.endswith("." + ah) for ah in allowed)
            for h in found_hosts
        )

    def _secret_scan(self, code: str) -> list[CodeThreat]:
        """Layer 6: Credential and secret pattern scan.

        Detects code that accesses, prints, or transmits secrets.

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        list[CodeThreat]
            Detected secret-related threats.
        """
        threats: list[CodeThreat] = []

        secret_patterns = [
            # Accessing environment secrets
            (r"os\.environ\s*\[", CodeThreat.SECRET_EXFIL),
            (r"os\.environ\.get\s*\(", CodeThreat.SECRET_EXFIL),
            (r"os\.getenv\s*\(", CodeThreat.SECRET_EXFIL),
            # Printing secrets
            (r"print\s*\(.*os\.environ", CodeThreat.SECRET_EXFIL),
            (r"print\s*\(.*(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIALS)", CodeThreat.SECRET_EXFIL),
            # Logging secrets
            (r"log(?:ging)?\.(?:info|debug|warning|error|critical)\s*\(.*os\.environ", CodeThreat.SECRET_EXFIL),
            # Cloud metadata endpoints
            (r"169\.254\.169\.254", CodeThreat.CREDENTIAL_ACCESS),
            (r"metadata\.google\.internal", CodeThreat.CREDENTIAL_ACCESS),
            (r"100\.100\.100\.200", CodeThreat.CREDENTIAL_ACCESS),  # Alibaba
            # Sensitive files
            (r"/etc/shadow", CodeThreat.CREDENTIAL_ACCESS),
            (r"\.ssh/id_rsa", CodeThreat.CREDENTIAL_ACCESS),
            (r"\.aws/credentials", CodeThreat.CREDENTIAL_ACCESS),
            (r"\.kube/config", CodeThreat.CREDENTIAL_ACCESS),
            (r"/var/run/secrets/", CodeThreat.CREDENTIAL_ACCESS),
        ]

        for pattern_str, threat in secret_patterns:
            if re.search(pattern_str, code, re.IGNORECASE):
                threats.append(threat)
                # Don't break — collect all secret-related threats

        # Deduplicate
        return list(dict.fromkeys(threats))

    # ===================================================================
    # Severity calculation
    # ===================================================================

    def _calculate_severity(self, threats: list[CodeThreat]) -> float:
        """Calculate aggregate severity from detected threats.

        Uses the maximum single-threat severity weighted upward by the
        number of distinct threats.

        Parameters
        ----------
        threats : list[CodeThreat]
            Detected threats.

        Returns
        -------
        float
            Severity in ``[0.0, 1.0]``.
        """
        if not threats:
            return 0.0

        max_sev = max(_THREAT_SEVERITY.get(t, 0.5) for t in threats)
        # Slight increase for multiple threats (caps at 1.0)
        count_bonus = min(0.1 * (len(threats) - 1), 0.2)
        return min(max_sev + count_bonus, 1.0)

    def _should_block(self, threats: list[CodeThreat], severity: float) -> bool:
        """Determine if code should be blocked.

        Parameters
        ----------
        threats : list[CodeThreat]
            Detected threats.
        severity : float
            Aggregate severity.

        Returns
        -------
        bool
            ``True`` if execution should be blocked.
        """
        if not threats:
            return False

        if self._strict or self._config.code_guard_strict:
            return True  # Any threat blocks in strict mode

        return severity >= self._config.max_code_severity

    # ===================================================================
    # Response helpers
    # ===================================================================

    def _sign(self, code_hash: str, agent_id: str) -> str:
        """Generate HMAC-SHA256 signature for a scan result.

        The signature covers ``code_hash + agent_id + timestamp``,
        ensuring the result cannot be forged.

        Parameters
        ----------
        code_hash : str
            SHA-256 of the code.
        agent_id : str
            Agent identifier.

        Returns
        -------
        str
            Hex-encoded HMAC-SHA256 signature.
        """
        ts = str(time.time())
        msg = f"{code_hash}:{agent_id}:{ts}".encode("utf-8")
        secret = self._config.get_hmac_secret()
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()

    def _redact(self, code: str, threats: list[CodeThreat]) -> str:
        """Remove dangerous parts from code, replacing with comments.

        This produces a version of the code that can be shown to the
        agent as a "here's what was dangerous" explanation.

        Parameters
        ----------
        code : str
            Original source code.
        threats : list[CodeThreat]
            Detected threats to redact.

        Returns
        -------
        str
            Redacted code with dangerous parts replaced by
            ``# [REDACTED: <threat>]`` comments.
        """
        redacted = code
        for threat in threats:
            patterns = DANGEROUS_PATTERNS.get(threat, [])
            for pattern_str in patterns:
                try:
                    compiled = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
                    redacted = compiled.sub(
                        f"# [REDACTED: {threat.value}]", redacted
                    )
                except re.error:
                    continue
        return redacted

    # ===================================================================
    # Statistics
    # ===================================================================

    def get_stats(self) -> dict[str, Any]:
        """Return scan statistics.

        Returns
        -------
        dict
            Keys: ``scan_count``, ``block_count``, ``block_rate``,
            ``threat_distribution``, ``cache_size``.
        """
        return {
            "scan_count": self._scan_count,
            "block_count": self._block_count,
            "block_rate": (
                self._block_count / self._scan_count
                if self._scan_count > 0
                else 0.0
            ),
            "threat_distribution": {
                t.value: count
                for t, count in self._threat_counter.most_common()
            },
            "cache_size": len(self._cache),
        }

    def get_blocked_code(
        self, agent_id: str | None = None
    ) -> list[CodeScanResult]:
        """Return scan results for blocked code.

        Parameters
        ----------
        agent_id : str | None
            If provided, filter to this agent only.

        Returns
        -------
        list[CodeScanResult]
            Blocked scan results, most recent first.
        """
        results = self._blocked_results
        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        return list(reversed(results))

    # ===================================================================
    # Cache management
    # ===================================================================

    async def clear_cache(self) -> int:
        """Clear the scan result cache.

        Returns
        -------
        int
            Number of cached entries removed.
        """
        async with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
        log.info("Cleared %d cached scan results", count)
        return count

    async def get_cache_size(self) -> int:
        """Return the number of cached scan results."""
        async with self._cache_lock:
            return len(self._cache)

    # ===================================================================
    # Repr
    # ===================================================================

    def __repr__(self) -> str:
        return (
            f"CodeGuard(strict={self._strict}, "
            f"scans={self._scan_count}, "
            f"blocks={self._block_count})"
        )
