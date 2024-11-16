from django import template
from djstripe.models import Subscription
from django.utils import timezone

register = template.Library()

@register.simple_tag
def get_subscription_status(user):
    if not user.is_authenticated:
        return 'anonymous'
    
    subscription = Subscription.objects.filter(customer__subscriber=user).last()
    
    if not subscription:
        return 'no_subscription'
        
    if subscription.trial_end and subscription.trial_end > timezone.now():
        return 'trial'
    elif subscription.status == 'active':
        return 'active'
    elif subscription.trial_end and subscription.trial_end < timezone.now():
        return 'trial_expired'
    
    return 'inactive'