from core.tasks import categorize_news_pages_with_gpt
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Categorize news pages with GPT'

    def handle(self, *args, **kwargs):
        categorize_news_pages_with_gpt()