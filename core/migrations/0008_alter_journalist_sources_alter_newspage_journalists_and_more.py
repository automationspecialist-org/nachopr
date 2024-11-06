# Generated by Django 5.1.2 on 2024-11-06 14:49

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_journalist_x_profile_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='journalist',
            name='sources',
            field=models.ManyToManyField(related_name='journalists', to='core.newssource'),
        ),
        migrations.AlterField(
            model_name='newspage',
            name='journalists',
            field=models.ManyToManyField(related_name='articles', to='core.journalist'),
        ),
        migrations.AlterField(
            model_name='newspage',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pages', to='core.newssource'),
        ),
    ]
