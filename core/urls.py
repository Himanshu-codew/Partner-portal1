from django.urls import path
from . import views

urlpatterns = [
    path('recycle-bin/', views.recycle_bin, name='recycle_bin'),
    path('recycle-bin/restore/<str:model_name>/<int:pk>/', views.restore_item, name='restore_item'),
    path('recycle-bin/delete/<str:model_name>/<int:pk>/', views.hard_delete_item, name='hard_delete_item'),
    path('recycle-bin/empty/<str:model_name>/', views.empty_bin, name='empty_bin'),
]
