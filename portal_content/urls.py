from django.urls import path
from . import views

urlpatterns = [
    path('', views.content_list, name='content_list'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('documents/', views.document_list, name='document_list'),
    path('announcement/add/', views.announcement_create, name='announcement_create'),
    path('announcement/<int:pk>/edit/', views.announcement_update, name='announcement_update'),
    path('announcement/<int:pk>/delete/', views.announcement_delete, name='announcement_delete'),
    path('document/add/', views.document_create, name='document_create'),
    path('document/<int:pk>/edit/', views.document_update, name='document_update'),
    path('document/<int:pk>/delete/', views.document_delete, name='document_delete'),
]
