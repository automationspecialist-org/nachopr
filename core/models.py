from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import AbstractUser

class NewsSource(models.Model):
    url = models.URLField(unique=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    last_crawled = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(max_length=255, null=True, blank=True)

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
    profile_url = models.URLField(null=True, blank=True, unique=True)
    image_url = models.URLField(null=True, blank=True, unique=True)
    country = models.CharField(max_length=255, null=True, blank=True)
    x_profile_url = models.URLField(null=True, blank=True, unique=True)
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


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
    title = models.CharField(max_length=255)
    content = models.TextField()
    source = models.ForeignKey(NewsSource, on_delete=models.CASCADE, related_name='pages')
    journalists = models.ManyToManyField(Journalist, related_name='articles')
    processed = models.BooleanField(default=False)
    categories = models.ManyToManyField(NewsPageCategory, related_name='pages')
    is_news_article = models.BooleanField(default=False)

    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        self.slug = slugify(self.title)
        super().save(*args, **kwargs)
    

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
    subscription = models.ForeignKey(
        'djstripe.Subscription',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='custom_users'
    )
    customer = models.ForeignKey(
        'djstripe.Customer',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='custom_users'
    )

    searches_count = models.IntegerField(default=0)
    has_searched = models.BooleanField(default=False)
    has_created_list = models.BooleanField(default=False)
    has_saved_journalist = models.BooleanField(default=False)
    has_retrieved_email = models.BooleanField(default=False)
    has_exported_list = models.BooleanField(default=False)

    @property
    def is_subscribed(self):
        """Return True if the user has an active subscription."""
        return self.subscription is not None and self.subscription.status in ('active', 'trialing')

    @property
    def subscription_status(self):
        """Return the subscription status or None if no subscription exists."""
        if self.subscription:
            return self.subscription.status
        return None

    @property
    def subscription_period_end(self):
        """Return the end date of the current subscription period."""
        if self.subscription and self.subscription.current_period_end:
            return self.subscription.current_period_end
        return None

    def get_stripe_subscription_url(self):
        """Get URL for managing subscription in Stripe Customer Portal."""
        if not self.customer:
            return None
        return f"https://billing.stripe.com/p/session/{self.customer.id}"


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

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-published_date']
        verbose_name = 'Digital PR Example'
        verbose_name_plural = 'Digital PR Examples'
