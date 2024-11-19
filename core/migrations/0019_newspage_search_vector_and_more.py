# Generated by Django 5.1.3 on 2024-11-19 11:11

import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_pricingplan_checkout_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='newspage',
            name='search_vector',
            field=django.contrib.postgres.search.SearchVectorField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='newspage',
            index=django.contrib.postgres.indexes.GinIndex(fields=['search_vector'], name='core_newspa_search__bb1acd_gin'),
        ),
    ]