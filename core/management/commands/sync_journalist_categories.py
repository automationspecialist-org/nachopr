from django.core.management.base import BaseCommand
from core.models import Journalist, NewsSource

class Command(BaseCommand):
    help = 'Syncs categories for all journalists based on their articles'

    def handle(self, *args, **options):
        journalists = Journalist.objects.all()
        total = journalists.count()
        
        self.stdout.write(f"Syncing categories for {total} journalists...")
        
        for i, journalist in enumerate(journalists, 1):
            journalist.sync_categories()
            if i % 100 == 0:  # Progress update every 100 journalists
                self.stdout.write(f"Processed {i}/{total} journalists")
        
        self.stdout.write(self.style.SUCCESS('Successfully synced all journalist categories'))

        for source in NewsSource.objects.all():
            source.sync_categories()