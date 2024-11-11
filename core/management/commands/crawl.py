from django.core.management.base import BaseCommand
from core.tasks import crawl_news_sources_sync, process_all_journalists_sync

class Command(BaseCommand):
    help = 'Crawl all news sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain-limit',
            type=int,
            help='Limit the number of domains to crawl',
        )
        parser.add_argument(
            '--page-limit',
            type=int,
            help='Limit the number of pages to crawl',
        )

    def handle(self, *args, **options):
        domain_limit = options.get('domain_limit')
        page_limit = options.get('page_limit')
        self.stdout.write('Starting news source crawl...')
        crawl_news_sources_sync(domain_limit=domain_limit, page_limit=page_limit)
        self.stdout.write(self.style.SUCCESS('Successfully crawled all news sources'))
        self.stdout.write('Starting journalist processing...')
        process_all_journalists_sync()
        self.stdout.write(self.style.SUCCESS('Successfully processed all journalists'))
