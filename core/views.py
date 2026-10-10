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
from django.utils.http import urlencode
from django.core.cache import cache
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


# ─────────────────────────────────────────
#  Global search (Phase 4B)
# ─────────────────────────────────────────

SEARCH_MIN_LENGTH = 2          # characters required before we hit the DB
SEARCH_RESULT_LIMIT = 50       # max rows fetched per group on the results page
SEARCH_SUGGEST_LIMIT = 5       # max rows per group in the type-ahead dropdown
SEARCH_SUGGEST_THROTTLE = 60   # suggestions allowed per user per window
SEARCH_SUGGEST_WINDOW = 60     # throttle window, in seconds


def _search_list_url(view_name, query):
    """Link to an existing list page, preserving the query string."""
    return reverse(view_name) + '?' + urlencode({'q': query})


def _item(title, subtitle, url, status=None, status_label=None):
    return {
        'title': title or '',
        'subtitle': subtitle or '',
        'url': url,
        'status': status,
        'status_label': status_label,
    }


def _rank(items, query):
    """Float exact (case-insensitive) title matches to the top of a group."""
    needle = query.casefold()
    return sorted(items, key=lambda i: 0 if i['title'].casefold() == needle else 1)


def _group(key, label, icon, color, items, total, list_name, query):
    return {
        'key': key,
        'label': label,
        'icon': icon,
        'color': color,
        'items': _rank(items, query),
        'total': total,
        'list_url': _search_list_url(list_name, query),
    }


def _search_groups(user, query, limit):
    """Build the grouped result set for ``query``, scoped to ``user``.

    Reuses the same role scoping as the list views: staff see everything,
    partners only their own records (plus content shared with them). Soft
    deleted rows are excluded automatically by the default managers.
    """
    from django.contrib.auth.models import User
    from django.db.models import Count, Q
    from leads.models import Lead
    from orders.models import Order
    from support.models import Ticket
    from partners.models import PartnerDocument, PartnerProfile
    from portal_content.models import Announcement, Document

    is_staff = user.is_staff
    profile = None if is_staff else get_partner_profile(user)
    groups = []

    # ── Leads (customer name / phone / product) ──
    leads = Lead.objects.select_related('partner')
    if not is_staff:
        leads = leads.filter(partner=profile)
    leads = leads.filter(
        Q(customer_name__icontains=query)
        | Q(customer_phone__icontains=query)
        | Q(product_interest__icontains=query)
    ).order_by('-created_at')
    lead_total = leads.count()
    groups.append(_group(
        'leads', 'Leads', 'bi-person-lines-fill', 'primary',
        [
            _item(
                l.customer_name,
                ((l.partner.company_name + ' · ') if l.partner else '') + l.product_interest,
                reverse('lead_update', args=[l.pk]),
                l.status, l.get_status_display(),
            )
            for l in leads[:limit]
        ],
        lead_total, 'lead_list', query,
    ))

    # ── Orders (order number / partner company) ──
    orders = Order.objects.select_related('partner', 'lead')
    if not is_staff:
        orders = orders.filter(partner=profile)
    orders = orders.filter(
        Q(order_number__icontains=query)
        | Q(partner__company_name__icontains=query)
    ).order_by('-created_at')
    order_total = orders.count()
    groups.append(_group(
        'orders', 'Orders', 'bi-cart-check', 'success',
        [
            _item(
                'Order #' + o.order_number,
                f'{o.partner.company_name} · ₹{o.amount:.2f}',
                reverse('order_update', args=[o.pk]) if is_staff else reverse('order_list'),
                o.status, o.get_status_display(),
            )
            for o in orders[:limit]
        ],
        order_total, 'order_list', query,
    ))

    # ── Support tickets (subject / description) ──
    tickets = Ticket.objects.select_related('partner')
    if not is_staff:
        tickets = tickets.filter(partner=profile)
    tickets = tickets.filter(
        Q(subject__icontains=query) | Q(description__icontains=query)
    ).order_by('-created_at')
    ticket_total = tickets.count()
    groups.append(_group(
        'tickets', 'Support Tickets', 'bi-headset', 'warning',
        [
            _item(
                t.subject,
                t.partner.company_name,
                reverse('ticket_detail', args=[t.pk]),
                t.status, t.get_status_display(),
            )
            for t in tickets[:limit]
        ],
        ticket_total, 'ticket_list', query,
    ))

    # ── KYC documents (partner company / OCR text / type) ──
    kyc = PartnerDocument.objects.select_related('partner')
    if not is_staff:
        kyc = kyc.filter(partner=profile)
    kyc = kyc.filter(
        Q(partner__company_name__icontains=query)
        | Q(ocr_text__icontains=query)
        | Q(doc_type__icontains=query)
    ).order_by('-uploaded_at')
    kyc_total = kyc.count()
    # Reuse the shared badge partial: map review states onto colours it knows.
    kyc_badge = {'pending': 'PENDING', 'approved': 'CONVERTED', 'rejected': 'LOST'}
    groups.append(_group(
        'kyc', 'KYC Documents', 'bi-file-earmark-person', 'info',
        [
            _item(
                f'{d.partner.company_name} — {d.get_doc_type_display()}',
                'KYC · ' + d.get_review_status_display(),
                reverse('kyc_document_detail', args=[d.pk]) if is_staff
                else reverse('kyc_document_list'),
                kyc_badge.get(d.review_status), d.get_review_status_display(),
            )
            for d in kyc[:limit]
        ],
        kyc_total, 'kyc_document_list', query,
    ))

    # ── Announcements (title / content) ──
    announcements = Announcement.objects.filter(is_active=True)
    if not is_staff:
        announcements = announcements.annotate(vcount=Count('visible_to')).filter(
            Q(vcount=0) | Q(visible_to=profile)
        )
    announcements = announcements.filter(
        Q(title__icontains=query) | Q(content__icontains=query)
    ).distinct().order_by('-created_at')
    ann_total = announcements.count()
    groups.append(_group(
        'announcements', 'Announcements', 'bi-megaphone', 'warning',
        [
            _item(a.title, a.content[:90], reverse('announcement_list'))
            for a in announcements[:limit]
        ],
        ann_total, 'announcement_list', query,
    ))

    # ── Resources: documents (title) ──
    documents = Document.objects.all()
    if not is_staff:
        documents = documents.annotate(vcount=Count('visible_to')).filter(
            Q(vcount=0) | Q(visible_to=profile)
        )
    documents = documents.filter(title__icontains=query).distinct().order_by('-uploaded_at')
    doc_total = documents.count()
    groups.append(_group(
        'documents', 'Documents', 'bi-folder2-open', 'primary',
        [
            _item(d.title, 'Resource · ' + d.file_size_display,
                  reverse('document_download', args=[d.pk]))
            for d in documents[:limit]
        ],
        doc_total, 'document_list', query,
    ))

    # ── Staff-only: partner profiles ──
    if is_staff:
        partners = PartnerProfile.objects.select_related('user').filter(
            Q(company_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
            | Q(phone_number__icontains=query)
        ).order_by('-created_at')
        partner_total = partners.count()
        groups.append(_group(
            'partners', 'Partners', 'bi-buildings', 'secondary',
            [
                _item(
                    p.company_name,
                    p.user.username + ((' · ' + p.user.email) if p.user.email else ''),
                    reverse('partner_update', args=[p.pk]),
                    'COMPLETED' if p.is_approved else 'PENDING',
                    'Approved' if p.is_approved else 'Pending',
                )
                for p in partners[:limit]
            ],
            partner_total, 'partner_list', query,
        ))

    # ── Staff-only: users ──
    if is_staff:
        users = User.objects.filter(is_active=True).filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        ).order_by('-date_joined')
        user_total = users.count()
        groups.append(_group(
            'users', 'Users', 'bi-person-badge', 'secondary',
            [
                _item(u.username, u.email or u.get_full_name(),
                      reverse('user_update', args=[u.pk]))
                for u in users[:limit]
            ],
            user_total, 'user_list', query,
        ))

    return groups


