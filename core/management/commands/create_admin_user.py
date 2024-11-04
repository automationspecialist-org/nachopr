from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create a superuser named dunc if it does not exist'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        if not User.objects.filter(username='dunc').exists():
            User.objects.create_superuser('dunc', 'd@uncan.net', 'Trowel-Acutely3-Elixir')
            self.stdout.write(self.style.SUCCESS('Superuser dunc created successfully.'))
        else:
            self.stdout.write(self.style.WARNING('Superuser dunc already exists.'))

        # Create staff user 'gee' if it doesn't exist
        if not User.objects.filter(username='gee').exists():
            User.objects.create_user('gee', 'georgiahackett@live.com', 'Gown-Salutary-Spoof9', is_staff=True)
            self.stdout.write(self.style.SUCCESS('Staff user gee created successfully.'))
        else:
            self.stdout.write(self.style.WARNING('Staff user gee already exists.'))
