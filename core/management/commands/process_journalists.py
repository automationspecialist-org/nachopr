import time
from django.core.management.base import BaseCommand
from core.tasks import process_all_journalists_sync

class Command(BaseCommand):
    help = 'Process all journalists'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Number of pages to process'
        )
        parser.add_argument(
            '--reprocess',
            action='store_true',
            default=False,
            help='Reprocess already processed pages'
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting journalist processing...')
        try:
            while True:
                process_all_journalists_sync(
                    limit=options['limit'],
                    re_process=options['reprocess']
                )
                self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
                self.stdout.write('Waiting 30 seconds before next iteration...')
                time.sleep(30)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nStopping journalist processing...'))
