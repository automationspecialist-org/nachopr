import os
from dotenv import load_dotenv
from django.shortcuts import render
import requests

load_dotenv()
from core.models import NewsSource, NewsPage, Journalist, NewsPageCategory

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
    # Get unique countries and sources for filters
    countries = Journalist.objects.exclude(country__isnull=True).values_list('country', flat=True).distinct()
    sources = NewsSource.objects.all()
    categories = NewsPageCategory.objects.all()
    
    context = {
        'countries': countries,
        'sources': sources,
        'categories': categories,
        'turnstile_site_key': os.getenv('CLOUDFLARE_TURNSTILE_SITE_KEY'),
    }
    return render(request, 'core/search.html', context=context)


def search_results(request):
    is_subscriber = request.user.is_authenticated
    query = request.GET.get('q', '')
    country = request.GET.get('country', '')
    source_id = request.GET.get('source', '')
    category_id = request.GET.get('category', '')
    
    # Start with all journalists
    results = Journalist.objects.all()
    
    # Apply filters
    if query:
        results = results.filter(name__icontains=query)
    if country:
        results = results.filter(country=country)
    if source_id:
        results = results.filter(sources__id=source_id)
    if category_id:
        results = results.filter(articles__categories__id=category_id).distinct()
    
    # Handle non-subscribers
    if not is_subscriber:
        token = request.GET.get('cf-turnstile-response')
        if not token:
            return render(request, 'core/search_results.html', 
                        {'error': 'Please complete the security check'})
        
        # Verify token with Cloudflare
        data = {
            'secret': os.getenv('CLOUDFLARE_TURNSTILE_SECRET_KEY'),
            'response': token,
            'remoteip': request.META.get('REMOTE_ADDR'),
        }
        response = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify', data=data)
        
        if not response.json().get('success', False):
            return render(request, 'core/search_results.html', 
                        {'error': 'Security check failed'})
        
        results = results[:3]  # Limit results for non-subscribers
    
    return render(request, 'core/search_results.html', {'results': results})


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