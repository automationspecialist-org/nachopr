# Generated by Django 5.1.3 on 2024-11-17 20:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_customuser_brand_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalist',
            name='email_status',
            field=models.CharField(choices=[('guessed', 'Guessed'), ('guessed_by_third_party', 'Guessed by Third Party'), ('verified', 'Verified')], default='guessed', max_length=32),
        ),
    ]
