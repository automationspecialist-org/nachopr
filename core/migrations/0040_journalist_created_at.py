# Generated by Django 5.1.3 on 2024-11-28 17:10

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_alter_newspage_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalist',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]