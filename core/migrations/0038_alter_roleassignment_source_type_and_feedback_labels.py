import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_professionaldomain_memberprofessionalqualification"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memberapplication",
            name="decided_by",
            field=models.ForeignKey(
                blank=True,
                help_text="执行准入提案或拒绝的维护者；不再表示单人审核。",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="decided_member_applications",
                to="core.member",
                verbose_name="决议人",
            ),
        ),
        migrations.AlterField(
            model_name="roleassignment",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("direct", "直接任命"),
                    ("self_application", "本人申请"),
                    ("proposal", "提案执行"),
                    ("initialization", "初始化"),
                    ("system", "系统产生"),
                ],
                default="direct",
                help_text="说明这条角色任命由直接任命、本人申请、提案执行、初始化或系统规则产生。",
                max_length=32,
                verbose_name="来源类型",
            ),
        ),
        migrations.AlterField(
            model_name="communityfeedback",
            name="official_response",
            field=models.TextField(blank=True, help_text="维护者的公开回应。", verbose_name="官方回应"),
        ),
        migrations.AlterField(
            model_name="communityfeedback",
            name="responded_by",
            field=models.ForeignKey(
                blank=True,
                help_text="最近回应该反馈的维护者。",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="responded_community_feedbacks",
                to="core.member",
                verbose_name="回应人",
            ),
        ),
    ]
