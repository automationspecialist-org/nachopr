from django.conf import settings
import typesense

# Schema for the journalists collection
JOURNALIST_SCHEMA = {
    'name': 'journalists',
    'fields': [
        {'name': 'id', 'type': 'string'},
        {'name': 'name', 'type': 'string'},
        {'name': 'description', 'type': 'string', 'optional': True},
        {'name': 'country', 'type': 'string', 'optional': True, 'facet': True},
        {'name': 'sources', 'type': 'string[]', 'facet': True, 'optional': True},
        {'name': 'categories', 'type': 'string[]', 'facet': True, 'optional': True},
        {'name': 'articles_count', 'type': 'int32', 'optional': True},
        {'name': 'email_status', 'type': 'string', 'optional': True},
        {'name': 'created_at', 'type': 'int64'},
    ],
    'default_sorting_field': 'created_at'
}

def get_typesense_client():
    """Get a configured Typesense client"""
    return typesense.Client({
        'api_key': settings.TYPESENSE_API_KEY,
        'nodes': [{
            'host': 'localhost',  # Using localhost since it's internal
            'port': '8108',
            'protocol': 'http'
        }],
        'connection_timeout_seconds': 2
    })

def init_typesense():
    """Initialize Typesense with our schema"""
    client = get_typesense_client()
    
    # Create collection if it doesn't exist
    try:
        client.collections['journalists'].retrieve()
    except typesense.exceptions.ObjectNotFound:
        client.collections.create(JOURNALIST_SCHEMA) 