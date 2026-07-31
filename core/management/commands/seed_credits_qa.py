"""Seed minimal local QA data for manual credit-system browser testing."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone

from core.credit_services import (
    ensure_system_accounts,
    get_or_create_member_credit_account,
    issue_credits_to_pool,
    post_credit_transaction,
)
from core.governance_setup import ensure_maintainer_role
from core.member_roles import (
    ROLE_FORMAL_MEMBER,
    ensure_catalog_role,
    ensure_role_assignment,
)
from core.models import CreditTransaction, Member, MerchantProfile
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "Seed minimal local QA data for manual credit-system browser testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            help="Target world. Required when world database routing is enabled, for example realworld.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirm this is a local QA database and test users may be created or updated.",
        )

    def handle(self, *args, **options):
        is_test_settings = settings.SETTINGS_MODULE == "live_os.test_settings"
        if not (is_test_settings or getattr(settings, "DEBUG", False)):
            raise CommandError("Refusing to seed QA data unless DEBUG=True or live_os.test_settings is active.")
        if not options.get("yes"):
            raise CommandError("Pass --yes to confirm this is a local QA database.")

        with command_world_context(options.get("world_id"), command_name="seed_credits_qa") as world:
            database_alias = world.database_alias if world is not None else "default"
            existing_tables = set(connections[database_alias].introspection.table_names())
            if "core_organization" not in existing_tables:
                raise CommandError(
                    "Database tables are missing. Run migrations first. "
                    "For browser QA, use settings_admin with --world-id realworld, not live_os.test_settings."
                )

            formal_role = ensure_catalog_role(ROLE_FORMAL_MEMBER)
            maintainer_role = ensure_maintainer_role()["role"]

            mem_a = self._ensure_member("qa-a", "QA Member A")
            mem_b = self._ensure_member("qa-b", "QA Member B")
            maintainer = self._ensure_member("qa-maintainer", "QA Maintainer")
            for member in [mem_a, mem_b, maintainer]:
                ensure_role_assignment(member, formal_role)
            ensure_role_assignment(maintainer, maintainer_role)

            user_model = get_user_model()
            for member in [mem_a, mem_b, maintainer]:
                user, _ = user_model.objects.get_or_create(username=member.member_no)
                user.set_password("test-password")
                user.is_active = True
                user.save(update_fields=["password", "is_active"])
                if member.user_id != user.pk:
                    member.user = user
                    member.save(update_fields=["user"])

            ensure_system_accounts()
            for member in [mem_a, mem_b, maintainer]:
                get_or_create_member_credit_account(member)
            acct_a = get_or_create_member_credit_account(mem_a)
            acct_maintainer = get_or_create_member_credit_account(maintainer)

            issue_credits_to_pool(
                amount=2000,
                reason="QA credit seed",
                initiated_by=maintainer,
                reviewed_by=maintainer,
                idempotency_key="qa-credit-seed-pool",
            )
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=500,
                target_account=acct_a,
                reason="QA initial member balance",
                idempotency_key="qa-credit-seed-member-a",
            )
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=500,
                target_account=acct_maintainer,
                reason="QA initial governance balance",
                idempotency_key="qa-credit-seed-member-maintainer",
            )

            MerchantProfile.objects.get_or_create(
                merchant_id="qa-canteen",
                defaults={
                    "display_name": "QA Canteen Cash Settlement",
                    "merchant_type": MerchantProfile.Type.CASH_SETTLEMENT,
                    "operator_member": mem_a,
                    "settlement_rate": Decimal("0.5"),
                    "status": MerchantProfile.Status.ACTIVE,
                },
            )
            MerchantProfile.objects.get_or_create(
                merchant_id="qa-coffee",
                defaults={
                    "display_name": "QA Coffee Micro Merchant",
                    "merchant_type": MerchantProfile.Type.MEMBER_MICRO,
                    "operator_member": mem_a,
                    "status": MerchantProfile.Status.ACTIVE,
                },
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "QA credit data seeded: "
                    f"world_id={command_world_label(world)}, "
                    "members=qa-a/qa-b/qa-maintainer, password=test-password, "
                    "cash_merchant=qa-canteen, micro_merchant=qa-coffee."
                )
            )

    def _ensure_member(self, member_no: str, display_name: str) -> Member:
        member, _ = Member.objects.get_or_create(
            member_no=member_no,
            defaults={
                "status": "active",
                "batch_id": "qa-credits",
                "joined_simulation_day": 1,
                "credit_floor": -100,
                "created_at": timezone.now(),
                "profile": {"display_name": display_name},
            },
        )
        return member
