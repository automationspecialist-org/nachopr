from django import template

register = template.Library()

@register.simple_tag
def get_subscription_status(user):
    if not user.is_authenticated:
        return 'anonymous'
    
    if not user.polar_subscription_id:
        return 'no_subscription'
        
    if user.subscription_status == 'active':
        return 'active'
    elif user.subscription_status == 'trialing':
        return 'trial'
    
    return 'inactive'