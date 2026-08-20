from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_alter_systemevent_event_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposalresolution",
            name="decided_by",
            field=models.ForeignKey(
                blank=True,
                help_text="实名记录触发本次确定性结果判定的成员；迁移前历史记录可以为空。",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="proposal_resolutions",
                to="core.member",
                verbose_name="判定触发人",
            ),
        ),
    ]
