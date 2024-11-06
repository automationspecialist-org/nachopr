from django.shortcuts import render
from core.models import NewsSource, NewsPage, Journalist

def home(request):
    news_sources_count = NewsSource.objects.count()
    news_pages_count = NewsPage.objects.count()
    journalist_count = Journalist.objects.count()
    example_journalists = (Journalist.objects
                         .filter(image_url__isnull=False, description__isnull=False)
                         .prefetch_related('sources')[:9])
    context = {
        'news_sources_count': news_sources_count,
        'news_pages_count': news_pages_count,
        'journalist_count': journalist_count,
        'example_journalists': example_journalists
    }
    return render(request, 'core/home.html', context=context)


def search(request):
    is_subscriber = request.user.is_authenticated
    query = request.GET.get('q')
    if not query:
       return render(request, 'core/search.html')
    if not is_subscriber:
        results = Journalist.objects.filter(name__icontains=query)[:3]
    else:
        results = Journalist.objects.filter(name__icontains=query)
    return render(request, 'core/search.html', {'results': results})


def free_media_list(request):
    news_sources_count = NewsSource.objects.count()
    news_pages_count = NewsPage.objects.count()
    journalist_count = Journalist.objects.count()
    
    context = {
        'news_sources_count': news_sources_count,
        'news_pages_count': news_pages_count,
        'journalist_count': journalist_count,
    }
    return render(request, 'core/free_media_list.html', context=context)


def signup(request):
    return render(request, 'core/signup.html')