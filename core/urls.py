from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('app/search/', views.search, name='search'),
    path('search-results/', views.search_results, name='search_results'),
    path('free-media-database/', views.free_media_list, name='free-media-list'),
    path('free-media-list/', RedirectView.as_view(url='/free-media-database/', permanent=True), name='free-media-list-redirect'),
    path('signup/', views.signup, name='signup'),
    path('pricing/', views.pricing, name='pricing'),
    path('app/', views.dashboard, name='dashboard'),
    path('app/settings/', views.settings_view, name='settings'),
    path('webhooks/polar/', views.polar_webhook, name='polar-webhook'),
    path('app/saved_lists/', views.saved_lists, name='saved_lists'),
    path('app/save-to-list/', views.save_to_list, name='save_to_list'),
    path('app/list/<int:id>/', views.single_saved_list, name='single_saved_list'),
    path('subscription-confirm/', views.subscription_confirm, name='subscription_confirm'),
    path('health/', views.health, name='health'),
    path('subscription-confirm-check/', views.subscription_confirm_check, name='subscription_confirm_check'),
    path('search-v2/', views.search_v2, name='search_v2'),
    path('app/journalist/<int:id>/', views.journalist_detail, name='journalist_detail'),
    path('journalist/<int:journalist_id>/find-email/', views.find_journalist_email, name='find_journalist_email'),
]

