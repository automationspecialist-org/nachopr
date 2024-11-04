from django.contrib import admin
from .models import NewsSource
from .models import NewsPage

admin.site.register(NewsSource)
admin.site.register(NewsPage)
