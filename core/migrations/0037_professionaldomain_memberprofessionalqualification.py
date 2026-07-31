# 成员专业资格权威模型迁移。

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_task_standard_minutes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfessionalDomain",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=64, unique=True, verbose_name="领域代码")),
                ("name", models.CharField(max_length=100, verbose_name="领域名称")),
                ("description", models.TextField(blank=True, verbose_name="领域说明")),
                ("status", models.CharField(choices=[("active", "启用"), ("archived", "已归档")], default="active", max_length=32, verbose_name="状态")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "专业领域",
                "verbose_name_plural": "专业领域",
                "ordering": ["code"],
                "db_table": "core_professional_domain",
            },
        ),
        migrations.CreateModel(
            name="MemberProfessionalQualification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("active", "有效"), ("revoked", "已撤销"), ("expired", "已过期")], default="active", max_length=32, verbose_name="状态")),
                ("external_confirmation_source", models.CharField(help_text="记录外部面试、考试、执照核验或其他确认来源；系统不实现其评估流程。", max_length=255, verbose_name="外部确认来源")),
                ("confirmed_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="确认时间")),
                ("valid_from", models.DateTimeField(default=django.utils.timezone.now, verbose_name="生效时间")),
                ("valid_until", models.DateTimeField(blank=True, null=True, verbose_name="失效时间")),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="撤销时间")),
                ("notes", models.TextField(blank=True, verbose_name="备注")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("confirmed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_professional_qualifications", to="core.member", verbose_name="确认人")),
                ("domain", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="member_qualifications", to="core.professionaldomain", verbose_name="专业领域")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="professional_qualifications", to="core.member", verbose_name="成员")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="revoked_professional_qualifications", to="core.member", verbose_name="撤销处理人")),
            ],
            options={
                "verbose_name": "成员专业资格",
                "verbose_name_plural": "成员专业资格",
                "db_table": "core_member_professional_qualification",
                "indexes": [
                    models.Index(fields=["member", "domain", "status"], name="core_member_member__271525_idx"),
                    models.Index(fields=["domain", "status", "valid_until"], name="core_member_domain__9d759c_idx"),
                    models.Index(fields=["valid_from", "valid_until"], name="core_member_valid_f_cc8786_idx"),
                ],
            },
        ),
    ]
