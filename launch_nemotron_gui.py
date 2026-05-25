"""Launch the Code Agent web UI with Nemotron as the default model."""
from orchestra.code_agent.cli import main
main(["serve", "--provider", "ollama", "--model", "nemotron-mini"])
