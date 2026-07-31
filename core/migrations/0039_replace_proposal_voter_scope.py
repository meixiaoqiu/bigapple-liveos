import django.db.models.deletion
from django.db import migrations, models


def reject_legacy_proposal_data(apps, schema_editor):
    """拒绝把旧选民范围提案静默解释为新制度提案。"""

    Proposal = apps.get_model("core", "Proposal")
    if Proposal.objects.exists():
        raise RuntimeError(
            "检测到旧制度提案数据。请重置到干净基线后再应用角色与权限迁移；"
            "迁移不会将旧选民范围静默改写为新选民政策。"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_alter_roleassignment_source_type_and_feedback_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposal",
            name="electorate_policy",
            field=models.CharField(
                choices=[
                    ("general_deliberation", "普通议事"),
                    ("professional_deliberation", "专业议事"),
                ],
                default="general_deliberation",
                help_text="普通议事由有效正式成员和议事者组成；专业议事还需要对应专业资格。",
                max_length=32,
                verbose_name="选民政策",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="proposal",
            name="professional_domain",
            field=models.ForeignKey(
                blank=True,
                help_text="仅专业议事提案可以指定且必须指定一个启用中的专业领域。",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="proposals",
                to="core.professionaldomain",
                verbose_name="专业领域",
            ),
        ),
        migrations.RunPython(reject_legacy_proposal_data, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="proposal",
            name="voter_scope_organization",
        ),
        migrations.RemoveField(
            model_name="proposal",
            name="voter_scope_role",
        ),
        migrations.RemoveField(
            model_name="proposal",
            name="voter_scope_type",
        ),
        migrations.AddIndex(
            model_name="proposal",
            index=models.Index(fields=["electorate_policy", "status"], name="core_propos_elector_6cd432_idx"),
        ),
    ]
