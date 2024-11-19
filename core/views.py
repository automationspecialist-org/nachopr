import os
from dotenv import load_dotenv
from django.shortcuts import get_object_or_404, render
import requests
from core.models import NewsSource, NewsPage, Journalist, NewsPageCategory, PricingPlan, SavedSearch, SavedList
from django.db.models import Prefetch
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import login
# Create a session for the user
from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
import json
from django.db import transaction
import random
import string
from .polar import PolarClient


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

@login_required
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
    starttime = timezone.now()
    is_subscriber = request.user.is_authenticated
    query = request.GET.get('q', '')
    country = request.GET.get('country', '')
    source_id = request.GET.get('source', '')
    category_id = request.GET.get('category', '')
    
    # Start with all journalists
    results = Journalist.objects.prefetch_related(
        'sources',
        Prefetch(
            'articles',
            queryset=NewsPage.objects.prefetch_related(
                Prefetch(
                    'categories',
                    queryset=NewsPageCategory.objects.all(),
                    to_attr='unique_categories'
                )
            ),
            to_attr='prefetched_articles'
        )
    ).distinct()
    
    # Apply filters
    if query:
        results = results.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(articles__categories__name__icontains=query) |
            Q(sources__name__icontains=query)
        ).order_by('name').distinct()
    if country:
        results = results.filter(country=country)
    if source_id:
        results = results.filter(sources__id=source_id)
    if category_id:
        results = results.filter(articles__categories__id=category_id).distinct()

    # debug:
    #if not settings.PROD:
    print(f"Query: {query}")
    
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
        
        filtered_results = results[:10]  # Limit results for non-subscribers
    else:
        request.user.searches_count += 1
        if not request.user.has_searched:
            request.user.has_searched = True
        request.user.save()

        #request.user.customuser.searches_count += 1
        print(request.user.searches_count)
        # Add pagination for subscribers
        page_number = request.GET.get('page', 1)
        paginator = Paginator(results, 10)  # Show 10 results per page
        filtered_results = paginator.get_page(page_number)

    unfiltered_results_count = results.count()
    time_taken = timezone.now() - starttime
    print(f'time taken: {time_taken}')
    return render(
        request, 'core/search_results.html',
        {'results': filtered_results, 'time_taken': time_taken, 'unfiltered_results_count': unfiltered_results_count})


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
    pricing_plans = PricingPlan.objects.filter(is_archived=False)
    return render(request, 'core/pricing.html', {'pricing_plans': pricing_plans})


@login_required
def dashboard(request):
    if request.user.is_authenticated:
        context = {
            'checklist': {
                'has_searched': request.user.has_searched,
                'has_created_list': request.user.has_created_list,
                'has_saved_journalist': request.user.has_saved_journalist,
                'has_retrieved_email': request.user.has_retrieved_email,
                'has_exported_list': request.user.has_exported_list,
            }
        }
        return render(request, 'core/dashboard.html', context)
    return redirect('login')

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
def polar_webhook(request):
    try:
        polar = PolarClient.get_client()
        event = polar.webhooks.construct_event(
            request.body,
            request.headers.get('Polar-Signature')
        )
        
        # Handle subscription events
        if event.type.startswith('subscription.'):
            User = get_user_model()
            subscription_id = event.data.get('id')
            user = User.objects.filter(polar_subscription_id=subscription_id).first()
            
            if user:
                if event.type == 'subscription.deleted':
                    user.polar_subscription_id = None
                    user.credits = 0
                elif event.type in ['subscription.created', 'subscription.updated']:
                    user.credits = event.data.get('metadata', {}).get('credits', 0)
                user.save()
                
        return HttpResponse(status=200)
        
    except Exception as e:
        return HttpResponse(status=400)


def generate_random_password(length=12):
    """Generate a random password of given length"""
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for _ in range(length))

def create_new_user(email):
    """
    Create a new user with the given email.
    Returns a tuple of (user, password) where password is only set for new users.
    """
    User = get_user_model()
    random_password = generate_random_password()
    username = email.split('@')[0]
    
    # Ensure username is unique
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
        
    user = User.objects.create_user(
        username=username,
        email=email,
        password=random_password
    )
    
    # Send welcome email with password reset link
    send_welcome_email(user)
    
    return user, random_password

