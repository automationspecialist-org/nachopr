from django.db import migrations
from pgvector.django import VectorField

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0033_remove_journalist_embedding'),  # Replace with your previous migration
    ]

    operations = [
        migrations.AddField(
            model_name='journalist',
            name='embedding',
            field=VectorField(dimensions=1536, null=True),
        ),
        migrations.AddField(
            model_name='newspage',
            name='embedding',
            field=VectorField(dimensions=1536, null=True),
        ),
    ]