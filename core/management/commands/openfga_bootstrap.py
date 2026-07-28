"""Bootstrap the local OpenFGA store and authorization model."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.authorization_services import openfga_context_for_world_kind
from core.openfga_client import OpenFGAClient, OpenFGARequestError


class Command(BaseCommand):
    help = "Create or reuse an OpenFGA store and write the Big Apple authorization model."

    def add_arguments(self, parser):
        parser.add_argument("--world-kind", choices=("real", "sim"), default=None)
        parser.add_argument("--store-name", default="")
        parser.add_argument("--api-url", default="")
        parser.add_argument(
            "--model-file",
            default=str(Path(settings.BASE_DIR) / "openfga" / "bigapple.authorization-model.json"),
        )

    def handle(self, *args, **options):
        context = openfga_context_for_world_kind(options["world_kind"])
        api_url = options["api_url"] or context.api_url
        store_name = options["store_name"] or context.store_name
        client = OpenFGAClient(api_url)
        model_path = Path(options["model_file"])
        if not model_path.exists():
            raise CommandError(f"OpenFGA model file does not exist: {model_path}")

        try:
            stores = client.list_stores()
            store = next((item for item in stores if item.get("name") == store_name), None)
            if store is None:
                store = client.create_store(store_name)
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model_response = client.write_authorization_model(store["id"], model)
        except (OpenFGARequestError, json.JSONDecodeError, KeyError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("OpenFGA local store/model is ready."))
        self.stdout.write(f"OPENFGA_{context.world_kind.upper()}_API_URL={api_url}")
        self.stdout.write(f"OPENFGA_{context.world_kind.upper()}_STORE_ID={store['id']}")
        self.stdout.write(
            f"OPENFGA_{context.world_kind.upper()}_AUTHORIZATION_MODEL_ID={model_response.get('authorization_model_id', '')}"
        )
