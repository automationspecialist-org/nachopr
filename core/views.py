import os
from core.tasks import find_single_email_with_hunter_io
from dotenv import load_dotenv
from django.shortcuts import get_object_or_404, render
import requests
from core.models import CustomUser, NewsSource, NewsPage, Journalist, NewsPageCategory, PricingPlan, SavedSearch, SavedList, EmailDiscovery
from django.db.models import Prefetch
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.db.models import Q
from django.utils import timezone
# Create a session for the user
import json
from django.db import transaction
import random
import string
from .polar import PolarClient
from django.contrib.postgres.search import SearchQuery, SearchRank
import resend
import logging
from django.urls import reverse
import asyncio
from pgvector.django import CosineDistance
from django.db.models import F
from django.db.models import Count
from typesense.client import Client

# Get logger instance at the top of the file
logger = logging.getLogger(__name__)

load_dotenv()


def home(request):
    news_sources_count = NewsSource.objects.filter(pages__isnull=False).distinct().count()
    news_pages_count = NewsPage.objects.filter(is_news_article=True)
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


def send_mail(subject, message, from_email, recipient_list, fail_silently=False):
    r = resend.Emails.send({
        "from": from_email,
        "to": recipient_list,
        "subject": subject,
        "html": message
    })

@login_required
def search(request):
    # Get unique countries and sources for filters
    countries = Journalist.objects.exclude(country__isnull=True).values_list('country', flat=True).distinct()
    
    # Get sources with their categories prefetched
    sources = NewsSource.objects.prefetch_related('categories').all()
    
    # Get all categories with their sources prefetched
    categories = NewsPageCategory.objects.prefetch_related('sources').order_by('name')
    
    # Get languages through the sources relationship
    languages = NewsSource.objects.exclude(language__isnull=True).values_list('language', flat=True).distinct()
    
    context = {
        'countries': countries,
        'sources': sources,
        'categories': categories,
        'languages': languages,
        'turnstile_site_key': os.getenv('CLOUDFLARE_TURNSTILE_SITE_KEY'),
        # Add source-category mapping
        'source_categories': {
            source.id: list(source.categories.values_list('id', flat=True))
            for source in sources
        }
    }
    return render(request, 'core/app_search.html', context=context)


def search_results(request):
    starttime = timezone.now()
    is_subscriber = request.user.is_authenticated
    query = request.GET.get('q', '')
    country = request.GET.get('country', '')
    source_id = request.GET.get('source', '')
    category_id = request.GET.get('category', '')
    page_number = int(request.GET.get('page', 1))
    
    # If query is empty, return empty results
    if not query:
        return render(request, 'core/search_results.html', {
            'results': [],
            'total_hits': 0,
            'page': page_number,
            'has_next': False,
            'has_previous': False,
            'search_time': timezone.now() - starttime,
            'is_subscriber': is_subscriber,
        })
    
    try:
        # Get Typesense client
        from .typesense_config import get_typesense_client
        client = get_typesense_client()
        
        # Build search parameters
        search_parameters = {
            'q': query,
            'query_by': 'name,description,sources,categories',
            'per_page': 10,
            'page': page_number,
        }
        
        # Add filters if specified
        filter_rules = []
        if country:
            filter_rules.append(f'country:{country}')
        if source_id:
            source = NewsSource.objects.get(id=source_id)
            filter_rules.append(f'sources:[{source.name}]')
        if category_id:
            category = NewsPageCategory.objects.get(id=category_id)
            filter_rules.append(f'categories:[{category.name}]')
        
        if filter_rules:
            search_parameters['filter_by'] = ' && '.join(filter_rules)
        
        logger.info(f"Searching Typesense with parameters: {search_parameters}")
        
        # Check if collection exists
        try:
            client.collections['journalists'].retrieve()
        except Exception as e:
            logger.error(f"Collection 'journalists' not found: {str(e)}")
            from .typesense_config import init_typesense
            init_typesense()
            
        # Perform the search
        search_results = client.collections['journalists'].documents.search(search_parameters)
        logger.info(f"Found {search_results['found']} results")
        
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
            
            # Limit results for non-subscribers
            search_results['hits'] = search_results['hits'][:10]
        else:
            request.user.searches_count += 1
            if not request.user.has_searched:
                request.user.has_searched = True
            request.user.save()
        
        # Get the actual Journalist objects for the results
        journalist_ids = [hit['document']['id'] for hit in search_results['hits']]
        logger.info(f"Looking up journalists with IDs: {journalist_ids}")
        
        journalists = Journalist.objects.filter(id__in=journalist_ids).prefetch_related(
            'sources', 'categories', 'articles'
        )
        
        # Map Journalist objects to results
        journalist_map = {str(j.id): j for j in journalists}
        logger.info(f"Found {len(journalist_map)} matching journalists in database")
        
        # Create a list of journalists in the same order as the search results
        mapped_results = []
        for hit in search_results['hits']:
            doc_id = hit['document']['id']
            if doc_id in journalist_map:
                mapped_results.append(journalist_map[doc_id])
        
        # Prepare context
        context = {
            'results': mapped_results,
            'total_hits': search_results['found'],
            'page': page_number,
            'has_next': len(search_results['hits']) == 10,
            'has_previous': page_number > 1,
            'time_taken': timezone.now() - starttime,
            'unfiltered_results_count': search_results['found'],
            'is_subscriber': is_subscriber,
        }
        
        return render(request, 'core/search_results.html', context)
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return render(request, 'core/search_results.html', 
                    {'error': 'An error occurred during search. Please try again.'})


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
    
    # Get the source of the redirect
    source = request.GET.get('source')
    message = None
    
    # Set appropriate message based on source
    if source == 'more_info':
        message = "Sign up to view detailed journalist information"
    elif source == 'add_list':
        message = "Sign up to create and manage journalist lists"
    elif source == 'email':
        message = "Sign up to access journalist contact information"
        
    context = {
        'pricing_plans': pricing_plans,
        'message': message
    }
    return render(request, 'core/pricing.html', context=context)


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
        
        logger.info(f"Received Polar webhook event: {event.type}")
        
        # Handle subscription events
        if event.type.startswith('subscription.'):
            User = get_user_model()
            subscription_id = event.data.get('id')
            user = User.objects.filter(polar_subscription_id=subscription_id).first()
            
            if user:
                if event.type == 'subscription.deleted':
                    user.polar_subscription_id = None
                    user.subscription_status = 'inactive'
                    user.credits = 0
                elif event.type == 'subscription.created':
                    user.subscription_status = 'active'
                    user.credits = event.data.get('metadata', {}).get('credits', 0)
                elif event.type == 'subscription.updated':
                    user.subscription_status = 'active'
                    user.credits = event.data.get('metadata', {}).get('credits', 0)
                
                user.save()
                logger.info(f"Updated user {user.email} subscription status to {user.subscription_status}")
                
        return HttpResponse(status=200)
        
    except Exception as e:
        logger.error(f"Error processing Polar webhook: {str(e)}")
        return HttpResponse(status=400)


