from django.core.management.base import BaseCommand
from core.tasks import guess_journalist_email_addresses, find_emails_with_hunter_io

class Command(BaseCommand):
    help = 'Guess email addresses for journalists without emails'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=1,
            help='Maximum number of journalists to process'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        self.stdout.write(f'Guessing email addresses for up to {limit} journalists...')
        
        find_emails_with_hunter_io(limit=limit)
        
        self.stdout.write(self.style.SUCCESS('Successfully completed email guessing'))
