from django.contrib import admin
from .models import NewsSource, NewsPage
from .tasks import crawl_news_sources_sync
from django.contrib import messages

@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    actions = ['crawl_selected_sources']
    
    def crawl_selected_sources(self, request, queryset):
        try:
            crawl_news_sources_sync()
            messages.success(request, "Crawling completed successfully!")
        except Exception as e:
            messages.error(request, f"Error during crawling: {str(e)}")
    
    crawl_selected_sources.short_description = "Crawl selected news sources"

@admin.register(NewsPage)
class NewsPageAdmin(admin.ModelAdmin):
    pass

