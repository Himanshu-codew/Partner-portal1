from django.urls import path
from . import views

urlpatterns = [
    path('', views.lead_list, name='lead_list'),
    path('add/', views.lead_create, name='lead_create'),
    path('<int:pk>/edit/', views.lead_update, name='lead_update'),
    path('<int:pk>/delete/', views.lead_delete, name='lead_delete'),
    path('update_status/<int:lead_id>/', views.lead_update_status, name='lead_update_status'),
]
