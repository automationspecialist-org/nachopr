# Generated by Django 5.1.3 on 2024-11-20 11:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_alter_journalist_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='digitalprexample',
            name='confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='credits',
            field=models.IntegerField(default=100),
        ),
    ]
