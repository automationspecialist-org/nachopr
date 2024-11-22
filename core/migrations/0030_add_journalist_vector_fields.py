from django.db import migrations
import pgvector.django

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0029_newssource_categories'),
    ]

    operations = [
        # First create the vector extension
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector;',
            reverse_sql='DROP EXTENSION IF EXISTS vector;'
        ),
        
        # Add the embedding field
        migrations.AddField(
            model_name='journalist',
            name='embedding',
            field=pgvector.django.VectorField(dimensions=1536, null=True),
        ),
        
        # Create the index after the column exists
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