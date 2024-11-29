from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from pgvector.django import VectorField
import logging
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.utils.typesense_utils import update_journalist_in_typesense
import re

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small dimensions


class NewsSource(models.Model):
    url = models.URLField(unique=True, max_length=500)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    last_crawled = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(max_length=255, null=True, blank=True)
    priority = models.BooleanField(default=False)
    categories = models.ManyToManyField('NewsPageCategory', related_name='sources', blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    

    def sync_categories(self):
        """Sync categories based on the source's news pages"""
        page_categories = NewsPageCategory.objects.filter(
            pages__source=self
        ).distinct()
        self.categories.set(page_categories)


class Journalist(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    sources = models.ManyToManyField(NewsSource, related_name='journalists')
    slug = models.SlugField(unique=True)
    profile_url = models.URLField(null=True, blank=True, max_length=500)
    image_url = models.URLField(null=True, blank=True, max_length=500)
    country = models.CharField(max_length=255, null=True, blank=True)
    x_profile_url = models.URLField(null=True, blank=True)
    email_address = models.EmailField(blank=True, null=True, unique=True)
    email_status = models.CharField(
        max_length=32,
        choices=[
            ('guessed', 'Guessed (60%)'),
            ('guessed_by_third_party', 'Guessed by Third Party (70%)'),
            ('verified', 'Verified (99%)')
        ],
        default='guessed'
    )
    categories = models.ManyToManyField('NewsPageCategory', related_name='journalists', blank=True)
    email_search_with_hunter_tried = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    
    search_vector = SearchVectorField(null=True)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True)

    def __str__(self):
        return self.name

    #def save(self, *args, **kwargs):
    #    self.slug = slugify(self.name)
    #    super().save(*args, **kwargs)
    #    self.update_search_vector()
    

    def has_articles(self):
        """Method to determine if journalist should be indexed"""
        return self.articles.exists()
    

    def get_unique_categories(self):
        """Return unique categories across all articles for this journalist."""
        if hasattr(self, 'prefetched_articles'):
            # Get categories from prefetched articles
            categories = []
            seen = set()
            for article in self.prefetched_articles:
                for category in article.unique_categories:
                    if category.id not in seen:
                        seen.add(category.id)
                        categories.append(category)
            return categories
        else:
            # Fallback if articles aren't prefetched
            return NewsPageCategory.objects.filter(
                pages__journalists=self
            ).distinct()

    def sync_categories(self):
        """Sync categories based on the journalist's articles"""
        logger.info(f"Starting category sync for journalist: {self.name}")
        article_categories = NewsPageCategory.objects.filter(
            pages__journalists=self
        ).distinct()
        logger.info(f"Found categories: {[c.name for c in article_categories]}")
        self.categories.set(article_categories)

    def update_search_vector(self):
        """Update the search vector field"""
        try:
            # First get the related field values
            source_names = ' '.join(self.sources.values_list('name', flat=True))
            category_names = ' '.join(self.categories.values_list('name', flat=True))
            
            # Create concatenated text fields
            vector = SearchVector('name', weight='A') + \
                     SearchVector('description', weight='B') + \
                     SearchVector(models.Value(source_names), weight='C') + \
                     SearchVector(models.Value(category_names), weight='D')
            
            # Update the search vector
            Journalist.objects.filter(pk=self.pk).update(search_vector=vector)
        except Exception as e:
            logger.error(f"Error updating search vector for journalist {self.pk}: {str(e)}")

    def get_text_for_embedding(self):
        """Get text representation of journalist for embedding generation"""
        text_parts = []
        
        if self.name:
            text_parts.append(f"Name: {self.name}")
        
        if self.description:
            text_parts.append(f"Description: {self.description}")
            
        if self.country:
            text_parts.append(f"Country: {self.country}")
            
        # Join all parts with newlines
        return "\n".join(text_parts)

    def clean_content(self, content):
        """Clean article content for indexing"""
        if not content:
            return ""
        # Remove markdown links
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', ' ', content)
        # Remove special characters and extra whitespace
        content = re.sub(r'[\n\r\t]+', ' ', content)
        content = re.sub(r'\s+', ' ', content)
        # Remove escape characters
        content = content.replace('\\', '')
        return content.strip()

    def update_typesense(self, force=False):
        """Update or create document in Typesense"""
        try:
            from .typesense_config import get_typesense_client
            client = get_typesense_client()
            
            # Get article data - order by published_date and ensure is_news_article=True
            articles = self.articles.filter(is_news_article=True).order_by('-published_date', '-id')
            
            # Get article titles and content
            article_titles = []
            article_contents = []
            
            for article in articles[:10]:  # Limit to 10 most recent articles
                if article.title:
                    article_titles.append(article.title)
                if article.content:
                    cleaned_content = self.clean_content(article.content)
                    if cleaned_content:
                        article_contents.append(cleaned_content)
            
            # Debug logging
            logger.info(f"Indexing journalist {self.id} ({self.name}) with {len(article_titles)} articles")
            logger.info(f"Article titles: {article_titles}")
            
            # Concatenate article content, limiting to prevent oversized documents
            article_content = ' '.join(article_contents)[:100000]  # Limit content size to 100KB
            
            document = {
                'id': str(self.id),
                'name': self.name,
                'description': self.description or '',
                'country': self.country or '',
                'sources': list(self.sources.values_list('name', flat=True)),
                'categories': list(self.categories.values_list('name', flat=True)),
                'articles_count': articles.count(),
                'email_status': self.email_status or '',
                'created_at': int(self.created_at.timestamp()) if self.created_at else int(timezone.now().timestamp()),
                'article_titles': article_titles,
                'article_content': article_content,
            }
            
            # Debug logging
            logger.info(f"Document for journalist {self.id}: {document}")
            
            try:
                if force:
                    # If force is True, try to create first
                    try:
                        client.collections['journalists'].documents.create(document)
                    except Exception as e:
                        # If creation fails (document exists), try update
                        client.collections['journalists'].documents[str(self.id)].update(document)
                else:
                    # Try to update first
                    try:
                        client.collections['journalists'].documents[str(self.id)].update(document)
                    except Exception as e:
                        # If update fails (document doesn't exist), create it
                        client.collections['journalists'].documents.create(document)
                
                logger.info(f"Successfully updated/created document for journalist {self.id} in Typesense")
                
            except Exception as e:
                logger.error(f"Error updating/creating document: {str(e)}")
                raise  # Re-raise the exception to be caught by the outer try block
                
        except Exception as e:
            logger.error(f"Error updating journalist {self.id} in Typesense: {str(e)}")
            raise  # Re-raise the exception so it's not silently caught
    
    def delete_from_typesense(self):
        """Delete document from Typesense"""
        try:
            from .typesense_config import get_typesense_client
            client = get_typesense_client()
            client.collections['journalists'].documents[str(self.id)].delete()
        except Exception as e:
            logger.error(f"Error deleting journalist {self.id} from Typesense: {str(e)}")
    
    def save(self, *args, **kwargs):
        # First do the normal save
        super().save(*args, **kwargs)
        # Then update Typesense
        self.update_typesense()
    
    def delete(self, *args, **kwargs):
        # First delete from Typesense
        self.delete_from_typesense()
        # Then do the normal delete
        super().delete(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['country']),
            models.Index(fields=['name']),
            models.Index(fields=['description']),
        ]


