# Generated by Django 5.1.3 on 2024-11-16 15:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_customuser_has_access_to_journalists'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='brand_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
