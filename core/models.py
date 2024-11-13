from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import AbstractUser
import djstripe

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
    slug = models.SlugField(unique=True)
    processed = models.BooleanField(default=False)
    categories = models.ManyToManyField(NewsPageCategory, related_name='pages')

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
        'djstripe.Subscription', null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The user's Stripe Subscription object, if it exists"
    )
    customer = models.ForeignKey(
        'djstripe.Customer', null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The user's Stripe Customer object, if it exists"
    )


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
