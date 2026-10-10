import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from partners.utils import get_partner_profile


# ─────────────────────────────────────────
#  PWA — manifest, service worker, offline (Phase 4A)
# ─────────────────────────────────────────

# Brand colours pulled from the sidebar tokens in static/css/portal.css.
PWA_THEME_COLOR = '#1e293b'       # dark navy
PWA_BACKGROUND_COLOR = '#0f172a'  # darker navy
SERVICE_WORKER_CACHE_VERSION = 'v1'


def _static(name):
    """Resolve a static asset to a URL (hashed in production, plain in dev).

    Falls back to an un-hashed URL when no manifest exists yet (local dev,
    tests without a ``collectstatic`` run), so the PWA endpoints never crash.
    """
    try:
        url = staticfiles_storage.url(name)
    except Exception:
        url = settings.STATIC_URL + name
    if not url.startswith('/'):
        url = '/' + url
    return url


def web_manifest(request):
    """Serve the web app manifest at /manifest.webmanifest (public)."""
    def icon(name, sizes, purpose=None):
        entry = {'src': _static(name), 'sizes': sizes, 'type': 'image/png'}
        if purpose:
            entry['purpose'] = purpose
        return entry

    manifest = {
        'name': 'Partner Portal',
        'short_name': 'Portal',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': PWA_BACKGROUND_COLOR,
        'theme_color': PWA_THEME_COLOR,
        'icons': [
            icon('icons/icon-192.png', '192x192'),
            icon('icons/icon-512.png', '512x512'),
            icon('icons/icon-maskable-512.png', '512x512', 'maskable'),
            {'src': _static('icons/icon.svg'), 'sizes': 'any',
             'type': 'image/svg+xml'},
        ],
    }
    return JsonResponse(manifest, content_type='application/manifest+json')


def service_worker(request):
    """Serve the service worker from the site root (public).

    The worker must control the whole origin, hence the
    ``Service-Worker-Allowed: /`` header. It is never cached.
    """
    precache_urls = [
        reverse('offline'),
        reverse('web_manifest'),
        _static('css/portal.css'),
        _static('icons/icon-192.png'),
        _static('icons/icon-512.png'),
    ]
    content = render_to_string('service-worker.js', {
        'cache_version': SERVICE_WORKER_CACHE_VERSION,
        'precache_urls_json': json.dumps(precache_urls),
        'offline_url': reverse('offline'),
    })
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response


def offline(request):
    """Public offline fallback page (no login required)."""
    return render(request, 'offline.html')


def get_soft_deleted_models():
    # Dictionary of model name to actual model class
    return {
        'partnerprofile': apps.get_model('partners', 'PartnerProfile'),
        'lead': apps.get_model('leads', 'Lead'),
        'order': apps.get_model('orders', 'Order'),
        'ticket': apps.get_model('support', 'Ticket'),
        'announcement': apps.get_model('portal_content', 'Announcement'),
        'document': apps.get_model('portal_content', 'Document'),
    }

@login_required(login_url='/login/')
def recycle_bin(request):
    if not request.user.is_staff:
        raise PermissionDenied
        
    models_map = get_soft_deleted_models()
    active_tab = request.GET.get('tab', 'partnerprofile')
    if active_tab not in models_map and active_tab != 'user':
        active_tab = 'partnerprofile'
        
    context = {'active_tab': active_tab, 'tabs': {}}
    
    # Custom logic for User
    deleted_users = list(User.objects.filter(is_active=False).order_by('-date_joined'))
    for u in deleted_users:
        u.deleted_at = u.last_login or u.date_joined
        u.deleted_by = None
        
    context['tabs']['user'] = {
        'verbose_name': 'Users',
        'count': len(deleted_users),
        'items': deleted_users if active_tab == 'user' else []
    }
    
    for name, model in models_map.items():
        deleted_items = model.deleted_objects.all().order_by('-deleted_at')
        context['tabs'][name] = {
            'verbose_name': model._meta.verbose_name_plural.title(),
            'count': deleted_items.count(),
            'items': deleted_items if name == active_tab else []
        }
        
    return render(request, 'core/recycle_bin.html', context)

