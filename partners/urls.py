from django.urls import path
from . import views

urlpatterns = [
    path('', views.partner_list, name='partner_list'),
    path('add/', views.partner_create, name='partner_create'),
    path('<int:pk>/edit/', views.partner_update, name='partner_update'),
    path('<int:pk>/delete/', views.partner_delete, name='partner_delete'),
    path('approve/<int:profile_id>/', views.partner_approve, name='partner_approve'),
    
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_update, name='user_update'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    
    path('groups/', views.group_list, name='group_list'),
    path('groups/add/', views.group_create, name='group_create'),
    path('groups/<int:pk>/edit/', views.group_update, name='group_update'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),
]
