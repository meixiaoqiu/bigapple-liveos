"""Replaceable payment execution boundary with a complete built-in default."""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from django.conf import settings

from core.exceptions import DomainError


@dataclass(frozen=True)
class PaymentRequest:
    claim_id: str
    amount: str
    currency: str
    payment_date: date
    payment_method: str


@dataclass(frozen=True)
class PaymentResult:
    succeeded: bool
    external_system: str = ""
    external_object_id: str = ""
    snapshot: dict = field(default_factory=dict)


class FinancePaymentBackend(Protocol):
    backend_type: str

    def execute(self, request: PaymentRequest) -> PaymentResult: ...


class LiveOSManualPaymentBackend:
    """Record a payment already performed by an accountable finance member."""

    backend_type = "liveos_manual"

    def execute(self, request: PaymentRequest) -> PaymentResult:
        if not request.payment_method.strip():
            raise DomainError("付款方式不能为空。")
        return PaymentResult(
            succeeded=True,
            snapshot={"mode": "manual_confirmation"},
        )


PAYMENT_BACKENDS = {LiveOSManualPaymentBackend.backend_type: LiveOSManualPaymentBackend}


def get_payment_backend() -> FinancePaymentBackend:
    """Return the configured implemented backend or fail closed."""
    backend_type = str(getattr(settings, "FINANCE_PAYMENT_BACKEND", "liveos_manual") or "").strip().lower()
    backend_class = PAYMENT_BACKENDS.get(backend_type)
    if backend_class is None:
        raise DomainError("付款执行后端未实现或配置无效。")
    return backend_class()
