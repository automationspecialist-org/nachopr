from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db.models.signals import m2m_changed
from django.dispatch import receiver


class NewsSource(models.Model):
    url = models.URLField(unique=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    last_crawled = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(max_length=255, null=True, blank=True)
    priority = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    

class Journalist(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    sources = models.ManyToManyField(NewsSource, related_name='journalists')
    slug = models.SlugField(unique=True)
    # Remove unique=True from URLs since empty values should be allowed
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
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    

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
        article_categories = NewsPageCategory.objects.filter(
            pages__journalists=self
        ).distinct()
        self.categories.set(article_categories)


class NewsPageCategory(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class NewsPage(models.Model):
    url = models.URLField(unique=True)
    title = models.CharField(max_length=500)
    content = models.TextField()
    source = models.ForeignKey(NewsSource, on_delete=models.CASCADE, related_name='pages')
    journalists = models.ManyToManyField(Journalist, related_name='articles')
    processed = models.BooleanField(default=False)
    categories = models.ManyToManyField(NewsPageCategory, related_name='pages')
    is_news_article = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True, blank=True)
    published_date = models.DateField(null=True, blank=True)


    def __str__(self):
        return self.title
    
    def update_search_vector(self):
        vector = SearchVector('title', weight='A') + SearchVector('content', weight='B')
        NewsPage.objects.filter(pk=self.pk).update(search_vector=vector)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_search_vector()
    
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
    
    def __str__(self):
        return self.name


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
    

@receiver(m2m_changed, sender=NewsPage.journalists.through)
def sync_journalist_categories(sender, instance, action, **kwargs):
    """Sync categories when articles are added/removed from journalist"""
    if action in ["post_add", "post_remove", "post_clear"]:
        for journalist in instance.journalists.all():
            journalist.sync_categories()
    
