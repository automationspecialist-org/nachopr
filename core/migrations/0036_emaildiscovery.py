# Generated by Django 5.1.3 on 2024-11-23 13:36

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_journalist_email_search_with_hunter_tried'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailDiscovery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('source_domain', models.CharField(max_length=255)),
                ('journalist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_discoveries', to='core.journalist')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_discoveries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Email Discovery',
                'verbose_name_plural': 'Email Discoveries',
                'ordering': ['-created_at'],
            },
        ),
    ]
