"""Example: Start the Code Agent API server.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/server_example.py

Then open http://localhost:8000/docs for the interactive API docs.
"""
from code_agent.api.server import AgentAPI


def serve(host: str = "127.0.0.1", port: int = 8000):
    api = AgentAPI()
    import asyncio
    asyncio.run(api.run_server(host=host, port=port))

if __name__ == "__main__":
    serve(host="127.0.0.1", port=8000)
