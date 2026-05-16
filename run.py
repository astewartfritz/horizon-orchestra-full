#!/usr/bin/env python3
"""Development server for Orchestra.

Usage:
    python run.py                          # Default: ollama + nemotron-mini
    python run.py --provider openai        # Use OpenAI
    python run.py --model qwen2.5:7b       # Use a different Ollama model
    python run.py --host 0.0.0.0 --port 9000

Environment variables (overridden by CLI flags):
    ORCHESTRA_HOST, ORCHESTRA_PORT, ORCHESTRA_PROVIDER, ORCHESTRA_MODEL
    ORCHESTRA_WORKSPACE, ORCHESTRA_LOG_LEVEL, LLM_API_KEY, LLM_BASE_URL
"""
import argparse
import os
import sys

# Env vars with defaults
os.environ.setdefault("ORCHESTRA_HOST", "127.0.0.1")
os.environ.setdefault("ORCHESTRA_PORT", "8000")
os.environ.setdefault("ORCHESTRA_PROVIDER", "ollama")
os.environ.setdefault("ORCHESTRA_MODEL", "nemotron-mini")
os.environ.setdefault("ORCHESTRA_WORKSPACE", os.getcwd())
os.environ.setdefault("ORCHESTRA_LOG_LEVEL", "info")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orchestra development server")
    parser.add_argument("--host", default=os.environ["ORCHESTRA_HOST"])
    parser.add_argument("--port", type=int, default=int(os.environ["ORCHESTRA_PORT"]))
    parser.add_argument("--provider", default=os.environ["ORCHESTRA_PROVIDER"])
    parser.add_argument("--model", default=os.environ["ORCHESTRA_MODEL"])
    parser.add_argument("--log-level", default=os.environ["ORCHESTRA_LOG_LEVEL"])
    args = parser.parse_args()

    os.environ["ORCHESTRA_HOST"] = args.host
    os.environ["ORCHESTRA_PORT"] = str(args.port)
    os.environ["ORCHESTRA_PROVIDER"] = args.provider
    os.environ["ORCHESTRA_MODEL"] = args.model
    os.environ["ORCHESTRA_LOG_LEVEL"] = args.log_level

    # Import and run via the canonical entrypoint
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from entrypoint import main
    main()
