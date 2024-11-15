from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create a superuser named dunc if it does not exist'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        
        # Let's first verify we're using the correct model
        self.stdout.write(f"Using user model: {User.__name__}")
        
        if not User.objects.filter(username='dunc').exists():
            User.objects.create_superuser(
                username='dunc',
                email='d@uncan.net',
                password='Trowel-Acutely3-Elixir',
                first_name='Duncan',
                last_name='Example'
            )
            self.stdout.write(self.style.SUCCESS('Superuser dunc created successfully.'))
        else:
            self.stdout.write(self.style.WARNING('Superuser dunc already exists.'))

        if not User.objects.filter(username='gee').exists():
            User.objects.create_user(
                username='gee',
                email='georgiahackett@live.com',
                password='Gown-Salutary-Spoof9',
                is_staff=True,
                first_name='Georgia',
                last_name='Example'
            )
            self.stdout.write(self.style.SUCCESS('Staff user gee created successfully.'))
        else:
            self.stdout.write(self.style.WARNING('Staff user gee already exists.'))
