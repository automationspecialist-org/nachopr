from django.core.management.base import BaseCommand
from core.tasks import update_page_embeddings_sync


class Command(BaseCommand):
    help = 'Updates embeddings for NewsPages that do not have them yet'

    def handle(self, *args, **options):
        self.stdout.write('Starting embedding updates...')
        update_page_embeddings_sync(limit=100)  # Process 100 pages at a time
        self.stdout.write(self.style.SUCCESS('Successfully updated embeddings'))
