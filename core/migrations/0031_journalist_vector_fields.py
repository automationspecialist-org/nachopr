from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0030_add_journalist_vector_fields'),
    ]

    operations = [
        # Create the vector extension if it doesn't exist
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector;',
            reverse_sql='DROP EXTENSION IF EXISTS vector;'
        ),
        
        # Create the index only
        migrations.RunSQL(
            sql="""
            DROP INDEX IF EXISTS journalist_embedding_idx;
            CREATE INDEX journalist_embedding_idx 
            ON core_journalist USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS journalist_embedding_idx;
            """
        ),
    ]