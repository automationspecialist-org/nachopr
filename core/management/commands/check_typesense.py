from django.core.management.base import BaseCommand
from core.typesense_config import get_typesense_client, init_typesense
from core.models import Journalist
import json

class Command(BaseCommand):
    help = 'Check Typesense status and collection stats'

    def handle(self, *args, **options):
        try:
            # Initialize Typesense if needed
            init_typesense()
            client = get_typesense_client()
            
            # Get collection stats
            collection_stats = client.collections['journalists'].retrieve()
            self.stdout.write("Collection stats:")
            self.stdout.write(json.dumps(collection_stats, indent=2))
            
            # Get total journalists in database
            db_count = Journalist.objects.count()
            self.stdout.write(f"\nJournalists in database: {db_count}")
            
            # Perform a test search
            search_results = client.collections['journalists'].documents.search({
                'q': '*',
                'query_by': 'name',
                'per_page': 1
            })
            
            self.stdout.write("\nTest search results:")
            self.stdout.write(json.dumps(search_results, indent=2))
            
            # Check health
            health = client.health.retrieve()
            self.stdout.write("\nTypesense health:")
            self.stdout.write(json.dumps(health, indent=2))
            
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {str(e)}")) 