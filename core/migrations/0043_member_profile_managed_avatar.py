from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0042_rename_core_propos_rule_status_idx_core_propos_elector_1b905e_idx_and_more")]

    operations = [
        migrations.AddField(
            model_name="memberpublicprofile",
            name="avatar_key",
            field=models.CharField(
                blank=True,
                help_text="系统生成的当前头像私有对象标识；为空时使用默认头像，不得由表单直接填写。",
                max_length=255,
                verbose_name="当前头像对象Key",
            ),
        ),
        migrations.AddField(
            model_name="memberpublicprofile",
            name="avatar_sha256",
            field=models.CharField(
                blank=True,
                help_text="处理后 WebP 内容的 SHA-256，用于一致性检查，不作为公开地址。",
                max_length=64,
                verbose_name="当前头像SHA-256",
            ),
        ),
        migrations.AddField(
            model_name="memberpublicprofile",
            name="avatar_size",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="处理后 WebP 的字节数；使用默认头像时为空。",
                null=True,
                verbose_name="当前头像字节数",
            ),
        ),
        migrations.AddField(
            model_name="memberpublicprofile",
            name="avatar_updated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="当前头像最后成功切换或移除的时间，与其它公开资料更新时间分开记录。",
                null=True,
                verbose_name="头像更新时间",
            ),
        ),
        # Existing external URLs are deliberately not fetched or migrated.
        migrations.RemoveField(model_name="memberpublicprofile", name="avatar_url"),
    ]
