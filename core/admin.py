from django.contrib import admin
from .models import NewsPageCategory, NewsSource, NewsPage, Journalist, CustomUser, SavedList, DigitalPRExample
from .models import BlogPost
from .tasks import crawl_news_sources_sync
from django.contrib import messages

admin.site.register(Journalist)
admin.site.register(NewsPageCategory)
admin.site.register(CustomUser)
admin.site.register(SavedList)
admin.site.register(DigitalPRExample)
admin.site.register(BlogPost)

@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    actions = ['crawl_selected_sources']
    
    def crawl_selected_sources(self, request, queryset):
        try:
            crawl_news_sources_sync()
            messages.success(request, "Crawl started in background!")
        except Exception as e:
            messages.error(request, f"Error starting crawl: {str(e)}")
    
    crawl_selected_sources.short_description = "Crawl selected news sources"

@admin.register(NewsPage)
class NewsPageAdmin(admin.ModelAdmin):
    pass