def subscription_confirm(request):
    session_id = request.GET.get('session_id')
    print(f"DEBUG: Received session_id: {session_id}")
    
    if not session_id:
        print("DEBUG: No session_id provided")
        return redirect('home')
    
    try:
        # Get checkout session
        polar = PolarClient.get_client()
        print(f"DEBUG: Getting checkout using client_get with session_id: {session_id}")
        checkout = polar.checkouts.custom.get(id=session_id)
        print(f"DEBUG: Checkout retrieved: {checkout}")
        
        if checkout.status != 'succeeded':
            print(f"DEBUG: Payment incomplete - status: {checkout.status}")
            return render(request, 'core/subscription_confirm.html', {
                'error': 'Payment incomplete'
            })

        # Get or create user based on checkout email
        customer_email = checkout.customer_email
        if not customer_email:
            print("DEBUG: No customer email provided in checkout")
            return render(request, 'core/subscription_confirm.html', {
                'error': 'No email provided'
            })
            
        User = get_user_model()
        user = User.objects.filter(email=customer_email).first()
        print(f"DEBUG: Existing user found: {user is not None}")
        
        if not user:
            try:
                user, password = create_new_user(customer_email)
                print(f"DEBUG: Created new user: {user.email}")
            except Exception as e:
                print(f"DEBUG: Error creating user: {str(e)}")
                return render(request, 'core/subscription_confirm.html', {
                    'error': f'Error creating user account: {str(e)}'
                })
            
        # Update user subscription
        try:
            user.polar_subscription_id = checkout.subscription_id
            user.subscription_status = 'active'
            user.credits = checkout.metadata.get('credits', 0)
            user.save()
            print(f"DEBUG: Updated subscription for user: {user.email}")
            
            # If user wasn't logged in, log them in now
            if not request.user.is_authenticated:
                # Use allauth's login method
                from allauth.account.utils import perform_login
                print("DEBUG: Attempting to login user with allauth")
                perform_login(
                    request, 
                    user,
                    email_verification='optional',  # or 'mandatory' if you require email verification
                    redirect_url=None,
                    signal_kwargs={
                        "signup": False,  # True if this is a new user
                    }
                )
                print(f"DEBUG: Successfully logged in user with allauth: {user.email}")
            
        except Exception as e:
            print(f"DEBUG: Error updating subscription: {str(e)}")
            return render(request, 'core/subscription_confirm.html', {
                'error': f'Error updating subscription: {str(e)}'
            })
        
        return render(request, 'core/subscription_confirm.html', {
            'success': True,
            'is_new_user': user.date_joined > timezone.now() - timezone.timedelta(minutes=5)
        })
        
    except Exception as e:
        print(f"DEBUG: Unexpected error: {str(e)}")
        return render(request, 'core/subscription_confirm.html', {
            'error': str(e)
        })


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
def settings_view(request):
    return render(request, 'core/settings.html')


@login_required
def saved_lists(request):
    lists = SavedList.objects.filter(user=request.user)
    context = {'lists': lists}
    return render(request, "core/saved_lists.html", context=context)

@login_required
def save_to_list(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        list_id = data.get('list_id')
        new_list_name = data.get('new_list_name')
        journalists = data.get('journalists', [])

        if not list_id:
            # New list being created
            request.user.has_created_list = True
        
        if journalists:
            request.user.has_saved_journalist = True
        
        request.user.save()
        
        if list_id:
            saved_list = SavedList.objects.get(id=list_id, user=request.user)
        else:
            saved_list = SavedList.objects.create(
                user=request.user,
                name=new_list_name
            )

        # Add journalists to the list
        journalist_ids = [j['id'] for j in journalists]
        saved_list.journalists.add(*journalist_ids)

        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'error'}, status=400)


@login_required
def single_saved_list(request, id):
    list = get_object_or_404(SavedList, id=id)
    context = {'list': list}
    return render(request, 'core/single_saved_list.html', context=context)


@login_required
def health(request):
    if not request.user.is_staff:
        return HttpResponse(status=403)  # Forbidden
    
    journalist_email_count = Journalist.objects.exclude(email_address__isnull=True).exclude(email_address='').count()
    news_article_count = NewsPage.objects.filter(is_news_article=True).count()
    
    return HttpResponse(
        f"OK - {journalist_email_count} journalists with email, {news_article_count} news articles", 
        status=200
    )
    