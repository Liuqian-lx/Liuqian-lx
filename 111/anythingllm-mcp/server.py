import logging
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from anythingllm import AnythingLLMClient, AnythingLLMError
from config import load_config

logger = logging.getLogger(__name__)

config = load_config()

client = AnythingLLMClient(
    base_url=config.anythingllm_url,
    api_key=config.anythingllm_api_key,
    session_id=config.session_id,
    workspace_slug=config.workspace_slug,
)

mcp = MCPServer("anythingllm-mcp", log_level=config.log_level)


@mcp.tool(
    title="Ask the AnythingLLM workspace",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def workspace_chat(
    message: Annotated[str, Field(description="The question to ask.")],
    mode: Literal["chat", "query", "automatic"] = "chat",
) -> str:
    """Ask a question and answer it from the single AnythingLLM workspace: the reply is grounded in the documents and knowledge stored in that workspace."""
    try:
        return client.chat(message, mode=mode)
    except AnythingLLMError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool(
    title="Count files in the AnythingLLM workspace",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def workspace_file_count(
    include_names: Annotated[
        bool,
        Field(description="When true, also list every file name stored in the workspace."),
    ] = False,
) -> str:
    """Return how many files (documents) are stored in the AnythingLLM workspace, optionally listing their names."""
    try:
        documents = client.get_workspace_documents()
    except AnythingLLMError as exc:
        raise RuntimeError(str(exc)) from exc
    total = len(documents)
    if not include_names:
        return f"The workspace contains {total} file(s)."
    listing = "\n".join(f"- {client.document_title(doc)}" for doc in documents)
    return f"The workspace contains {total} file(s):\n{listing}"


@mcp.tool(
    title="Search the AnythingLLM workspace",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def workspace_search(
    query: Annotated[str, Field(description="Keywords or a question used to search the workspace documents.")],
    top_n: Annotated[
        int,
        Field(ge=1, le=20, description="How many matching document chunks to return (1-20)."),
    ] = 5,
) -> str:
    """Search the documents stored in the AnythingLLM workspace by vector similarity and return the matching excerpts with their source file names. This does not need a chat model, so it works even when the workspace AI is offline."""
    try:
        results = client.vector_search(query, top_n)
    except AnythingLLMError as exc:
        raise RuntimeError(str(exc)) from exc
    if not results:
        return (
            f"No document in the workspace matched {query!r}. "
            "Try different keywords, or check that relevant files were uploaded."
        )
    blocks = []
    for index, item in enumerate(results, 1):
        source, body = _split_chunk(str(item.get("text", "")))
        score = item.get("score")
        score_text = f" (score {score:.4f})" if isinstance(score, (int, float)) else ""
        blocks.append(
            f"[{index}] source: {source or 'unknown'}{score_text}\n{body.strip()}"
        )
    return f"Found {len(results)} matching excerpt(s) for {query!r}:\n\n" + "\n\n".join(blocks)


def _split_chunk(text: str) -> tuple[str, str]:
    """Split AnythingLLM's ``<document_metadata>`` prefix off a chunk."""
    source = ""
    body = text
    if text.startswith("<document_metadata>"):
        end = text.find("</document_metadata>")
        if end != -1:
            meta = text[len("<document_metadata>"):end]
            for line in meta.splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "sourceDocument":
                    source = value.strip()
                    break
            body = text[end + len("</document_metadata>"):]
    return source, body


if __name__ == "__main__":
    try:
        slug = client.resolve_workspace_slug()
        logger.info("Using AnythingLLM workspace: %s", slug)
    except Exception as exc:
        logger.warning("Workspace resolution failed at startup: %s", exc)

    mcp.run(
        transport="streamable-http",
        host=config.mcp_host,
        port=config.mcp_port,
        streamable_http_path=config.mcp_path,
        json_response=True,
        stateless_http=True,
    )