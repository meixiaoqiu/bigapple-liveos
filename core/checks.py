"""Project system checks for configured capability backends."""

from django.conf import settings
from django.core.checks import Error, register

from .payment_backends import PAYMENT_BACKENDS


@register()
def finance_payment_backend_check(app_configs, **kwargs):
    backend_type = str(getattr(settings, "FINANCE_PAYMENT_BACKEND", "") or "").strip().lower()
    if backend_type not in PAYMENT_BACKENDS:
        return [Error("付款执行后端未实现或配置无效。", id="core.E020")]
    return []
