# Generated by Django 5.1.3 on 2024-11-24 19:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_alter_savedlist_options_savedlist_updated_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='newssource',
            name='url',
            field=models.URLField(max_length=500, unique=True),
        ),
    ]
