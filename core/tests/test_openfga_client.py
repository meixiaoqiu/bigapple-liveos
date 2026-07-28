from __future__ import annotations

import asyncio

from django.test import SimpleTestCase

from core.openfga_client import OpenFGAClient, OpenFGARequestError


class OpenFGAClientTests(SimpleTestCase):
    def test_sdk_configuration_fails_fast_without_retries(self) -> None:
        configuration = OpenFGAClient("http://openfga.test")._configuration()

        self.assertEqual(configuration.timeout_millisec, 1000)
        self.assertEqual(configuration.retry_params.max_retry, 0)

    def test_sdk_response_without_to_dict_converts_to_empty_dict(self) -> None:
        class SDKWriteResponse:
            pass

        self.assertEqual(OpenFGAClient._to_dict(SDKWriteResponse()), {})

    def test_async_timeout_is_wrapped_as_openfga_request_error(self) -> None:
        async def operation():
            raise asyncio.TimeoutError()

        with self.assertRaises(OpenFGARequestError):
            OpenFGAClient("http://openfga.test")._run("check", operation)

    def test_sdk_operation_is_wrapped_in_hard_timeout(self) -> None:
        async def operation():
            await asyncio.sleep(1)

        with self.assertRaises(OpenFGARequestError):
            OpenFGAClient("http://openfga.test", timeout_seconds=0.01)._run("check", operation)
