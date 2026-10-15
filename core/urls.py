from django.urls import path
from . import views

urlpatterns = [
    # PWA (Phase 4A) — all public, served from the site root
    path('manifest.webmanifest', views.web_manifest, name='web_manifest'),
    path('service-worker.js', views.service_worker, name='service_worker'),
    path('offline/', views.offline, name='offline'),

    # Global search (Phase 4B)
    path('search/', views.search, name='search'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),

    # Inbound WhatsApp webhook (Phase 5 — 360dialog); token-guarded, no login
    path('webhooks/whatsapp/<str:token>/', views.whatsapp_webhook, name='whatsapp_webhook'),

    # OCR helper endpoint (Phase 7) — token-guarded, only active with OCR_WORKER_TOKEN
    path('internal/ocr/', views.ocr_worker, name='ocr_worker'),

    path('recycle-bin/', views.recycle_bin, name='recycle_bin'),
    path('recycle-bin/restore/<str:model_name>/<int:pk>/', views.restore_item, name='restore_item'),
    path('recycle-bin/delete/<str:model_name>/<int:pk>/', views.hard_delete_item, name='hard_delete_item'),
    path('recycle-bin/empty/<str:model_name>/', views.empty_bin, name='empty_bin'),
    path('notifications/feed/', views.notifications_feed, name='notifications_feed'),
    path('notifications/mark-read/', views.notifications_mark_read, name='notifications_mark_read'),
]
