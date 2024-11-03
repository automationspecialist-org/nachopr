import asyncio
from django.core.management.base import BaseCommand
from core.tasks import fetch_website


class Command(BaseCommand):
    help = 'Crawls a website and extracts links'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='URL to crawl')

    def handle(self, *args, **options):
        url = options['url']
        asyncio.run(fetch_website(url))
