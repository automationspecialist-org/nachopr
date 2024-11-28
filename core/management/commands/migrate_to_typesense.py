from django.core.management.base import BaseCommand
from core.models import Journalist
from core.typesense_config import init_typesense
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Migrate existing journalists to Typesense'

    def handle(self, *args, **options):
        # Initialize Typesense schema
        init_typesense()
        
        # Get all journalists
        journalists = Journalist.objects.all()
        total = journalists.count()
        
        self.stdout.write(f"Starting migration of {total} journalists to Typesense...")
        
        # Migrate each journalist
        for i, journalist in enumerate(journalists, 1):
            try:
                journalist.update_typesense()
                if i % 100 == 0:
                    self.stdout.write(f"Migrated {i}/{total} journalists...")
            except Exception as e:
                logger.error(f"Error migrating journalist {journalist.id}: {str(e)}")
        
        self.stdout.write(self.style.SUCCESS(f"Successfully migrated {total} journalists to Typesense")) 