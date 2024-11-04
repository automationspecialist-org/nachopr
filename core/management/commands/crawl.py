from django.core.management.base import BaseCommand
from core.tasks import crawl_news_sources_sync

class Command(BaseCommand):
    help = 'Crawl all news sources'

    def handle(self, *args, **options):
        self.stdout.write('Starting news source crawl...')
        crawl_news_sources_sync()
        self.stdout.write(self.style.SUCCESS('Successfully crawled all news sources'))
