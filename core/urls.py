from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('app/search/', views.search, name='search'),
    path('search-results/', views.search_results, name='search_results'),
    path('free-media-database/', views.free_media_list, name='free-media-list'),
    path('signup/', views.signup, name='signup'),
    path('pricing/', views.pricing, name='pricing'),
    path('app/', views.dashboard, name='dashboard'),
    path('app/settings/', views.settings_view, name='settings'),
    path('webhooks/stripe/', views.stripe_webhook, name='stripe-webhook'),
    path('app/saved_lists.html', views.saved_lists, name='saved_lists'),
]