@login_required(login_url='/login/')
@require_POST
def restore_item(request, model_name, pk):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        from django.contrib.auth.models import User
        user = get_object_or_404(User, pk=pk)
        user.is_active = True
        user.save()
        messages.success(request, "User successfully restored.")
        return redirect(f'/recycle-bin/?tab={model_name}')
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        item = get_object_or_404(model.deleted_objects.all(), pk=pk)
        item.restore()
        
        # Special logic for PartnerProfile restore
        if model_name == 'partnerprofile':
            item.user.is_active = True
            item.user.save()
            
        messages.success(request, f"{model._meta.verbose_name.title()} successfully restored.")
    return redirect(f'/recycle-bin/?tab={model_name}')

@login_required(login_url='/login/')
@require_POST
def hard_delete_item(request, model_name, pk):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        from django.contrib.auth.models import User
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, "You cannot delete your own account.")
            return redirect(f'/recycle-bin/?tab={model_name}')
        if user.is_superuser and not request.user.is_superuser:
            messages.error(request, "Only superusers can delete superuser accounts.")
            return redirect(f'/recycle-bin/?tab={model_name}')
        if user.is_superuser and user.is_active:
            active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
            if not active_superusers.exists():
                messages.error(request, "The last remaining active superuser cannot be deleted.")
                return redirect(f'/recycle-bin/?tab={model_name}')
        user.delete()
        messages.success(request, "User permanently deleted.")
        return redirect(f'/recycle-bin/?tab={model_name}')
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        item = get_object_or_404(model.deleted_objects.all(), pk=pk)
        item.hard_delete()
        messages.success(request, f"{model._meta.verbose_name.title()} permanently deleted.")
    return redirect(f'/recycle-bin/?tab={model_name}')

@login_required(login_url='/login/')
@require_POST
def empty_bin(request, model_name):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        users = User.objects.filter(is_active=False).exclude(pk=request.user.pk)
        if not request.user.is_superuser:
            users = users.exclude(is_superuser=True)
        count = users.count()
        users.delete()
        messages.success(request, f"Permanently deleted {count} Users.")
        return redirect(f'/recycle-bin/?tab={model_name}')

        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        count = model.deleted_objects.count()
        for item in model.deleted_objects.all():
            item.hard_delete()
        messages.success(request, f"Permanently deleted {count} {model._meta.verbose_name_plural}.")
    return redirect(f'/recycle-bin/?tab={model_name}')


# ─────────────────────────────────────────
#  Notifications
# ─────────────────────────────────────────

def _humanize_time(dt):
    """Return a compact 'X ago' string without importing humanize."""
    from django.utils.timesince import timesince
    return timesince(dt).split(',')[0] + ' ago'


