# Generated by Django 5.1.3 on 2024-11-18 16:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_journalist_email_status'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customuser',
            name='customer',
        ),
        migrations.RemoveField(
            model_name='customuser',
            name='subscription',
        ),
        migrations.AddField(
            model_name='customuser',
            name='polar_customer_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='polar_subscription_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='journalist',
            name='email_status',
            field=models.CharField(choices=[('guessed', 'Guessed (60%)'), ('guessed_by_third_party', 'Guessed by Third Party (70%)'), ('verified', 'Verified (99%)')], default='guessed', max_length=32),
        ),
    ]