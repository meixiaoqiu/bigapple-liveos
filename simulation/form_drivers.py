"""Drivers that make simulations interact with real world-scoped forms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from django.conf import settings
from django.test import Client, override_settings

from applications.simulation_metadata import SIMULATION_METADATA_TOKEN_FIELD, signed_simulation_metadata_token
from core.models import MemberApplication, PartnerApplication


@dataclass(frozen=True)
class FormSubmissionResult:
    success: bool
    path: str
    status_code: int
    application_id: str = ""
    errors: list[str] = field(default_factory=list)


class HttpFormDriver:
    """Submit simulation actions through real Django pages without opening a browser."""

    mode = "http_form"

    def __init__(self, *, host: str | None = None):
        self.client = Client()
        self.host = host or self._default_host()

    def submit_member_application(
        self,
        *,
        world_id: str,
        run_id: str,
        simulation_hour: int,
        external_ref: str,
        data: Mapping[str, object],
    ) -> FormSubmissionResult:
        self.client.logout()
        with self._fixed_world_urlconf(world_id):
            # Step 1: register the account first
            username = str(data.get("username") or "").strip()
            password = str(data.get("password1") or data.get("password") or "sim-test-password").strip()
            register_data = {
                "username": username,
                "password1": password,
                "password2": password,
                "display_name": str(data.get("applicant_name") or username),
                "contact": str(data.get("contact") or ""),
            }
            reg_resp = self.client.post(
                "/register/", data=register_data, follow=True, HTTP_HOST=self.host
            )
            if reg_resp.status_code >= 400:
                return FormSubmissionResult(
                    False, "/register/", reg_resp.status_code,
                    errors=[self._response_error(reg_resp, "注册账号失败。")],
                )

            # Step 2: use apply/ as authenticated user
            path = "/apply/"
            required_fields = (
                "applicant_name",
                "contact",
                "role_gap",
                "availability_slots",
                "motivation_reasons",
                "confirm_submit",
            )
            page_error = self._verify_form_page(world_id, path, required_fields)
            if page_error:
                return FormSubmissionResult(False, path, page_error[0], errors=[page_error[1]])
            payload = self._payload(
                data=data,
                run_id=run_id,
                simulation_hour=simulation_hour,
                external_ref=external_ref,
            )
            response = self.client.post(path, data=payload, follow=True, HTTP_HOST=self.host)
        application = MemberApplication.objects.filter(metadata__external_ref=external_ref).first()
        if response.status_code >= 400 or application is None:
            return FormSubmissionResult(
                False,
                path,
                response.status_code,
                errors=[self._response_error(response, "成员报名表单提交后没有生成 MemberApplication。")],
            )
        return FormSubmissionResult(True, path, response.status_code, application_id=application.application_id)

    def submit_partner_application(
        self,
        *,
        world_id: str,
        run_id: str,
        simulation_hour: int,
        external_ref: str,
        data: Mapping[str, object],
    ) -> FormSubmissionResult:
        self.client.logout()
        path = self._application_path(world_id, "partner")
        required_fields = (
            "organization_name",
            "contact_name",
            "contact",
            "service_domains_text",
        )
        page_error = self._verify_form_page(world_id, path, required_fields)
        if page_error:
            return FormSubmissionResult(False, path, page_error[0], errors=[page_error[1]])
        payload = self._payload(
            data=data,
            run_id=run_id,
            simulation_hour=simulation_hour,
            external_ref=external_ref,
        )
        with self._fixed_world_urlconf(world_id):
            response = self.client.post(path, data=payload, follow=True, HTTP_HOST=self.host)
        application = PartnerApplication.objects.filter(metadata__external_ref=external_ref).first()
        if response.status_code >= 400 or application is None:
            return FormSubmissionResult(
                False,
                path,
                response.status_code,
                errors=[self._response_error(response, "合作方报名表单提交后没有生成 PartnerApplication。")],
            )
        return FormSubmissionResult(True, path, response.status_code, application_id=application.application_id)

    def _verify_form_page(self, world_id: str, path: str, field_names: tuple[str, ...]) -> tuple[int, str] | None:
        with self._fixed_world_urlconf(world_id):
            response = self.client.get(path, HTTP_HOST=self.host)
        if response.status_code >= 400:
            return response.status_code, self._response_error(response, "报名页面无法打开。")
        html = response.content.decode(response.charset or "utf-8", errors="replace")
        missing_fields = [field_name for field_name in field_names if f'name="{field_name}"' not in html]
        if missing_fields:
            return response.status_code, f"报名页面缺少表单字段：{', '.join(missing_fields)}"
        return None

    def _payload(
        self,
        *,
        data: Mapping[str, object],
        run_id: str,
        simulation_hour: int,
        external_ref: str,
    ) -> dict[str, object]:
        return {
            **dict(data),
            SIMULATION_METADATA_TOKEN_FIELD: signed_simulation_metadata_token(
                run_id=run_id,
                simulation_hour=simulation_hour,
                external_ref=external_ref,
                driver_mode=self.mode,
            ),
        }

    def _response_error(self, response, fallback: str) -> str:
        content = response.content.decode(response.charset or "utf-8", errors="replace").strip()
        if not content:
            return fallback
        return f"{fallback} HTTP {response.status_code}: {content[:500]}"

    def _application_path(self, world_id: str, application_type: str) -> str:
        if application_type == "member":
            return "/apply/"
        return f"/apply/{application_type}/"

    def _fixed_world_urlconf(self, world_id: str):
        database_alias = world_id if world_id in settings.DATABASES else "default"
        database_name = str(settings.DATABASES.get(database_alias, {}).get("NAME", ""))
        return override_settings(
            ROOT_URLCONF="live_os.urls_world",
            SITE_FIXED_WORLD=True,
            SITE_WORLD_ID=world_id,
            SITE_WORLD_TYPE="simulation" if world_id.startswith("simulation") else "real",
            SITE_WORLD_DATABASE_ALIAS=database_alias,
            SITE_WORLD_DATABASE_NAME=database_name,
        )

    def _default_host(self) -> str:
        allowed_hosts = [host for host in getattr(settings, "ALLOWED_HOSTS", []) if host and host != "*"]
        site_role = getattr(settings, "SITE_ROLE", "")
        preferred_hosts = {
            "real": "bigreal.local",
            "simulation": "bigsim.local",
            "control": "bigadmin.local",
        }
        preferred_host = preferred_hosts.get(site_role)
        if preferred_host in allowed_hosts:
            return preferred_host
        if "big.local" in allowed_hosts:
            return "big.local"
        if "localhost" in allowed_hosts:
            return "localhost"
        if "127.0.0.1" in allowed_hosts:
            return "127.0.0.1"
        if allowed_hosts:
            return allowed_hosts[0]
        return "localhost"
