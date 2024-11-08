# Generated by Django 5.1.2 on 2024-11-08 17:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_alter_journalist_sources_alter_newspage_journalists_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='NewsPageCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(unique=True)),
            ],
        ),
        migrations.AddField(
            model_name='newspage',
            name='categories',
            field=models.ManyToManyField(related_name='pages', to='core.newspagecategory'),
        ),
    ]
