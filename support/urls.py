from django.urls import path
from . import views

urlpatterns = [
    path('', views.ticket_list, name='ticket_list'),
    path('add/', views.ticket_create, name='ticket_create'),
    path('<int:pk>/edit/', views.ticket_update, name='ticket_update'),
    path('<int:pk>/delete/', views.ticket_delete, name='ticket_delete'),
    path('update_status/<int:ticket_id>/', views.ticket_update_status, name='ticket_update_status'),
    path('<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('<int:pk>/reply/', views.ticket_reply, name='ticket_reply'),
]
