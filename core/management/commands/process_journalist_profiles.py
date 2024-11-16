from django.core.management.base import BaseCommand
from core.tasks import process_journalist_descriptions_sync

class Command(BaseCommand):
    help = 'Process descriptions for journalists that have profile URLs but no descriptions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Number of journalists to process'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        self.stdout.write(self.style.SUCCESS(f'Starting to process {limit} journalist profiles...'))
        
        try:
            process_journalist_descriptions_sync(limit=limit)
            self.stdout.write(self.style.SUCCESS('Successfully processed journalist profiles'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error processing journalist profiles: {str(e)}'))