"""Launch the Code Agent web UI with Nemotron as the default model."""
from code_agent.cli import main
main(["serve", "--provider", "ollama", "--model", "nemotron-mini"])
