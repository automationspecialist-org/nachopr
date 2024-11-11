from core.tasks import create_social_sharing_image
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Generate the social sharing image'

    def handle(self, *args, **kwargs):
        create_social_sharing_image()