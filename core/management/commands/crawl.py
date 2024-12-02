from django.core.management.base import BaseCommand
from core.tasks import crawl_news_sources_sync, process_all_journalists_sync
import time

class Command(BaseCommand):
    help = 'Continuously crawl news sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain-limit',
            type=int,
            default=1,
            help='Limit the number of domains to crawl per iteration',
        )
        parser.add_argument(
            '--page-limit',
            type=int,
            default=2000,
            help='Limit the number of pages to crawl per domain',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=1,  # 1 second
            help='Seconds to wait between crawl iterations',
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting continuous news source crawler...')
        try:
            while True:
                crawl_news_sources_sync(
                    domain_limit=options['domain_limit'],
                    page_limit=options['page_limit']
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed iteration, waiting {options['interval']} seconds..."
                    )
                )
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nStopping crawler...'))
