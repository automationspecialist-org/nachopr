from django.core.management.base import BaseCommand
from core.tasks import find_digital_pr_examples

class Command(BaseCommand):
    help = 'Find news pages that match digital PR patterns and create DigitalPRExample entries'

    def handle(self, *args, **options):
        self.stdout.write('Finding digital PR examples...')
        find_digital_pr_examples()
        self.stdout.write(self.style.SUCCESS('Successfully found digital PR examples'))
