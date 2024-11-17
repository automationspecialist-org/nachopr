from django.core.management.base import BaseCommand
from core.tasks import guess_journalist_email_addresses

class Command(BaseCommand):
    help = 'Guess email addresses for journalists without emails'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100_000,
            help='Maximum number of journalists to process'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        self.stdout.write(f'Guessing email addresses for up to {limit} journalists...')
        
        guess_journalist_email_addresses(limit=limit)
        
        self.stdout.write(self.style.SUCCESS('Successfully completed email guessing'))
