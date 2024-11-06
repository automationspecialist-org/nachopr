from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('free-media-list/', views.free_media_list, name='free-media-list'),
    path('signup/', views.signup, name='signup'),
]

