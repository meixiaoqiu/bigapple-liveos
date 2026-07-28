"""Small OpenFGA HTTP client used by local authorization tooling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenFGARequestError(RuntimeError):
    """Raised when OpenFGA cannot complete a request."""


@dataclass(frozen=True)
class OpenFGAClient:
    api_url: str
    timeout_seconds: float = 3.0

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise OpenFGARequestError(f"OpenFGA {method} {path} failed: HTTP {exc.code} {details}") from exc
        except URLError as exc:
            raise OpenFGARequestError(f"OpenFGA {method} {path} failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OpenFGARequestError(f"OpenFGA {method} {path} timed out") from exc

        if not content:
            return {}
        return json.loads(content.decode("utf-8"))

    def list_stores(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/stores")
        return list(response.get("stores", []))

    def create_store(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/stores", {"name": name})

    def write_authorization_model(self, store_id: str, model: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/stores/{store_id}/authorization-models", model)

    def check(
        self,
        *,
        store_id: str,
        user: str,
        relation: str,
        object_: str,
        authorization_model_id: str = "",
    ) -> bool:
        body: dict[str, Any] = {
            "tuple_key": {
                "user": user,
                "relation": relation,
                "object": object_,
            },
        }
        if authorization_model_id:
            body["authorization_model_id"] = authorization_model_id
        response = self._request("POST", f"/stores/{store_id}/check", body)
        return bool(response.get("allowed"))

    def write_tuples(
        self,
        *,
        store_id: str,
        writes: list[dict[str, str]],
        authorization_model_id: str = "",
    ) -> dict[str, Any]:
        if not writes:
            return {}
        body: dict[str, Any] = {"writes": {"tuple_keys": writes}}
        if authorization_model_id:
            body["authorization_model_id"] = authorization_model_id
        return self._request("POST", f"/stores/{store_id}/write", body)

    def read_tuples(self, *, store_id: str) -> list[dict[str, Any]]:
        tuples: list[dict[str, Any]] = []
        continuation_token = ""
        while True:
            body: dict[str, Any] = {}
            if continuation_token:
                body["continuation_token"] = continuation_token
            response = self._request("POST", f"/stores/{store_id}/read", body)
            tuples.extend(response.get("tuples", []))
            continuation_token = str(response.get("continuation_token", "") or "")
            if not continuation_token:
                return tuples