class NewsPageCategory(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class NewsPage(models.Model):
    url = models.URLField(unique=True, max_length=500)
    title = models.CharField(max_length=500)
    content = models.TextField()
    source = models.ForeignKey(NewsSource, on_delete=models.CASCADE, related_name='pages')
    journalists = models.ManyToManyField(Journalist, related_name='articles')
    processed = models.BooleanField(default=False)
    categories = models.ManyToManyField(NewsPageCategory, related_name='pages')
    is_news_article = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True, blank=True)
    published_date = models.DateField(null=True, blank=True)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True)

    def __str__(self):
        return self.title
    
    def update_search_vector(self):
        vector = SearchVector('title', weight='A') + SearchVector('content', weight='B')
        NewsPage.objects.filter(pk=self.pk).update(search_vector=vector)

    #def save(self, *args, **kwargs):
    #    super().save(*args, **kwargs)
    #    self.update_search_vector()
    
    class Meta:
        indexes = [
            GinIndex(fields=['search_vector'])
        ]


class PricingPlan(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    credits = models.IntegerField(default=100)
    polar_id = models.CharField(max_length=255)
    is_recurring = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    checkout_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
        verbose_name='groups',
        help_text='The groups this user belongs to.',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True,
        verbose_name='user permissions',
        help_text='Specific permissions for this user.',
    )
    polar_subscription_id = models.CharField(max_length=255, null=True, blank=True)
    polar_customer_id = models.CharField(max_length=255, null=True, blank=True)
    pricing_plan = models.ForeignKey(PricingPlan, on_delete=models.SET_NULL, null=True, blank=True)
    credits = models.IntegerField(default=100)
    searches_count = models.IntegerField(default=0)
    has_searched = models.BooleanField(default=False)
    has_created_list = models.BooleanField(default=False)
    has_saved_journalist = models.BooleanField(default=False)
    has_retrieved_email = models.BooleanField(default=False)
    has_exported_list = models.BooleanField(default=False)
    has_access_to_journalists = models.ManyToManyField(Journalist)

    brand_name = models.CharField(max_length=255, blank=True, null=True)
    @property 
    def is_subscribed(self):
        """Return True if user has an active subscription"""
        if not self.polar_subscription_id:
            return False
            
        try:
            from .polar import PolarClient
            subscription = PolarClient.get_client().users.subscriptions.get(
                id=self.polar_subscription_id
            )
            return subscription.status == 'active'
        except:
            return False

    


