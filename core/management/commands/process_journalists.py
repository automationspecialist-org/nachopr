from django.core.management.base import BaseCommand
from core.tasks import run_journalist_processing

class Command(BaseCommand):
    help = 'Process all journalists'

    def handle(self, *args, **options):
        self.stdout.write('Starting journalist processing...')
        run_journalist_processing()
        self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
