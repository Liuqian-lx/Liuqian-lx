import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"


@dataclass(frozen=True)
class Config:
    anythingllm_url: str
    anythingllm_api_key: str
    workspace_slug: str | None
    session_id: str
    mcp_host: str
    mcp_port: int
    mcp_path: str
    log_level: str


def load_config(env_path: Path = DEFAULT_ENV_PATH) -> Config:
    load_dotenv(dotenv_path=env_path, override=False)

    api_key = os.getenv("ANYTHINGLLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANYTHINGLLM_API_KEY is required. Copy .env.example to .env and fill it in."
        )

    port_raw = (os.getenv("MCP_PORT", "3002") or "").strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError(f"MCP_PORT must be an integer, got {port_raw!r}") from exc

    return Config(
        anythingllm_url=(os.getenv("ANYTHINGLLM_URL", "http://localhost:3001/api") or "").rstrip("/"),
        anythingllm_api_key=api_key,
        workspace_slug=(os.getenv("ANYTHINGLLM_WORKSPACE_SLUG") or "").strip() or None,
        session_id=os.getenv("ANYTHINGLLM_SESSION_ID", "mcp-anythingllm-workspace"),
        mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
        mcp_port=port,
        mcp_path=os.getenv("MCP_PATH", "/mcp"),
        log_level=os.getenv("MCP_LOG_LEVEL", "INFO"),
    )