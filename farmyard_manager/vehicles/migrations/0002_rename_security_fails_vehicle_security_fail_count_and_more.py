# Generated by Django 5.0.12 on 2025-03-12 11:28

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='vehicle',
            old_name='security_fails',
            new_name='security_fail_count',
        ),
        migrations.AddField(
            model_name='blacklist',
            name='blacklist_date',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='vehicle',
            name='is_removed',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='blacklist',
            name='vehicle',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='blacklist', to='vehicles.vehicle'),
        ),
        migrations.AlterField(
            model_name='securityfail',
            name='failure_date',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='securityfail',
            name='vehicle',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='security_fails', to='vehicles.vehicle'),
        ),
    ]
