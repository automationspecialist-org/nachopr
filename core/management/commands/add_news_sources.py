from django.core.management.base import BaseCommand
from core.models import NewsSource


NEWS_SOURCES = [
    {
        "url": "https://www.theguardian.com/",
        "name": "The Guardian"
    },
    {
        "url": "https://www.dailymail.co.uk/home/index.html", 
        "name": "Daily Mail"
    }
]

class Command(BaseCommand):
    help = 'Adds news sources to the database'

    def handle(self, *args, **kwargs):
        for src in NEWS_SOURCES:
            instance, created = NewsSource.objects.get_or_create(url=src["url"], defaults={"name": src["name"]})
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created news source: {instance.url}'))
            else:
                self.stdout.write(self.style.WARNING(f'News source already exists: {instance.url}'))
