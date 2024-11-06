from django.core.management.base import BaseCommand
from core.tasks import extract_all_journalists_with_gpt

class Command(BaseCommand):
    help = 'Process all journalists'

    def handle(self, *args, **options):
        self.stdout.write('Starting journalist processing...')
        extract_all_journalists_with_gpt()
        self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
