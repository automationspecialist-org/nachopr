from django.core.management.base import BaseCommand
from core.models import Journalist
from core.typesense_config import init_typesense
import logging
from django.db import transaction

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Migrate existing journalists to Typesense'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Number of journalists to process in each batch'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        
        # Initialize Typesense schema
        init_typesense()
        
        # Get total count
        total = Journalist.objects.count()
        self.stdout.write(f"Starting migration of {total} journalists to Typesense...")
        
        # Process in batches
        processed = 0
        while processed < total:
            batch = Journalist.objects.all()[processed:processed + batch_size]
            with transaction.atomic():
                for journalist in batch:
                    try:
                        journalist.update_typesense()
                    except Exception as e:
                        logger.error(f"Error migrating journalist {journalist.id}: {str(e)}")
            
            processed += batch_size
            self.stdout.write(f"Migrated {min(processed, total)}/{total} journalists...")
        
        self.stdout.write(self.style.SUCCESS(f"Successfully migrated {total} journalists to Typesense")) 