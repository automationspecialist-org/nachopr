from django.shortcuts import render
from core.models import NewsSource, NewsPage, Journalist

def home(request):
    news_sources_count = NewsSource.objects.count()
    news_pages_count = NewsPage.objects.count()
    journalist_count = Journalist.objects.count()
    context = {
        'news_sources_count': news_sources_count,
        'news_pages_count': news_pages_count,
        'journalist_count': journalist_count
    }
    return render(request, 'core/home.html', context=context)
