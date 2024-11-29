from django.utils import timezone
from datetime import timedelta
import logging
from core.typesense_config import get_typesense_client, init_typesense

logger = logging.getLogger(__name__)

def update_journalist_in_typesense(journalist):
    """
    Update a single journalist in Typesense.
    This is used by both the signal handler and sync tasks.
    """
    try:
        journalist.update_typesense()
    except Exception as e:
        logger.error(f"Error updating Typesense for journalist {journalist.id}: {str(e)}")
        # Don't raise the exception to prevent disrupting the operation

def sync_recent_journalists():
    """
    Sync recently modified journalists to Typesense.
    Returns the number of journalists processed.
    """
    from core.models import Journalist  # Import here to avoid circular imports
    
    try:
        # Initialize Typesense if needed
        init_typesense()
        
        # Get all journalists modified in the last hour
        recent_journalists = Journalist.objects.filter(
            updated_at__gte=timezone.now() - timedelta(hours=1)
        )
        
        if not recent_journalists.exists():
            logger.info("No journalists updated in the last hour")
            return 0
        
        count = recent_journalists.count()
        logger.info(f"Found {count} journalists to sync")
        
        # Update each journalist in Typesense
        for journalist in recent_journalists:
            update_journalist_in_typesense(journalist)
        
        logger.info(f"Completed Typesense sync of {count} journalists")
        return count
        
    except Exception as e:
        logger.error(f"Error during Typesense sync: {str(e)}")
        raise 