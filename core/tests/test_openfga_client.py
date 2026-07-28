from __future__ import annotations

from django.test import SimpleTestCase

from core.openfga_client import OpenFGAClient


class OpenFGAClientTests(SimpleTestCase):
    def test_sdk_response_without_to_dict_converts_to_empty_dict(self) -> None:
        class SDKWriteResponse:
            pass

        self.assertEqual(OpenFGAClient._to_dict(SDKWriteResponse()), {})
