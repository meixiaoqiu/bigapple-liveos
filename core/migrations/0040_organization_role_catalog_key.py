from django.db import migrations, models


ROLE_CATALOG_ORGANIZATION_NAME = "成员资格与职责"
ROLE_CATALOG_ORGANIZATION_KEY = "member-role-catalog"


def promote_existing_catalog_organization(apps, schema_editor):
    """为唯一的旧目录组织补充稳定标识；歧义数据必须先重置。"""

    Organization = apps.get_model("core", "Organization")
    organization_ids = list(
        Organization.objects.filter(name=ROLE_CATALOG_ORGANIZATION_NAME)
        .order_by("pk")
        .values_list("pk", flat=True)[:2]
    )
    if len(organization_ids) > 1:
        raise RuntimeError("存在多个成员资格与职责目录组织；请重置到干净基线后再迁移。")
    if organization_ids:
        Organization.objects.filter(pk=organization_ids[0]).update(
            role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_replace_proposal_voter_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="role_catalog_key",
            field=models.CharField(
                blank=True,
                help_text="仅规范成员资格与职责目录使用的稳定内部标识；其他组织必须留空。",
                max_length=64,
                null=True,
                unique=True,
                verbose_name="角色目录标识",
            ),
        ),
        migrations.RunPython(promote_existing_catalog_organization, migrations.RunPython.noop),
    ]
