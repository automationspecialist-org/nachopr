from django.core.management.base import BaseCommand
from core.tasks import crawl_news_sources_sync, run_journalist_processing

class Command(BaseCommand):
    help = 'Crawl all news sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit the number of pages to crawl',
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        self.stdout.write('Starting news source crawl...')
        crawl_news_sources_sync(limit=limit)
        self.stdout.write(self.style.SUCCESS('Successfully crawled all news sources'))
        self.stdout.write('Starting journalist processing...')
        run_journalist_processing()
        self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
