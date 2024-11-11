from django.core.management.base import BaseCommand
from core.tasks import process_all_journalists_sync

class Command(BaseCommand):
    help = 'Process all journalists'

    def handle(self, *args, **options):
        self.stdout.write('Starting journalist processing...')
        process_all_journalists_sync(limit=10)
        self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
