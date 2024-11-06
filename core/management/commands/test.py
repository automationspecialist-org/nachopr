from django.core.management.base import BaseCommand
from core.tasks import extract_all_journalists_with_gpt

class Command(BaseCommand):
    help = 'Extract all journalists using GPT-4 on Azure'

    def handle(self, *args, **kwargs):
        extract_all_journalists_with_gpt()
