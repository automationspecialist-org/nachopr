from polar_sdk import Polar
from django.conf import settings
from core.models import PricingPlan  # Import PricingPlan from models.py

class PolarClient:
    _instance = None
    
    @classmethod
    def get_client(cls):
        if cls._instance is None:
            cls._instance = Polar(
                access_token=settings.POLAR_ACCESS_TOKEN,
                server=settings.POLAR_SERVER,
            )
        return cls._instance


def sync_pricing_plans():
    """
    Syncs pricing plans from Polar API to local PricingPlan model.
    """
    # Get Polar client instance
    client = PolarClient.get_client()
    organization_id = settings.POLAR_ORGANIZATION_ID
    
    try:
        # Get list of products from Polar with organization_id
        response = client.products.list(organization_id=organization_id)
        
        if response is not None:
            while True:
                # Process each product in the current page
                products = response.result.items
                for product in products:
                    print(f"DEBUG: Processing product: {product.name}")
                    # Create or update PricingPlan
                    pricing_plan, created = PricingPlan.objects.update_or_create(
                        polar_id=product.id,
                        defaults={
                            'name': product.name,
                            'description': product.description,
                            'is_recurring': product.is_recurring,
                            'is_archived': product.is_archived,
                        }
                    )
                    
                    # Process the first price if available
                    if product.prices:
                        price = product.prices[0]
                        pricing_plan.price_amount = price.price_amount
                        pricing_plan.price_currency = price.price_currency
                        pricing_plan.recurring_interval = price.recurring_interval.value
                        pricing_plan.save()
                
                # Get next page if available
                response = response.next()
                if response is None:
                    break
                    
            return True
            
    except Exception as e:
        print(f"Error syncing pricing plans: {str(e)}")
        return False


