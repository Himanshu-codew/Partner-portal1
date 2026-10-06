from django.urls import path
from . import views

urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('add/', views.order_create, name='order_create'),
    path('<int:pk>/edit/', views.order_update, name='order_update'),
    path('<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('update_status/<int:order_id>/', views.order_update_status, name='order_update_status'),
    path('commission/', views.commission_list, name='commission_list'),
    path('<int:pk>/mark-paid/', views.order_mark_commission_paid, name='order_mark_commission_paid'),
    path('<int:pk>/mark-unpaid/', views.order_mark_commission_unpaid, name='order_mark_commission_unpaid'),
]
