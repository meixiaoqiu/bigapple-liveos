"""Project boundary over the official OpenFGA Python SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync
from openfga_sdk import ClientConfiguration, CreateStoreRequest, ReadRequestTupleKey, WriteAuthorizationModelRequest
from openfga_sdk.client import OpenFgaClient as OpenFGASDKClient
from openfga_sdk.client.models import ClientCheckRequest, ClientTuple
from openfga_sdk.exceptions import ApiException, OpenApiException


class OpenFGARequestError(RuntimeError):
    """Raised when OpenFGA cannot complete a request."""


@dataclass(frozen=True)
class OpenFGAClient:
    api_url: str
    timeout_seconds: float = 3.0

    def _configuration(
        self,
        *,
        store_id: str = "",
        authorization_model_id: str = "",
    ) -> ClientConfiguration:
        return ClientConfiguration(
            api_url=self.api_url.rstrip("/"),
            store_id=store_id or None,
            authorization_model_id=authorization_model_id or None,
            timeout_millisec=int(self.timeout_seconds * 1000),
        )

    def _run(self, operation_name: str, async_operation):
        try:
            return async_to_sync(async_operation)()
        except (ApiException, OpenApiException, TimeoutError, OSError) as exc:
            raise OpenFGARequestError(f"OpenFGA {operation_name} failed: {exc}") from exc

    @staticmethod
    def _to_dict(response) -> dict[str, Any]:
        if response is None:
            return {}
        if hasattr(response, "to_dict"):
            return response.to_dict()
        if isinstance(response, dict):
            return response
        if not hasattr(response, "__iter__"):
            return {}
        return dict(response)

    def list_stores(self) -> list[dict[str, Any]]:
        async def operation():
            client = OpenFGASDKClient(self._configuration())
            try:
                response = await client.list_stores()
                return self._to_dict(response)
            finally:
                await client.close()

        response = self._run("list_stores", operation)
        return list(response.get("stores", []))

    def create_store(self, name: str) -> dict[str, Any]:
        async def operation():
            client = OpenFGASDKClient(self._configuration())
            try:
                response = await client.create_store(CreateStoreRequest(name=name))
                return self._to_dict(response)
            finally:
                await client.close()

        return self._run("create_store", operation)

    def write_authorization_model(self, store_id: str, model: dict[str, Any]) -> dict[str, Any]:
        async def operation():
            client = OpenFGASDKClient(self._configuration(store_id=store_id))
            try:
                response = await client.write_authorization_model(WriteAuthorizationModelRequest(**model))
                return self._to_dict(response)
            finally:
                await client.close()

        return self._run("write_authorization_model", operation)

    def check(
        self,
        *,
        store_id: str,
        user: str,
        relation: str,
        object_: str,
        authorization_model_id: str = "",
    ) -> bool:
        async def operation():
            client = OpenFGASDKClient(
                self._configuration(
                    store_id=store_id,
                    authorization_model_id=authorization_model_id,
                )
            )
            try:
                response = await client.check(
                    ClientCheckRequest(
                        user=user,
                        relation=relation,
                        object=object_,
                    )
                )
                return self._to_dict(response)
            finally:
                await client.close()

        response = self._run("check", operation)
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

        async def operation():
            client = OpenFGASDKClient(
                self._configuration(
                    store_id=store_id,
                    authorization_model_id=authorization_model_id,
                )
            )
            try:
                response = await client.write_tuples(_client_tuples(writes))
                return self._to_dict(response)
            finally:
                await client.close()

        return self._run("write_tuples", operation)

    def delete_tuples(
        self,
        *,
        store_id: str,
        deletes: list[dict[str, str]],
        authorization_model_id: str = "",
    ) -> dict[str, Any]:
        if not deletes:
            return {}

        async def operation():
            client = OpenFGASDKClient(
                self._configuration(
                    store_id=store_id,
                    authorization_model_id=authorization_model_id,
                )
            )
            try:
                response = await client.delete_tuples(_client_tuples(deletes))
                return self._to_dict(response)
            finally:
                await client.close()

        return self._run("delete_tuples", operation)

    def read_tuples(self, *, store_id: str) -> list[dict[str, Any]]:
        async def operation():
            tuples: list[dict[str, Any]] = []
            continuation_token = ""
            client = OpenFGASDKClient(self._configuration(store_id=store_id))
            try:
                while True:
                    options: dict[str, str | int] = {"page_size": 100}
                    if continuation_token:
                        options["continuation_token"] = continuation_token
                    response = self._to_dict(await client.read(ReadRequestTupleKey(), options))
                    tuples.extend(response.get("tuples", []))
                    continuation_token = str(response.get("continuation_token", "") or "")
                    if not continuation_token:
                        return tuples
            finally:
                await client.close()

        return self._run("read_tuples", operation)


def _client_tuples(tuple_keys: list[dict[str, str]]) -> list[ClientTuple]:
    return [
        ClientTuple(
            user=tuple_key["user"],
            relation=tuple_key["relation"],
            object=tuple_key["object"],
        )
        for tuple_key in tuple_keys
    ]
