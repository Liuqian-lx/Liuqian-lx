import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 300.0


class AnythingLLMError(RuntimeError):
    """Raised when the AnythingLLM API returns an error or cannot be reached."""


class AnythingLLMClient:
    """Tiny REST client for the local AnythingLLM Developer API."""

    def __init__(self, base_url: str, api_key: str, session_id: str, workspace_slug: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self._configured_slug = workspace_slug
        self._resolved_slug: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None):
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise AnythingLLMError(
                f"AnythingLLM {method} {path} failed: HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AnythingLLMError(
                f"AnythingLLM {method} {path} unreachable: {exc.reason}"
            ) from exc
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AnythingLLMError(
                f"AnythingLLM returned non-JSON response: {payload[:200]!r}"
            ) from exc

    def list_workspaces(self) -> list[dict]:
        data = self._request("GET", "/v1/workspaces")
        if not isinstance(data, dict):
            raise AnythingLLMError("Unexpected workspaces response shape")
        return data.get("workspaces", [])

    def resolve_workspace_slug(self) -> str:
        if self._configured_slug:
            return self._configured_slug
        if self._resolved_slug:
            return self._resolved_slug
        workspaces = self.list_workspaces()
        if len(workspaces) == 1:
            slug = workspaces[0].get("slug")
            if not slug:
                raise AnythingLLMError("The workspace has no slug")
            self._resolved_slug = slug
            logger.info("Auto-detected workspace '%s' (%s)", workspaces[0].get("name"), slug)
            return slug
        if not workspaces:
            raise AnythingLLMError("No workspaces found on the AnythingLLM server")
        listing = ", ".join(
            f"{w.get('name', '?')} ({w.get('slug')})" for w in workspaces
        )
        raise AnythingLLMError(
            "Multiple workspaces found; set ANYTHINGLLM_WORKSPACE_SLUG to select one. "
            f"Found: {listing}"
        )

    def get_workspace_documents(self) -> list[dict]:
        slug = self.resolve_workspace_slug()
        data = self._request("GET", f"/v1/workspace/{slug}")
        if not isinstance(data, dict):
            raise AnythingLLMError("Unexpected workspace response shape")
        workspaces = data.get("workspace", [])
        if not isinstance(workspaces, list) or not workspaces:
            raise AnythingLLMError(f"Workspace {slug} returned no data")
        documents = workspaces[0].get("documents", [])
        if not isinstance(documents, list):
            raise AnythingLLMError("Unexpected documents response shape")
        return documents

    def document_title(self, document: dict) -> str:
        """Return the original, human-readable source file name if available.

        AnythingLLM stores a parsed cache file (filename like ``<name>-<uuid>.json``)
        per document; the original uploaded name lives inside the JSON ``metadata``
        field under ``title``.
        """
        meta_raw = document.get("metadata")
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError:
                meta = {}
        elif isinstance(meta_raw, dict):
            meta = meta_raw
        else:
            meta = {}
        title = meta.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return document.get("filename") or "?"

    def vector_search(self, query: str, top_n: int = 5) -> list[dict]:
        """Return the most similar document chunks for ``query``.

        Uses AnythingLLM's vector-search endpoint, which only needs the
        workspace embedder and does not involve a chat model.
        """
        slug = self.resolve_workspace_slug()
        data = self._request(
            "POST",
            f"/v1/workspace/{slug}/vector-search",
            body={"query": query, "topN": max(1, min(int(top_n), 20))},
        )
        if not isinstance(data, dict):
            raise AnythingLLMError("Unexpected vector-search response shape")
        results = data.get("results")
        if not isinstance(results, list):
            raise AnythingLLMError("Vector-search response has no results list")
        return [item for item in results if isinstance(item, dict)]

    def chat(self, message: str, mode: str = "chat") -> str:
        slug = self.resolve_workspace_slug()
        body = {
            "message": message,
            "mode": mode,
            "sessionId": self.session_id,
            "recentMessages": [],
        }
        data = self._request("POST", f"/v1/workspace/{slug}/chat", body=body)
        if not isinstance(data, dict):
            raise AnythingLLMError("Empty response from AnythingLLM chat endpoint")
        if data.get("error"):
            raise AnythingLLMError(f"AnythingLLM chat error: {data['error']}")
        if data.get("type") != "textResponse":
            raise AnythingLLMError(f"Unexpected chat response type: {data.get('type')}")
        return data.get("textResponse", "")