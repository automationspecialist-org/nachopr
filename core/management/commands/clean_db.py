from django.core.management.base import BaseCommand
from core.models import Journalist, NewsPageCategory, NewsPage
from urllib.parse import urlparse

class Command(BaseCommand):
    help = 'Clean database: remove unwanted journalists and mark root domain pages'

    def handle(self, *args, **options):
        # List of partial strings to check for
        unwanted_terms = ['.com', 'staff', 'team', 'reporters', 'press']
        
        # Keep track of how many journalists are removed
        removed_count = 0
        
        # Check each term
        for term in unwanted_terms:
            # Find and delete journalists with the term in their name
            journalists = Journalist.objects.filter(name__icontains=term)
            count = journalists.count()
            journalists.delete()
            removed_count += count
            self.stdout.write(f'Removed {count} journalists containing "{term}"')
            
        self.stdout.write(self.style.SUCCESS(f'Successfully removed {removed_count} total journalists'))
        
        # Remove specific NewsPageCategory
        try:
            category = NewsPageCategory.objects.get(name='New Categories Needed')
            category.delete()
            self.stdout.write(f'Removed NewsPageCategory "New Categories Needed"')
        except NewsPageCategory.DoesNotExist:
            self.stdout.write('NewsPageCategory "New Categories Needed" not found')

        # Update root domain pages
        updated_count = 0
        for page in NewsPage.objects.all():
            parsed_url = urlparse(page.url)
            path = parsed_url.path.rstrip('/')
            
            if path == '' or path == '/':
                page.is_news_article = False
                page.save(update_fields=['is_news_article'])
                updated_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Updated {updated_count} root domain pages'))

