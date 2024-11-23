from django.db import migrations
from django.contrib.postgres.search import SearchVectorField

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0031_journalist_vector_fields'),
    ]

    operations = [
        # These operations won't actually create the fields (they already exist),
        # but will tell Django that they're supposed to be there
        
        migrations.AddField(
            model_name='journalist',
            name='search_vector',
            field=SearchVectorField(null=True),
        ),
    ]