@login_required(login_url='/login/')
def search(request):
    """Grouped, permission-aware global search results page."""
    query = (request.GET.get('q') or '').strip()
    context = {
        'query': query,
        'groups': [],
        'total': 0,
        'min_length': SEARCH_MIN_LENGTH,
        'too_short': 0 < len(query) < SEARCH_MIN_LENGTH,
    }
    if len(query) >= SEARCH_MIN_LENGTH:
        context['groups'] = [
            g for g in _search_groups(request.user, query, SEARCH_RESULT_LIMIT)
            if g['total']
        ]
        context['total'] = sum(g['total'] for g in context['groups'])
    return render(request, 'search.html', context)


def _suggest_throttled(user):
    """Simple fixed-window rate limit: 60 suggestions / minute / user."""
    window = int(timezone.now().timestamp()) // SEARCH_SUGGEST_WINDOW
    key = 'search-suggest:%s:%s' % (user.pk, window)
    try:
        current = cache.get(key, 0)
        if current >= SEARCH_SUGGEST_THROTTLE:
            return True
        cache.set(key, current + 1, SEARCH_SUGGEST_WINDOW * 2)
    except Exception:
        # Never let a cache outage break search.
        return False
    return False


@login_required(login_url='/login/')
def search_suggest(request):
    """Type-ahead JSON for the top-bar dropdown (same permission rules)."""
    query = (request.GET.get('q') or '').strip()
    if len(query) < SEARCH_MIN_LENGTH:
        return JsonResponse({'query': query, 'total': 0, 'groups': []})

    if _suggest_throttled(request.user):
        return JsonResponse(
            {'error': 'Too many search requests. Please slow down.'}, status=429
        )

    groups = []
    for g in _search_groups(request.user, query, SEARCH_SUGGEST_LIMIT):
        if not g['items']:
            continue
        groups.append({
            'key': g['key'],
            'label': g['label'],
            'icon': g['icon'],
            'items': [
                {'title': i['title'], 'subtitle': i['subtitle'], 'url': i['url']}
                for i in g['items']
            ],
        })

    return JsonResponse({
        'query': query,
        'total': sum(len(g['items']) for g in groups),
        'groups': groups,
    })
