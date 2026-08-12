from django.conf import settings
from django.db import migrations, models


LEGACY_ADMINISTRATOR_NAMES = ("典守者", "维护者")


def rename_administrator_authority_facts(apps, schema_editor):
    """仿真 world 直接采用管理员新语义；其他数据库遇到旧事实时失败关闭。"""

    Role = apps.get_model("core", "Role")
    Proposal = apps.get_model("core", "Proposal")
    ElectorateRuleTemplate = apps.get_model("core", "ElectorateRuleTemplate")
    ProposalTypeElectorateRule = apps.get_model("core", "ProposalTypeElectorateRule")
    database_alias = schema_editor.connection.alias
    is_simulation = (
        getattr(settings, "SITE_WORLD_TYPE", "") == "simulation"
        or database_alias.startswith("simulation")
    )

    legacy_roles = Role.objects.using(database_alias).filter(
        organization__role_catalog_key="member-role-catalog",
        name__in=LEGACY_ADMINISTRATOR_NAMES,
    )
    legacy_proposals = Proposal.objects.using(database_alias).filter(proposal_type="maintenance")
    legacy_templates = ElectorateRuleTemplate.objects.using(database_alias).filter(code="maintainer_matter")
    legacy_bindings = ProposalTypeElectorateRule.objects.using(database_alias).filter(proposal_type="maintenance")

    if not is_simulation and (
        legacy_roles.exists()
        or legacy_proposals.exists()
        or legacy_templates.exists()
        or legacy_bindings.exists()
    ):
        raise RuntimeError("检测到旧管理员角色或提案语义；请先明确重置对应 world。")

    if is_simulation:
        if legacy_roles.count() > 1 or (
            legacy_roles.exists()
            and Role.objects.using(database_alias).filter(
                organization__role_catalog_key="member-role-catalog",
                name="管理员",
            ).exists()
        ):
            raise RuntimeError("检测到冲突的管理员角色事实；请重置仿真 world 后重试。")
        legacy_roles.update(name="管理员")
        legacy_proposals.update(proposal_type="administration")
        legacy_bindings.update(proposal_type="administration")
        legacy_templates.update(code="administrator_matter", name="管理事务")


class Migration(migrations.Migration):
    dependencies = [("core", "0047_deliberatorexampolicy_active_slot_and_more")]

    operations = [
        migrations.RunPython(rename_administrator_authority_facts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="proposal",
            name="proposal_type",
            field=models.CharField(
                choices=[
                    ("member_admission", "成员准入"),
                    ("role_appointment", "角色任命"),
                    ("role_revocation", "角色卸任"),
                    ("rule", "规则"),
                    ("policy", "政策"),
                    ("budget", "预算"),
                    ("project", "项目"),
                    ("statement", "声明"),
                    ("community", "社区共议"),
                    ("administration", "管理事务"),
                ],
                max_length=32,
                verbose_name="提案类型",
            ),
        ),
    ]
