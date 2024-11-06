from django.core.management.base import BaseCommand
from django.db import IntegrityError
from core.models import NewsSource
import csv
import os
from django.conf import settings

class Command(BaseCommand):
    help = 'Adds news sources to the database from sites.csv'

    def handle(self, *args, **kwargs):
        csv_path = os.path.join(settings.BASE_DIR, 'core', 'initial_data', 'sites.csv')
        
        with open(csv_path, 'r') as file:
            reader = csv.reader(file, delimiter=',')
            next(reader)  # Skip header row
            
            for row in reader:
                if not row:  # Skip empty rows
                    continue
                    
                handle, name, url, location, timezone, country, language = row
                
                try:
                    instance, created = NewsSource.objects.get_or_create(
                        slug=handle,
                    defaults={
                        "name": name,
                        "url": url,
                        "location": location,
                        "timezone": timezone,
                        "country": country,
                        "language": language
                    }
                )
                
                    if created:
                        self.stdout.write(self.style.SUCCESS(f'Created news source: {instance.name}'))
                    else:
                        self.stdout.write(self.style.WARNING(f'News source already exists: {instance.name}'))
                except IntegrityError:
                    self.stdout.write(self.style.WARNING(f'News source already exists: {instance.name}'))
