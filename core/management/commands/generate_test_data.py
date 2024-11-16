from core.models import Journalist
from django.conf import settings

def fake_journalist() -> dict:
    """
    Generate fake data to populate an instance of Journalist.
    """
    journalist_dict = {

    }

    return journalist_dict



def generate_batch(num_journalists: int = 100):
    if settings.PROD:
        if not input("It seems you are creating fake data in production. ARE YOU SURE? Enter yes to proceed") == 'yes':
            print("Cancelled")
            return
    for i in range(num_journalists):
        Journalist.objects.create(defaults=fake_journalist())