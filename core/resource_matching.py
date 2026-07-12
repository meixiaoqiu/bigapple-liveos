"""Resource demand, stock, and supplier quote matching."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import PartnerApplication, PlanRequirement, PlanRevision, Resource, SupplierQuote


ZERO = Decimal("0")


@dataclass(frozen=True)
class ResourceGapRow:
    """Aggregated demand and supply picture for one resource."""

    resource: Resource
    requirements: list[PlanRequirement]
    required_quantity: Decimal
    current_stock: Decimal
    shortage_quantity: Decimal
    active_quote_count: int
    quoted_available_quantity: Decimal
    best_quote: SupplierQuote | None

    @property
    def has_shortage(self) -> bool:
        return self.shortage_quantity > ZERO

    @property
    def is_fully_covered_by_quotes(self) -> bool:
        return self.has_shortage and self.quoted_available_quantity >= self.shortage_quantity

    @property
    def coverage_status(self) -> str:
        if not self.has_shortage:
            return "stock_sufficient"
        if self.is_fully_covered_by_quotes:
            return "quoted_cover"
        if self.quoted_available_quantity > ZERO:
            return "quoted_partial"
        return "no_quote"

    @property
    def estimated_best_cost(self) -> Decimal | None:
        if self.best_quote is None or not self.has_shortage:
            return None
        purchasable_quantity = min(self.shortage_quantity, self.best_quote.available_quantity)
        return purchasable_quantity * self.best_quote.unit_price


def active_supplier_quotes_for_resource(resource: Resource, *, at_time=None):
    """Return usable quotes for a resource from qualified or standby partners."""

    at_time = at_time or timezone.now()
    return (
        SupplierQuote.objects.select_related("partner_application", "resource")
        .filter(
            resource=resource,
            status=SupplierQuote.Status.ACTIVE,
            partner_application__status__in=[
                PartnerApplication.Status.QUALIFIED,
                PartnerApplication.Status.STANDBY,
            ],
        )
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=at_time))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=at_time))
        .order_by("unit_price", "lead_time_days", "quote_id")
    )


def resource_gap_rows(*, revision: PlanRevision | None = None, at_time=None) -> list[ResourceGapRow]:
    """Aggregate published plan requirements against current stock and active quotes."""

    requirements = (
        PlanRequirement.objects.select_related("node", "node__revision", "resource")
        .filter(resource__isnull=False, quantity__gt=ZERO)
        .order_by("resource_id", "node__sequence", "requirement_id")
    )
    if revision is not None:
        requirements = requirements.filter(node__revision=revision)
    else:
        requirements = requirements.filter(node__revision__status=PlanRevision.Status.PUBLISHED)

    grouped: dict[str, dict[str, object]] = {}
    for requirement in requirements:
        resource = requirement.resource
        if resource is None:
            continue
        row = grouped.setdefault(
            resource.pk,
            {
                "resource": resource,
                "requirements": [],
                "required_quantity": ZERO,
            },
        )
        row["requirements"].append(requirement)
        row["required_quantity"] = row["required_quantity"] + requirement.quantity

    rows: list[ResourceGapRow] = []
    for item in grouped.values():
        resource = item["resource"]
        required_quantity = item["required_quantity"]
        current_stock = resource.current_stock
        shortage_quantity = max(required_quantity - current_stock, ZERO)
        quotes = list(active_supplier_quotes_for_resource(resource, at_time=at_time))
        quoted_available_quantity = sum((quote.available_quantity for quote in quotes), ZERO)
        rows.append(
            ResourceGapRow(
                resource=resource,
                requirements=item["requirements"],
                required_quantity=required_quantity,
                current_stock=current_stock,
                shortage_quantity=shortage_quantity,
                active_quote_count=len(quotes),
                quoted_available_quantity=quoted_available_quantity,
                best_quote=quotes[0] if quotes else None,
            )
        )

    return sorted(rows, key=lambda row: (row.coverage_status != "no_quote", row.resource.resource_type, row.resource.pk))
