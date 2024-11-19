from django.core.management.base import BaseCommand
from core.polar import sync_pricing_plans

class Command(BaseCommand):
    help = 'Syncs pricing plans from Polar'

    def handle(self, *args, **options):
        self.stdout.write('Syncing pricing plans...')
        sync_pricing_plans()
        self.stdout.write(self.style.SUCCESS('Successfully synced pricing plans'))
