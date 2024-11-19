from algoliasearch_django import AlgoliaIndex
from algoliasearch_django.decorators import register
from .models import Journalist

@register(Journalist)
class JournalistIndex(AlgoliaIndex):
    fields = [
        'name',
        'description',
        'country',
        'email_address',
    ]
    
    index_name = 'journalists'
    
    settings = {
        'searchableAttributes': [
            'name',
            'description',
            'sources.name',
            'articles.title',
            'articles.snippet',
            'country'
        ],
        'attributesForFaceting': [
            'country',
            'sources.id',
            'categories.id'
        ]
    }

    custom_ranking = ['desc(articles_count)']
    
    def get_raw_record(self, instance):
        """Override get_raw_record to add computed fields"""
        record = super(JournalistIndex, self).get_raw_record(instance)
        
        # Add related data with minimal fields to save space
        record['sources'] = [{
            'id': source.id,
            'name': source.name,
            'country': source.country
        } for source in instance.sources.all().select_related()]
        
        # Get categories with minimal fields
        categories = instance.get_unique_categories()
        record['categories'] = [{
            'id': category.id,
            'name': category.name
        } for category in categories]
        
        # Add articles data with larger snippets (up to 5000 chars)
        record['articles'] = [{
            'id': article.id,
            'title': article.title,
            'snippet': self.get_article_snippet(article.content, max_length=5000),
            'published_date': article.published_date.isoformat() if article.published_date else None
        } for article in instance.articles.all().select_related()[:5]]  # Limit to 5 most recent articles
        
        record['articles_count'] = len(record['articles'])
        
        return record

    def get_article_snippet(self, content, max_length=5000):
        """Create a shortened version of the article content"""
        if not content:
            return ''
        # Take first max_length characters and cut at the last complete word
        snippet = content[:max_length].rsplit(' ', 1)[0]
        return snippet + '...' if len(content) > max_length else snippet