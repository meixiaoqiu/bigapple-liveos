"""Signed metadata bridge for simulation form submissions."""

from __future__ import annotations

from typing import Mapping

from django.core import signing


SIMULATION_METADATA_TOKEN_FIELD = "_simulation_form_token"
SIMULATION_METADATA_TOKEN_SALT = "big-apple-live-os.simulation-form-metadata"
SIMULATION_METADATA_MAX_AGE_SECONDS = 15 * 60


def signed_simulation_metadata_token(
    *,
    run_id: str,
    simulation_hour: int,
    external_ref: str,
    driver_mode: str,
) -> str:
    payload = {
        "simulation_run_id": str(run_id).strip(),
        "simulation_hour": str(simulation_hour).strip(),
        "external_ref": str(external_ref).strip(),
        "driver_mode": str(driver_mode).strip(),
    }
    return signing.dumps(payload, salt=SIMULATION_METADATA_TOKEN_SALT)


def metadata_from_signed_form_post(post_data: Mapping[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {"source": "public_form"}
    token = str(post_data.get(SIMULATION_METADATA_TOKEN_FIELD) or "").strip()
    if not token:
        return metadata

    try:
        payload = signing.loads(
            token,
            salt=SIMULATION_METADATA_TOKEN_SALT,
            max_age=SIMULATION_METADATA_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return metadata

    if not isinstance(payload, dict):
        return metadata

    simulation_run_id = str(payload.get("simulation_run_id") or "").strip()
    if not simulation_run_id:
        return metadata

    metadata["source"] = "simulation_form"
    metadata["simulation_run_id"] = simulation_run_id
    for key in ("external_ref", "simulation_hour", "driver_mode"):
        value = str(payload.get(key) or "").strip()
        if value:
            metadata[key] = value
    return metadata
