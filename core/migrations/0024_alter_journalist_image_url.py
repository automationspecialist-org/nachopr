# Generated by Django 5.1.3 on 2024-11-19 13:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_alter_journalist_profile_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='journalist',
            name='image_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
