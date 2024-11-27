from core.tasks import test_openai_connection
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Test the OpenAI connection'

    def handle(self, *args, **kwargs):
        test_openai_connection()