@login_required(login_url='/login/')
def notifications_feed(request):
    """Return latest 10 notifications as JSON, scoped by role."""
    from support.models import Ticket, TicketReply
    from leads.models import Lead
    from orders.models import Order
    from partners.models import PartnerProfile
    from portal_content.models import Announcement
    from core.models import UserNotificationRead
    from django.db.models import Count, Q

    user = request.user

    # Determine last-read timestamp
    try:
        nr = user.notification_read
        last_read = nr.last_read_at
    except UserNotificationRead.DoesNotExist:
        last_read = timezone.now() - timezone.timedelta(days=7)

    notifications = []

    if user.is_staff:
        # Open / in-progress tickets
        for t in Ticket.objects.select_related('partner__user').filter(
            status__in=['OPEN', 'IN_PROGRESS']
        ).order_by('-created_at')[:5]:
            notifications.append({
                'icon': 'bi-headset',
                'color': 'danger',
                'title': t.subject,
                'msg': f"Ticket from {t.partner.company_name} — {t.get_status_display()}",
                'time': _humanize_time(t.created_at),
                'url': '/support/',
                'unread': t.created_at > last_read,
            })

        # Pending partner approvals
        for p in PartnerProfile.objects.select_related('user').filter(
            is_approved=False, is_deleted=False
        ).order_by('-created_at')[:3]:
            notifications.append({
                'icon': 'bi-person-check',
                'color': 'warning',
                'title': f"Pending approval: {p.company_name}",
                'msg': f"Partner {p.user.username} is awaiting approval",
                'time': _humanize_time(p.created_at),
                'url': f'/partners/',
                'unread': p.created_at > last_read,
            })

        # New leads (last 7 days)
        recent_leads = Lead.objects.select_related('partner__user').filter(
            created_at__gte=timezone.now() - timezone.timedelta(days=7)
        ).order_by('-created_at')[:3]
        for l in recent_leads:
            notifications.append({
                'icon': 'bi-person-lines-fill',
                'color': 'primary',
                'title': f"New lead: {l.customer_name}",
                'msg': f"Added by {l.partner.company_name if l.partner else 'system'}",
                'time': _humanize_time(l.created_at),
                'url': '/leads/',
                'unread': l.created_at > last_read,
            })

        # New orders (last 7 days)
        recent_orders = Order.objects.select_related('partner__user').filter(
            created_at__gte=timezone.now() - timezone.timedelta(days=7)
        ).order_by('-created_at')[:3]
        for o in recent_orders:
            notifications.append({
                'icon': 'bi-cart-check',
                'color': 'success',
                'title': f"New order #{o.order_number}",
                'msg': f"From {o.partner.company_name}",
                'time': _humanize_time(o.created_at),
                'url': '/orders/',
                'unread': o.created_at > last_read,
            })

        # Partner replies on tickets (last 7 days)
        recent_replies = TicketReply.objects.filter(
            author__is_staff=False,
            created_at__gte=timezone.now() - timezone.timedelta(days=7),
            ticket__is_deleted=False,
        ).select_related('ticket', 'author').order_by('-created_at')[:3]
        for r in recent_replies:
            who = r.author.username if r.author else 'partner'
            notifications.append({
                'icon': 'bi-reply-fill',
                'color': 'info',
                'title': r.ticket.subject,
                'msg': f"Reply from {who} — {r.ticket.get_status_display()}",
                'time': _humanize_time(r.created_at),
                'url': f'/support/{r.ticket.pk}/',
                'unread': r.created_at > last_read,
            })

    else:
        # Partner — scoped to their own data
        profile = get_partner_profile(user)
        if not profile or not profile.is_approved:
            return JsonResponse({'notifications': [], 'unread_count': 0})

        # Ticket replies from the support team (legacy admin_reply counts too)
        for t in Ticket.objects.filter(partner=profile).order_by('-updated_at')[:4]:
            support_replies = t.replies.filter(
                Q(author__isnull=True) | Q(author__is_staff=True)
            )
            if t.admin_reply or support_replies.exists():
                notifications.append({
                    'icon': 'bi-headset',
                    'color': 'info',
                    'title': t.subject,
                    'msg': f"Admin replied — {t.get_status_display()}",
                    'time': _humanize_time(t.updated_at),
                    'url': f'/support/{t.pk}/',
                    'unread': t.updated_at > last_read,
                })

        # Lead status changes
        for l in Lead.objects.filter(partner=profile).order_by('-created_at')[:3]:
            notifications.append({
                'icon': 'bi-person-lines-fill',
                'color': 'primary',
                'title': f"Lead: {l.customer_name}",
                'msg': l.get_status_display(),
                'time': _humanize_time(l.created_at),
                'url': '/leads/',
                'unread': l.created_at > last_read,
            })

        # Commission paid
        for o in Order.objects.filter(partner=profile, is_commission_paid=True).order_by('-created_at')[:3]:
            notifications.append({
                'icon': 'bi-wallet2',
                'color': 'success',
                'title': f"Commission paid — #{o.order_number}",
                'msg': f"₹{o.commission_amount:.0f} credited",
                'time': _humanize_time(o.created_at),
                'url': '/orders/commission/',
                'unread': o.created_at > last_read,
            })

        # Visible announcements
        from django.db.models import Q as DQ
        ann_qs = Announcement.objects.filter(is_active=True).annotate(
            vcount=Count('visible_to')
        ).filter(
            DQ(vcount=0) | DQ(visible_to=profile)
        ).distinct().order_by('-created_at')[:3]
        for a in ann_qs:
            notifications.append({
                'icon': 'bi-megaphone',
                'color': 'warning',
                'title': a.title,
                'msg': a.content[:80],
                'time': _humanize_time(a.created_at),
                'url': '/resources/announcements/',
                'unread': a.created_at > last_read,
            })

    # Sort by unread first, then limit to 10
    notifications.sort(key=lambda n: (0 if n['unread'] else 1))
    notifications = notifications[:10]

    return JsonResponse({'notifications': notifications, 'unread_count': sum(1 for n in notifications if n['unread'])})


@login_required(login_url='/login/')
@require_POST
def notifications_mark_read(request):
    """Mark all notifications as read by updating last_read_at."""
    from core.models import UserNotificationRead
    nr, _ = UserNotificationRead.objects.get_or_create(user=request.user)
    nr.last_read_at = timezone.now()
    nr.save(update_fields=['last_read_at'])
    return JsonResponse({'status': 'ok'})