class SavedSearch(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='saved_searches')
    name = models.CharField(max_length=255)
    query = models.CharField(max_length=255, blank=True, null=True)
    countries = models.ManyToManyField('Journalist', related_name='saved_countries')
    sources = models.ManyToManyField('NewsSource', related_name='saved_sources')
    categories = models.ManyToManyField('NewsPageCategory', related_name='saved_categories')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name

class SavedList(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='saved_lists')
    name = models.CharField(max_length=255)
    journalists = models.ManyToManyField(Journalist, related_name='saved_lists')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.name} ({self.journalists.count()} journalists)"


class DigitalPRExample(models.Model):
    news_page = models.ForeignKey('NewsPage', on_delete=models.CASCADE, related_name='pr_examples')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    url = models.URLField()
    published_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed = models.BooleanField(default=False)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-published_date']
        verbose_name = 'Digital PR Example'
        verbose_name_plural = 'Digital PR Examples'


class DbStat(models.Model):
    num_journalists = models.IntegerField(default=0)
    num_journalists_added_today = models.IntegerField(default=0)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.date} - {self.num_journalists_added_today} journalists added"
    

#@receiver(m2m_changed, sender=NewsPage.journalists.through)
def sync_journalist_categories(sender, instance, action, **kwargs):
    """Sync categories when articles are added/removed from journalist"""
    logger.info(f"Signal fired: sync_journalist_categories - Action: {action}")
    if action in ["post_add", "post_remove", "post_clear"]:
        for journalist in instance.journalists.all():
            logger.info(f"Syncing categories for journalist: {journalist.name}")
            journalist.sync_categories()

#@receiver(arm2m_changed, sender=NewsPage.categories.through)
def sync_source_categories(sender, instance, action, **kwargs):
    """Sync categories when categories are added/removed from news pages"""
    logger.info(f"Signal fired: sync_source_categories - Action: {action}")
    if action in ["post_add", "post_remove", "post_clear"]:
        logger.info(f"Syncing categories for source: {instance.source.name}")
        instance.source.sync_categories()

#@receiver(m2m_changed, sender=NewsPage.journalists.through)
def sync_journalist_sources_and_categories(sender, instance, action, **kwargs):
    """Sync sources and categories when journalists are added/removed from a page"""
    if action in ["post_add", "post_remove", "post_clear"]:
        for journalist in instance.journalists.all():
            # Add the source to the journalist
            journalist.sources.add(instance.source)
            # Sync categories
            journalist.sync_categories()


class EmailDiscovery(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='email_discoveries')
    journalist = models.ForeignKey(Journalist, on_delete=models.CASCADE, related_name='email_discoveries')
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    source_domain = models.CharField(max_length=255)  # Store which domain was used to find the email
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email Discovery'
        verbose_name_plural = 'Email Discoveries'
        
    def __str__(self):
        return f"{self.journalist.name} - {self.email}"

@receiver(post_save, sender=Journalist)
def update_typesense_on_save(sender, instance, created, **kwargs):
    """
    Signal handler to update Typesense when a journalist is created or updated.
    This ensures real-time updates while the periodic task handles any missed updates.
    """
    update_journalist_in_typesense(instance)
