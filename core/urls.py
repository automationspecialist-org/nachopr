from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('search-results/', views.search_results, name='search_results'),
    path('free-media-database/', views.free_media_list, name='free-media-list'),
    path('signup/', views.signup, name='signup'),
    path('pricing/', views.pricing, name='pricing'),
]

