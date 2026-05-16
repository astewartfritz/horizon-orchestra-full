"""Cloud entrypoint for Orchestra. Reads env vars and starts the server."""
import logging
import os
import sys

logging.basicConfig(
    level=getattr(logging, os.environ.get("ORCHESTRA_LOG_LEVEL", "info").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)

os.environ.setdefault("ORCHESTRA_HOST", "0.0.0.0")
os.environ.setdefault("ORCHESTRA_PORT", "8000")
os.environ.setdefault("ORCHESTRA_PROVIDER", os.environ.get("LLM_PROVIDER", "ollama"))
os.environ.setdefault("ORCHESTRA_MODEL", os.environ.get("LLM_MODEL", "nemotron-mini"))
_default_ws = os.getcwd() if os.name == "nt" else "/workspace"
os.environ.setdefault("ORCHESTRA_WORKSPACE", os.environ.get("WORKSPACE", _default_ws))
os.environ.setdefault("ORCHESTRA_SESSION_DIR", os.environ.get("SESSION_DIR", ""))
os.environ.setdefault("ORCHESTRA_LOG_LEVEL", os.environ.get("LOG_LEVEL", "info"))
os.environ.setdefault("OTEL_ENABLED", os.environ.get("OTEL_ENABLED", "false"))
os.environ.setdefault("OTEL_SERVICE_NAME", os.environ.get("OTEL_SERVICE_NAME", "orchestra"))
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", os.environ.get("OTEL_ENDPOINT", "http://localhost:4317"))

def main():
    """Start the Orchestra server using environment variables for configuration."""
    logger = logging.getLogger("orchestra")
    host = os.environ["ORCHESTRA_HOST"]
    port = int(os.environ["ORCHESTRA_PORT"])
    log_level = os.environ["ORCHESTRA_LOG_LEVEL"]

    from code_agent.config import AgentConfig, LLMConfig
    cfg = AgentConfig(
        llm=LLMConfig(
            provider=os.environ["ORCHESTRA_PROVIDER"],
            model=os.environ["ORCHESTRA_MODEL"],
            api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
        ),
        workspace=os.environ["ORCHESTRA_WORKSPACE"],
    )
    from code_agent.ui.server import create_ui_app
    app = create_ui_app(cfg)

    logger.info("Starting provider=%s model=%s on %s:%s", cfg.llm.provider, cfg.llm.model, host, port)
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
