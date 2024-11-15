import os
from dotenv import load_dotenv
from django.shortcuts import render
import requests
from core.models import CustomUser, NewsSource, NewsPage, Journalist, NewsPageCategory, SavedSearch
from djstripe.models import Product
from django.db.models import Prefetch
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.conf import settings
import stripe
from djstripe.models import Customer, Subscription
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

load_dotenv()


def home(request):
    news_sources_count = NewsSource.objects.filter(pages__isnull=False).distinct().count()
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
    categories = NewsPageCategory.objects.all().order_by('name')
    # Get languages through the sources relationship
    languages = NewsSource.objects.exclude(language__isnull=True).values_list('language', flat=True).distinct()
    
    context = {
        'countries': countries,
        'sources': sources,
        'categories': categories,
        'languages': languages,
        'turnstile_site_key': os.getenv('CLOUDFLARE_TURNSTILE_SITE_KEY'),
    }
    return render(request, 'core/app_search.html', context=context)


def search_results(request):
    is_subscriber = request.user.is_authenticated
    query = request.GET.get('q', '')
    country = request.GET.get('country', '')
    source_id = request.GET.get('source', '')
    category_id = request.GET.get('category', '')
    
    # Start with all journalists
    results = Journalist.objects.prefetch_related(
        'sources',
        Prefetch(
            'articles__categories',
            queryset=NewsPageCategory.objects.all().distinct()
        )
    )
    
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
                        {'error': 'Please complete the security check',
                         'reset_turnstile': True})
        
        # Verify token with Cloudflare
        data = {
            'secret': os.getenv('CLOUDFLARE_TURNSTILE_SECRET_KEY'),
            'response': token,
            'remoteip': request.META.get('REMOTE_ADDR'),
        }
        response = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify', data=data)
        
        if not response.json().get('success', False):
            return render(request, 'core/search_results.html', 
                        {'error': 'Security check failed',
                         'reset_turnstile': True})
        
        results = results[:3]  # Limit results for non-subscribers
    else:
        #request.user.customuser.searches_count += 1

        #request.user.customuser.searches_count += 1
        #print(request.user.searches_count)
        # Add pagination for subscribers
        page_number = request.GET.get('page', 1)
        paginator = Paginator(results, 10)  # Show 10 results per page
        results = paginator.get_page(page_number)
    
    return render(request, 'core/search_results.html', {'results': results})


def free_media_list(request):
    news_sources_count = NewsSource.objects.filter(pages__isnull=False).distinct().count()
    news_pages_count = NewsPage.objects.count()
    journalist_count = Journalist.objects.count()
    categories = NewsPageCategory.objects.all().order_by('name')
    
    context = {
        'news_sources_count': news_sources_count,
        'news_pages_count': news_pages_count,
        'journalist_count': journalist_count,
        'categories': categories,
    }
    return render(request, 'core/free_media_list.html', context=context)


def signup(request):
    return render(request, 'core/signup.html')

def terms_of_service(request):
    return render(request, 'core/terms_of_service.html')

def privacy_policy(request):
    return render(request, 'core/privacy_policy.html')

def refund_policy(request):
    return render(request, 'core/refund_policy.html')

def pricing(request):
    products = Product.objects.all()
    return render(request, 'core/pricing.html', {'products': products})


def dashboard(request):
    return render(request, 'core/dashboard.html')

@login_required
def save_search(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        query = request.POST.get('q', '')
        countries = request.POST.getlist('countries', [])
        sources = request.POST.getlist('source', [])
        categories = request.POST.getlist('category', [])
        
        saved_search = SavedSearch.objects.create(user=request.user, name=name, query=query)
        saved_search.countries.set(countries)
        saved_search.sources.set(sources)
        saved_search.categories.set(categories)
        return redirect('saved_searches')

@login_required
def saved_searches(request):
    searches = request.user.saved_searches.all()
    return render(request, 'core/saved_searches.html', {'searches': searches})

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)
        
    # Handle the event
    if event.type == "customer.subscription.created":
        handle_subscription_created(event)
    elif event.type == "customer.subscription.updated":
        # Handle subscription update
        pass
    elif event.type == "customer.subscription.deleted":
        # Handle subscription deletion
        pass
    
    return HttpResponse(status=200)

def handle_subscription_created(event):
    """
    Handle the customer.subscription.created webhook from Stripe
    """
    # Get customer email from the event
    customer_email = event.data.object.customer_email
    
    User = get_user_model()
    
    # Check if user exists
    user = User.objects.filter(email=customer_email).first()
    
    if not user:
        # Create new user with a random password
        # They can reset it later via email
        random_password = User.objects.make_random_password()
        username = customer_email.split('@')[0]
        # Ensure username is unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
            
        user = User.objects.create_user(
            username=username,
            email=customer_email,
            password=random_password
        )
        
        # TODO: Send welcome email with password reset link
        
    # Link Stripe Customer to User
    customer = Customer.objects.get(id=event.data.object.customer)
    user.customer = customer
    
    # Link Subscription to User
    subscription = Subscription.objects.get(id=event.data.object.id)
    user.subscription = subscription
    
    user.save()

def send_welcome_email(user):
    """Send welcome email with password reset link to new users."""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    password_reset_url = f"/reset/{uid}/{token}/"
    
    context = {
        'user': user,
        'password_reset_url': password_reset_url,
    }
    
    message = render_to_string('core/email/welcome.html', context)
    
    send_mail(
        'Welcome to NachoPR',
        message,
        'support@nachopr.com',
        [user.email],
        fail_silently=False,
    )


@login_required
def settings(request):
    return render(request, 'core/settings.html')


@login_required
def saved_lists(request):
    return render(request, "core/saved_lists.html")