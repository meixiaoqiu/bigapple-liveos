import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


OLD_ROLE_NAMES = ("正式成员", "议事者", "维护者", "治理成员", "治理管理员")


def prepare_clean_authority_baseline(apps, schema_editor):
    """仿真 world 清除旧基线；真实和控制数据库发现旧数据时失败关闭。"""

    Proposal = apps.get_model("core", "Proposal")
    Role = apps.get_model("core", "Role")
    database_alias = schema_editor.connection.alias
    proposals = Proposal.objects.using(database_alias)
    legacy_roles = Role.objects.using(database_alias).filter(name__in=OLD_ROLE_NAMES)
    is_simulation = (
        getattr(settings, "SITE_WORLD_TYPE", "") == "simulation"
        or database_alias.startswith("simulation")
    )

    if is_simulation:
        ProposalExecution = apps.get_model("core", "ProposalExecution")
        RoleAssignment = apps.get_model("core", "RoleAssignment")
        SystemEvent = apps.get_model("core", "SystemEvent")
        Task = apps.get_model("core", "Task")
        CredentialGrant = apps.get_model("core", "CredentialGrant")

        RoleAssignment.objects.using(database_alias).update(
            source_proposal=None,
            source_proposal_execution=None,
        )
        Task.objects.using(database_alias).update(
            source_proposal=None,
            source_proposal_execution=None,
        )
        CredentialGrant.objects.using(database_alias).update(
            source_proposal=None,
            source_proposal_execution=None,
        )
        ProposalExecution.objects.using(database_alias).all().delete()
        proposals.all().delete()

        legacy_role_ids = list(legacy_roles.values_list("pk", flat=True))
        SystemEvent.objects.using(database_alias).filter(
            actor_role_assignment__role_id__in=legacy_role_ids,
        ).update(actor_role_assignment=None)
        RoleAssignment.objects.using(database_alias).filter(
            role_id__in=legacy_role_ids,
        ).delete()
        Role.objects.using(database_alias).filter(
            appointment_electorate_role_id__in=legacy_role_ids,
        ).update(appointment_electorate_role=None)
        legacy_roles.delete()
        return

    if proposals.exists():
        raise RuntimeError("检测到旧提案数据；请明确重置当前 world 后再应用新选民规则迁移。")
    if legacy_roles.exists():
        raise RuntimeError("检测到旧规范角色数据；请明确重置当前 world 后再应用正式命名迁移。")


class Migration(migrations.Migration):
    dependencies = [("core", "0040_organization_role_catalog_key")]

    operations = [
        migrations.RunPython(prepare_clean_authority_baseline, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ElectorateRuleTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=64, unique=True, verbose_name="稳定代码")),
                ("name", models.CharField(max_length=64, verbose_name="中文名称")),
                ("status", models.CharField(choices=[("active", "启用"), ("inactive", "停用")], default="active", max_length=16, verbose_name="状态")),
                ("description", models.TextField(blank=True, verbose_name="说明")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={"verbose_name": "选民规则模板", "verbose_name_plural": "选民规则模板", "db_table": "core_electorate_rule_template"},
        ),
        migrations.CreateModel(
            name="ElectorateRuleVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField(verbose_name="版本")),
                ("condition_json", models.JSONField(help_text="仅允许由 ALL、ANY、NOT 和已注册选择器组成的条件树。", verbose_name="结构化条件")),
                ("parameter_schema_json", models.JSONField(blank=True, default=dict, help_text="声明提案创建时允许填写的参数；不得接受任意条件树。", verbose_name="开放参数约束")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="core.electorateruletemplate", verbose_name="规则模板")),
            ],
            options={"verbose_name": "选民规则版本", "verbose_name_plural": "选民规则版本", "db_table": "core_electorate_rule_version", "ordering": ("template__code", "-version")},
        ),
        migrations.CreateModel(
            name="ProposalTypeElectorateRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proposal_type", models.CharField(max_length=32, verbose_name="提案类型")),
                ("minimum_condition_json", models.JSONField(blank=True, default=dict, help_text="创建提案时必须保留的制度条件；空对象表示模板本身已经完整约束。", verbose_name="最低必要条件")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="proposal_type_bindings", to="core.electorateruletemplate", verbose_name="允许的规则模板")),
            ],
            options={"verbose_name": "提案类型选民规则", "verbose_name_plural": "提案类型选民规则", "db_table": "core_proposal_type_electorate_rule"},
        ),
        migrations.AddConstraint(
            model_name="electorateruleversion",
            constraint=models.UniqueConstraint(fields=("template", "version"), name="unique_electorate_rule_version"),
        ),
        migrations.AddConstraint(
            model_name="proposaltypeelectoraterule",
            constraint=models.UniqueConstraint(fields=("proposal_type", "template"), name="unique_proposal_type_rule"),
        ),
        migrations.RemoveIndex(model_name="proposal", name="core_propos_elector_6cd432_idx"),
        migrations.RemoveField(model_name="proposal", name="electorate_policy"),
        migrations.AddField(
            model_name="proposal",
            name="electorate_rule_snapshot_json",
            field=models.JSONField(default=dict, help_text="规范化后的实际条件树和开放参数，用于当前资格重检与审计。", verbose_name="选民规则快照"),
        ),
        migrations.AddField(
            model_name="proposal",
            name="electorate_rule_version",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="proposals", to="core.electorateruleversion", verbose_name="选民规则版本"),
        ),
        migrations.AlterField(
            model_name="proposal",
            name="electorate_rule_version",
            field=models.ForeignKey(help_text="创建提案时固定的规则版本；后续模板更新不得改变本提案语义。", on_delete=django.db.models.deletion.PROTECT, related_name="proposals", to="core.electorateruleversion", verbose_name="选民规则版本"),
        ),
        migrations.AddIndex(
            model_name="proposal",
            index=models.Index(fields=["electorate_rule_version", "status"], name="core_propos_rule_status_idx"),
        ),
        migrations.RenameField(model_name="capacityassessment", old_name="current_formal_members", new_name="current_covenanters"),
        migrations.RenameField(model_name="capacityassessment", old_name="current_candidate_members", new_name="current_contributors"),
        migrations.AlterField(
            model_name="proposal",
            name="proposal_type",
            field=models.CharField(choices=[("member_admission", "成员准入"), ("role_appointment", "角色任命"), ("role_revocation", "角色卸任"), ("rule", "规则"), ("policy", "政策"), ("budget", "预算"), ("project", "项目"), ("statement", "声明"), ("community", "社区共议"), ("maintenance", "典守事务")], max_length=32, verbose_name="提案类型"),
        ),
    ]
