from django.db import models
from django.utils.text import slugify

class NewsSource(models.Model):
    url = models.URLField(unique=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    last_crawled = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    

class Journalist(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    sources = models.ManyToManyField(NewsSource)
    slug = models.SlugField(unique=True)
    profile_url = models.URLField(null=True, blank=True, unique=True)
    image_url = models.URLField(null=True, blank=True, unique=True)
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class NewsPage(models.Model):
    url = models.URLField(unique=True)
    title = models.CharField(max_length=255)
    content = models.TextField()
    source = models.ForeignKey(NewsSource, on_delete=models.CASCADE)
    journalists = models.ManyToManyField(Journalist)
    slug = models.SlugField(unique=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        self.slug = slugify(self.title)
        super().save(*args, **kwargs)
    


