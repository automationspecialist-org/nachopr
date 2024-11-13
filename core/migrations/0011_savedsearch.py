# Generated by Django 5.1.3 on 2024-11-13 20:10

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_customuser'),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedSearch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('query', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('categories', models.ManyToManyField(related_name='saved_categories', to='core.newspagecategory')),
                ('countries', models.ManyToManyField(related_name='saved_countries', to='core.journalist')),
                ('sources', models.ManyToManyField(related_name='saved_sources', to='core.newssource')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_searches', to='core.customuser')),
            ],
        ),
    ]