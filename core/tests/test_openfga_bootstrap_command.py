from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class OpenFGABootstrapCommandTests(SimpleTestCase):
    @override_settings(
        OPENFGA_SIM_API_URL="http://openfga-sim:8082",
        OPENFGA_SIM_STORE_NAME="big-apple-simulation0001",
    )
    def test_outputs_complete_manual_env_configuration(self) -> None:
        output = StringIO()
        model_path = Path(settings.BASE_DIR) / "openfga" / "bigapple.authorization-model.json"

        with patch("core.management.commands.openfga_bootstrap.OpenFGAClient") as client_class:
            client = client_class.return_value
            client.list_stores.return_value = [
                {"id": "sim-store-id", "name": "big-apple-simulation0001"}
            ]
            client.write_authorization_model.return_value = {
                "authorization_model_id": "sim-model-id"
            }

            call_command(
                "openfga_bootstrap",
                "--world-kind",
                "sim",
                "--api-url",
                "http://openfga-sim:8082",
                stdout=output,
            )

        command_output = output.getvalue()
        self.assertIn("OPENFGA_SIM_API_URL=http://openfga-sim:8082", command_output)
        self.assertIn("OPENFGA_SIM_STORE_ID=sim-store-id", command_output)
        self.assertIn("OPENFGA_SIM_AUTHORIZATION_MODEL_ID=sim-model-id", command_output)
        self.assertIn(
            f"OPENFGA_AUTHORIZATION_MODEL_SHA256={hashlib.sha256(model_path.read_bytes()).hexdigest()}",
            command_output,
        )
