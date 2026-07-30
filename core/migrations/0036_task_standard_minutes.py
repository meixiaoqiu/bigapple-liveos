from decimal import Decimal, ROUND_HALF_UP

import django.core.validators
from django.db import migrations, models


def hours_to_minutes(apps, schema_editor):
    Task = apps.get_model("core", "Task")
    database_alias = schema_editor.connection.alias
    tasks = list(Task.objects.using(database_alias).all())
    for task in tasks:
        task.standard_minutes = max(
            1,
            int(
                (task.standard_minutes * Decimal("60")).quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_UP,
                )
            ),
        )
    Task.objects.using(database_alias).bulk_update(tasks, ["standard_minutes"])


def minutes_to_hours(apps, schema_editor):
    Task = apps.get_model("core", "Task")
    database_alias = schema_editor.connection.alias
    tasks = list(Task.objects.using(database_alias).all())
    for task in tasks:
        task.standard_minutes = Decimal(task.standard_minutes) / Decimal("60")
    Task.objects.using(database_alias).bulk_update(tasks, ["standard_minutes"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_alter_creditaccount_member"),
    ]

    operations = [
        migrations.RenameField(
            model_name="task",
            old_name="standard_hours",
            new_name="standard_minutes",
        ),
        migrations.RunPython(hours_to_minutes, minutes_to_hours),
        migrations.AlterField(
            model_name="task",
            name="standard_minutes",
            field=models.PositiveIntegerField(
                help_text="完成任务所需的标准整数分钟数。",
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="标准工时（分钟）",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=models.Q(("standard_minutes__gte", 1)),
                name="core_task_standard_minutes_gte_1",
            ),
        ),
    ]
