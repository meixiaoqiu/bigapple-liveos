"""Small helpers shared by contract-facing JSON API views."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse


def read_json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


def error_response(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"code": code, "message": message}, status=status)


def method_not_allowed(request: HttpRequest) -> HttpResponseNotAllowed:
    return HttpResponseNotAllowed(["GET", "POST"])
