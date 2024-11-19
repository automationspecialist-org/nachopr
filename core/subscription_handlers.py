from django.contrib.auth import get_user_model
from django.db import transaction
from .models import CustomUser

User = get_user_model()

def handle_subscription_created(event):
    """Handle when a new subscription is created"""
    with transaction.atomic():
        subscription_data = event.data
        customer_email = subscription_data.get('customer_email')
        
        user = User.objects.select_for_update().filter(email=customer_email).first()
        if not user:
            return
            
        # Update user subscription details
        user.polar_subscription_id = subscription_data.get('id')
        user.subscription_status = subscription_data.get('status')
        user.subscription_period_end = subscription_data.get('current_period_end')
        
        # Get credits from subscription metadata
        credits = subscription_data.get('metadata', {}).get('email_credits', 0)
        if credits:
            user.credits = int(credits)
            
        user.save()

def handle_subscription_updated(event):
    """Handle when a subscription is updated"""
    with transaction.atomic():
        subscription_data = event.data
        subscription_id = subscription_data.get('id')
        
        user = User.objects.select_for_update().filter(
            polar_subscription_id=subscription_id
        ).first()
        
        if not user:
            return
            
        # Update subscription status and period
        user.subscription_status = subscription_data.get('status')
        user.subscription_period_end = subscription_data.get('current_period_end')
        
        # Update credits if changed
        credits = subscription_data.get('metadata', {}).get('email_credits')
        if credits is not None:
            user.credits = int(credits)
            
        user.save()

def handle_subscription_deleted(event):
    """Handle when a subscription is cancelled/deleted"""
    with transaction.atomic():
        subscription_data = event.data
        subscription_id = subscription_data.get('id')
        
        user = User.objects.select_for_update().filter(
            polar_subscription_id=subscription_id
        ).first()
        
        if not user:
            return
            
        # Clear subscription data
        user.polar_subscription_id = None
        user.subscription_status = 'cancelled'
        user.subscription_period_end = None
        user.credits = 0
        user.save()
