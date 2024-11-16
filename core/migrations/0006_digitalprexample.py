# Generated by Django 5.1.3 on 2024-11-16 13:07

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_savedlist'),
    ]

    operations = [
        migrations.CreateModel(
            name='DigitalPRExample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                ('url', models.URLField()),
                ('published_date', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('news_page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pr_examples', to='core.newspage')),
            ],
            options={
                'verbose_name': 'Digital PR Example',
                'verbose_name_plural': 'Digital PR Examples',
                'ordering': ['-published_date'],
            },
        ),
    ]
