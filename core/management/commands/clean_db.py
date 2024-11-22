from django.core.management.base import BaseCommand
from core.models import Journalist, NewsPageCategory

class Command(BaseCommand):
    help = 'Remove journalists with unwanted terms in their names'

    def handle(self, *args, **options):
        # List of partial strings to check for
        unwanted_terms = ['.com', 'staff', 'team', 'reporters', 'Associated Press']
        
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
