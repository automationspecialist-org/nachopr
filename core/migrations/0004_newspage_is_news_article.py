# Generated by Django 5.1.3 on 2024-11-16 12:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_remove_newspage_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='newspage',
            name='is_news_article',
            field=models.BooleanField(default=False),
        ),
    ]