from __future__ import annotations

from pathlib import Path

COMMANDS = [
    "run", "tui", "repl", "serve", "review", "scaffold",
    "session", "benchmark", "mcp", "analyze", "vector",
    "testgen", "watch", "cost", "plugins", "tools", "init",
    "improve", "workflow", "docgen", "graphviz",
]

TOOLS = [
    "read", "write", "edit", "glob", "bash", "grep",
    "webfetch", "websearch", "git", "task", "diff",
    "patch", "apply_edit", "index", "analyze", "testgen",
    "watch", "sandbox", "scaffold", "improve", "workflow",
    "docgen", "graphviz",
]

PROVIDERS = ["openai", "anthropic", "ollama"]
MODELS = ["gpt-4o", "gpt-4o-mini", "claude-sonnet-4-20250514", "claude-3-haiku"]
TEMPLATES = ["python-package", "python-script", "typescript-package", "web-app", "fastapi-app"]

_JOINED_COMMANDS = " ".join(COMMANDS)
_JOINED_PROVIDERS = " ".join(PROVIDERS)
_JOINED_MODELS = " ".join(MODELS)
_JOINED_TEMPLATES = " ".join(TEMPLATES)

ZSH_COMPLETION = f"""#compdef code-agent

_code_agent() {{
    local -a commands
    commands=(
        {" ".join(f'"{cmd}:Code Agent command"' for cmd in COMMANDS)}
    )

    _arguments \\
        '--help[Show help]' \\
        '--version[Show version]' \\
        '1: :->command' \\
        '*: :->args'

    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[1] in
                run)
                    _arguments \\
                        '-m[Model]:model:({_JOINED_PROVIDERS})' \\
                        '-p[Provider]:provider:({_JOINED_MODELS})' \\
                        '-w[Workspace]:directory:_files -/' \\
                        '--stream[Stream output]' \\
                        '--cache[Enable caching]' \\
                        '--config[Config file]:file:_files'
                    ;;
                scaffold)
                    _arguments \\
                        '1:template:({_JOINED_TEMPLATES})' \\
                        '2:name:' \\
                        '-d[Description]:description:' \\
                        '-o[Output dir]:directory:_files -/'
                    ;;
                serve)
                    _arguments \\
                        '-h[Host]:host:' \\
                        '-p[Port]:port:' \\
                        '--model[Model]:model:({_JOINED_MODELS})'
                    ;;
                analyze|vector|testgen|watch|improve|docgen|graphviz)
                    _arguments \\
                        '1:file:_files' \\
                        '*:options'
                    ;;
                *)
                    _files
                    ;;
            esac
            ;;
    esac
}}

_code_agent "$@"
"""

BASH_COMPLETION = f"""_code_agent_completion() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    local commands="{_JOINED_COMMANDS}"

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
    else
        case "${{COMP_WORDS[1]}}" in
            run)
                COMPREPLY=($(compgen -W "-m --model -p --provider -w --workspace --stream --cache --config" -- "$cur"))
                ;;
            scaffold)
                if [[ $COMP_CWORD -eq 2 ]]; then
                    COMPREPLY=($(compgen -W "{_JOINED_TEMPLATES}" -- "$cur"))
                fi
                ;;
            review|analyze|vector|testgen|watch|improve|docgen|graphviz)
                COMPREPLY=($(compgen -f -- "$cur"))
                ;;
            *)
                COMPREPLY=($(compgen -f -- "$cur"))
                ;;
        esac
    fi
}}

complete -F _code_agent_completion code-agent
"""

_JOINED_COMMANDS_PS = "', '".join(COMMANDS)
_JOINED_TEMPLATES_PS = "', '".join(TEMPLATES)

POWERSHELL_COMPLETION = f"""Register-ArgumentCompleter -Native -CommandName code-agent -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $commands = @('{_JOINED_COMMANDS_PS}')
    $command = $commandAst.CommandElements[1].Value

    if (-not $command) {{
        return $commands | Where-Object {{ $_ -like "$wordToComplete*" }}
    }}

    switch ($command) {{
        "run" {{ return @("-m", "--model", "-p", "--provider", "-w", "--workspace", "--stream", "--cache", "--config") }}
        "scaffold" {{ return @('{_JOINED_TEMPLATES_PS}') }}
        default {{ return @() }}
    }}
}}
"""


def generate_completions(shell: str = "bash") -> str:
    match shell:
        case "zsh":
            return ZSH_COMPLETION
        case "bash":
            return BASH_COMPLETION
        case "powershell":
            return POWERSHELL_COMPLETION
        case _:
            raise ValueError(f"Unsupported shell: {shell}")


def install_completions(shell: str = "bash") -> str:
    if shell == "bash":
        path = Path.home() / ".bash_completion.d" / "code-agent"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BASH_COMPLETION, "utf-8")
        return str(path)
    elif shell == "zsh":
        path = Path("/usr/local/share/zsh/site-functions") / "_code-agent"
        try:
            path.write_text(ZSH_COMPLETION, "utf-8")
            return str(path)
        except PermissionError:
            local_path = Path.home() / ".zsh" / "_code-agent"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(ZSH_COMPLETION, "utf-8")
            return str(local_path)
    elif shell == "powershell":
        path = Path.home() / "Documents" / "PowerShell" / "code-agent-completions.ps1"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(POWERSHELL_COMPLETION, "utf-8")
        return str(path)
    else:
        raise ValueError(f"Unsupported shell: {shell}")
