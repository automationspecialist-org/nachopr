# Generated by Django 5.1.2 on 2024-11-06 14:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_journalist_country'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalist',
            name='x_profile_url',
            field=models.URLField(blank=True, null=True, unique=True),
        ),
    ]