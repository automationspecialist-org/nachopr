# Generated by Django 5.1.3 on 2024-11-18 17:59

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_pricingplan_customuser_pricing_plan'),
    ]

    operations = [
        migrations.RenameField(
            model_name='pricingplan',
            old_name='product_id',
            new_name='polar_id',
        ),
    ]