def search_v2(request):
    context = {
        'ALGOLIA_APP_ID': os.getenv('ALGOLIA_APP_ID'),
        'ALGOLIA_SEARCH_API_KEY': os.getenv('ALGOLIA_SEARCH_API_KEY'),
        'ALGOLIA_INDEX_NAME': os.getenv('ALGOLIA_INDEX_NAME'),
    }
    return render(request, 'core/search_v2.html', context=context)


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
    """Landing page for subscription confirmation"""
    if not request.GET.get('session_id'):
        return redirect('home')
    return render(request, 'core/subscription_confirm.html')

def subscription_confirm_check(request):
    """HTMX endpoint to check subscription status"""
    session_id = request.GET.get('session_id')
    logger.info(f"Checking session_id: {session_id}")
    
    if not session_id:
        return render(request, 'core/partials/subscription_status.html', {
            'error': 'No session ID provided'
        })
    
    try:
        polar = PolarClient.get_client()
        checkout = polar.checkouts.custom.get(id=session_id)
        
        if checkout.status != 'succeeded':
            # Still processing - return template that will trigger another check
            return render(request, 'core/partials/subscription_status.html', {
                'session_id': session_id
            })

        # Process successful checkout
        customer_email = checkout.customer_email
        if not customer_email:
            return render(request, 'core/partials/subscription_status.html', {
                'error': 'No email provided'
            })
            
        User = get_user_model()
        user = User.objects.filter(email=customer_email).first()
        
        if not user:
            try:
                user, password = create_new_user(customer_email)
            except Exception as e:
                return render(request, 'core/partials/subscription_status.html', {
                    'error': f'Error creating user account: {str(e)}'
                })
            
        try:
            user.polar_subscription_id = checkout.subscription_id
            user.subscription_status = 'active'
            user.credits = checkout.metadata.get('credits', 0)
            user.save()
            
            if not request.user.is_authenticated:
                from allauth.account.utils import perform_login
                perform_login(
                    request, 
                    user,
                    email_verification='optional',
                    redirect_url=None,
                    signal_kwargs={"signup": False}
                )
            
            return render(request, 'core/partials/subscription_status.html', {
                'success': True,
                'redirect_url': reverse('dashboard')
            })
            
        except Exception as e:
            return render(request, 'core/partials/subscription_status.html', {
                'error': f'Error updating subscription: {str(e)}'
            })
        
    except Exception as e:
        return render(request, 'core/partials/subscription_status.html', {
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
        'Duncan from NachoPR <duncan@updates.nachopr.com>',
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
        try:
            data = json.loads(request.body)
            list_id = data.get('list_id')
            new_list_name = data.get('new_list_name')
            journalists = data.get('journalists', [])

            with transaction.atomic():
                # Create or get the list
                if list_id:
                    saved_list = get_object_or_404(SavedList, id=list_id, user=request.user)
                else:
                    # Validate new list name
                    if not new_list_name or new_list_name.strip() == '':
                        return JsonResponse({
                            'status': 'error',
                            'message': 'List name is required'
                        }, status=400)
                    
                    saved_list = SavedList.objects.create(
                        user=request.user,
                        name=new_list_name.strip()
                    )

                # Update user activity flags
                if not list_id:
                    request.user.has_created_list = True
                if journalists:
                    request.user.has_saved_journalist = True
                request.user.save()

                # Add journalists to the list
                journalist_ids = [j['id'] for j in journalists]
                saved_list.journalists.add(*journalist_ids)
                
                # Update the list's updated_at timestamp
                saved_list.save()

                return JsonResponse({
                    'status': 'success',
                    'list': {
                        'id': saved_list.id,
                        'name': saved_list.name,
                        'journalist_count': saved_list.journalists.count()
                    }
                })

        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            logger.error(f"Error saving to list: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'An error occurred while saving the list'
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Method not allowed'
    }, status=405)


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


def journalist_detail(request, id):
    journalist = get_object_or_404(Journalist, id=id)
    context = {'journalist': journalist}
    return render(request, 'core/journalist_detail.html', context=context)

@login_required
def find_journalist_email(request, journalist_id):
    """HTMX endpoint to find and save journalist email"""
    logger.info(f"Finding email for journalist {journalist_id}")
    
    if request.method != 'POST':
        logger.warning(f"Invalid method {request.method} for find_journalist_email")
        return HttpResponse(status=405)  # Method not allowed
        
    if request.user.credits <= 0:
        logger.warning(f"User {request.user.email} has no credits remaining")
        return HttpResponse(
            '<span class="text-red-600">No credits remaining</span>',
            status=200
        )
        
    journalist = get_object_or_404(Journalist, id=journalist_id)
    logger.info(f"Found journalist: {journalist.name}")
    
    # Don't search if we already have an email
    if journalist.email_address:
        logger.info(f"Email already exists for {journalist.name}: {journalist.email_address}")
        return HttpResponse(
            f'<span class="text-green-600">{journalist.email_address}</span>',
            status=200
        )
        
    # Get the first source's domain to try
    first_source = journalist.sources.first()
    if not first_source:
        logger.warning(f"No source found for journalist {journalist.name}")
        return HttpResponse(
            '<span class="text-red-600">No source domain available</span>',
            status=200
        )
        
    # Extract domain from source URL
    try:
        domain = first_source.url.split('//')[1].split('/')[0]
        logger.info(f"Trying domain {domain} for {journalist.name}")
    except Exception as e:
        logger.error(f"Error extracting domain from {first_source.url}: {str(e)}")
        return HttpResponse(
            '<span class="text-red-600">Invalid source URL</span>',
            status=200
        )
    
    # Try to find email
    try:
        email = find_single_email_with_hunter_io(journalist.name, domain)
        
        if email:
            logger.info(f"Found email {email} for {journalist.name}")
            # Use direct update to avoid triggering signals
            Journalist.objects.filter(id=journalist.id).update(
                email_address=email,
                email_status='guessed_by_third_party',
                email_search_with_hunter_tried=True
            )
            
            # Record the email discovery
            EmailDiscovery.objects.create(
                user=request.user,
                journalist=journalist,
                email=email,
                source_domain=domain
            )
            
            # Deduct credit using direct update
            CustomUser.objects.filter(id=request.user.id).update(
                credits=F('credits') - 1,
                has_retrieved_email=True
            )
            
            return HttpResponse(
                f'<span class="text-green-600">{email}</span>',
                status=200
            )
        else:
            logger.info(f"No email found for {journalist.name} at {domain}")
            # Use direct update to avoid triggering signals
            Journalist.objects.filter(id=journalist.id).update(
                email_search_with_hunter_tried=True
            )
            return HttpResponse(
                '<span class="text-red-600">No email found</span>',
                status=200
            )
    except Exception as e:
        logger.error(f"Error finding email for {journalist.name}: {str(e)}")
        return HttpResponse(
            '<span class="text-red-600">Error finding email</span>',
            status=200
        )

@login_required
def email_discoveries(request):
    discoveries = EmailDiscovery.objects.filter(user=request.user).select_related('journalist')
    
    # Group by date for better organization
    discoveries_by_date = {}
    for discovery in discoveries:
        date = discovery.created_at.date()
        if date not in discoveries_by_date:
            discoveries_by_date[date] = []
        discoveries_by_date[date].append(discovery)
    
    context = {
        'discoveries_by_date': discoveries_by_date
    }
    return render(request, 'core/email_discoveries.html', context)

@login_required
def get_user_lists(request):
    """API endpoint to get user's saved lists with journalist counts"""
    lists = SavedList.objects.filter(user=request.user).values(
        'id', 
        'name'
    ).annotate(
        journalist_count=Count('journalists')
    ).order_by('-updated_at')
    
    return JsonResponse(list(lists), safe=False)

def get_typesense_client():
    return Client(
        os.getenv('TYPESENSE_URL'),
        os.getenv('TYPESENSE_API_KEY')
    )