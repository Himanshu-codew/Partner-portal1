from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView
from django.core.cache import cache
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth, TruncDay
from django.contrib import messages
from django.utils import timezone
import datetime

from leads.models import Lead
from orders.models import Order
from support.models import Ticket
from partners.models import PartnerProfile
from portal_content.models import Announcement
from partners.utils import get_partner_profile
from .forms import PartnerRegistrationForm, PartnerProfileUpdateForm, UserUpdateForm


def get_month_range(dt):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1) - datetime.timedelta(microseconds=1)
    else:
        end = start.replace(month=start.month + 1) - datetime.timedelta(microseconds=1)
    return start, end


def calculate_trend(current_val, previous_val):
    if previous_val == 0:
        if current_val == 0:
            return {'direction': 'flat', 'value': 0}
        return {'direction': 'up', 'value': 100}
    
    diff = current_val - previous_val
    percent = round((abs(diff) / previous_val) * 100)
    
    if diff > 0:
        return {'direction': 'up', 'value': percent}
    elif diff < 0:
        return {'direction': 'down', 'value': percent}
    else:
        return {'direction': 'flat', 'value': 0}


def compact_currency(amount):
    if amount >= 10000000:
        return f"₹{amount/10000000:.1f}Cr".replace('.0', '')
    elif amount >= 100000:
        return f"₹{amount/100000:.1f}L".replace('.0', '')
    elif amount >= 1000:
        return f"₹{amount/1000:.1f}K".replace('.0', '')
    else:
        return f"₹{int(amount)}"


@login_required(login_url='/login/')
def approval_pending(request):
    """View shown to users whose partner account is pending admin approval."""
    if request.user.is_staff:
        return redirect('dashboard')
    profile = get_partner_profile(request.user)
    if profile and profile.is_approved:
        return redirect('dashboard')
    return render(request, 'approval_pending.html')


@login_required(login_url='/login/')
def dashboard(request):
    is_staff = request.user.is_staff
    
    now = timezone.now()
    curr_start, curr_end = get_month_range(now)
    prev_dt = curr_start - datetime.timedelta(days=15)
    prev_start, prev_end = get_month_range(prev_dt)
    
    if is_staff:
        leads_qs = Lead.objects.all()
        orders_qs = Order.objects.all()
        tickets_qs = Ticket.objects.all()
        # Admin earnings = Total amount collected - Total commission paid to partners
        total_collected = Order.objects.aggregate(total=Sum('amount'))['total'] or 0
        commission_paid = Order.objects.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        earnings = total_collected - commission_paid
        
        # Current month
        curr_orders = Order.objects.filter(created_at__range=(curr_start, curr_end))
        curr_collected = curr_orders.aggregate(total=Sum('amount'))['total'] or 0
        curr_comm = curr_orders.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        curr_earnings = curr_collected - curr_comm
        
        # Previous month
        prev_orders = Order.objects.filter(created_at__range=(prev_start, prev_end))
        prev_collected = prev_orders.aggregate(total=Sum('amount'))['total'] or 0
        prev_comm = prev_orders.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        prev_earnings = prev_collected - prev_comm
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')

        leads_qs = Lead.objects.filter(partner=profile)
        orders_qs = Order.objects.filter(partner=profile)
        tickets_qs = Ticket.objects.filter(partner=profile)
        earnings = Order.objects.filter(partner=profile, is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        
        curr_orders = Order.objects.filter(partner=profile, created_at__range=(curr_start, curr_end))
        curr_earnings = curr_orders.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        
        prev_orders = Order.objects.filter(partner=profile, created_at__range=(prev_start, prev_end))
        prev_earnings = prev_orders.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0

    leads_count = leads_qs.count()
    orders_count = orders_qs.count()
    tickets_count = tickets_qs.filter(status__in=['OPEN', 'IN_PROGRESS']).count()

    # Trends calculation
    curr_leads = leads_qs.filter(created_at__range=(curr_start, curr_end)).count()
    prev_leads = leads_qs.filter(created_at__range=(prev_start, prev_end)).count()
    trends = {
        'leads': calculate_trend(curr_leads, prev_leads),
        'orders': calculate_trend(orders_qs.filter(created_at__range=(curr_start, curr_end)).count(), 
                                orders_qs.filter(created_at__range=(prev_start, prev_end)).count()),
        'tickets': calculate_trend(tickets_qs.filter(created_at__range=(curr_start, curr_end)).count(),
                                 tickets_qs.filter(created_at__range=(prev_start, prev_end)).count()),
        'earnings': calculate_trend(curr_earnings, prev_earnings)
    }

    # Chart 1: Leads by status
    leads_chart = list(leads_qs.values('status').annotate(count=Count('id')))
    status_map = dict(Lead.STATUS_CHOICES)
    for l in leads_chart:
        l['status_label'] = status_map.get(l['status'], l['status'])

    # Chart 2: Orders by time range
    chart_range = request.GET.get('range', '12m')
    chart_orders_qs = orders_qs
    
    if chart_range == '7d':
        start_date = now - datetime.timedelta(days=7)
        chart_orders_qs = orders_qs.filter(created_at__gte=start_date)
        orders_chart_raw = list(chart_orders_qs.annotate(date=TruncDay('created_at'))
                                         .values('date')
                                         .annotate(count=Count('id'))
                                         .order_by('date'))
        orders_chart = []
        for o in orders_chart_raw:
            if o['date']:
                orders_chart.append({
                    'month': o['date'].strftime('%b %d'),
                    'count': o['count']
                })
    elif chart_range == '30d':
        start_date = now - datetime.timedelta(days=30)
        chart_orders_qs = orders_qs.filter(created_at__gte=start_date)
        orders_chart_raw = list(chart_orders_qs.annotate(date=TruncDay('created_at'))
                                         .values('date')
                                         .annotate(count=Count('id'))
                                         .order_by('date'))
        orders_chart = []
        for o in orders_chart_raw:
            if o['date']:
                orders_chart.append({
                    'month': o['date'].strftime('%b %d'),
                    'count': o['count']
                })
    else: # 12m or default
        start_date = now - datetime.timedelta(days=365)
        chart_orders_qs = orders_qs.filter(created_at__gte=start_date)
        orders_chart_raw = list(chart_orders_qs.annotate(month=TruncMonth('created_at'))
                                         .values('month')
                                         .annotate(count=Count('id'))
                                         .order_by('month'))
        orders_chart = []
        for o in orders_chart_raw:
            if o['month']:
                orders_chart.append({
                    'month': o['month'].strftime('%b %Y'),
                    'count': o['count']
                })

    # Recent Activity with select_related
    events = []
    for l in leads_qs.select_related('partner', 'partner__user').order_by('-created_at')[:8]:
        events.append({
            'type': 'Lead', 
            'title': f"New Lead: {l.customer_name}", 
            'status': l.get_status_display(), 
            'created_at': l.created_at, 
            'icon': 'bi-person-lines-fill',
            'color': 'primary'
        })
    for o in orders_qs.select_related('partner', 'partner__user').order_by('-created_at')[:8]:
        events.append({
            'type': 'Order', 
            'title': f"Order #{o.order_number}", 
            'status': o.get_status_display(), 
            'created_at': o.created_at, 
            'icon': 'bi-cart-check',
            'color': 'success'
        })
    for t in tickets_qs.select_related('partner', 'partner__user').order_by('-created_at')[:8]:
        events.append({
            'type': 'Ticket', 
            'title': f"Ticket: {t.subject}", 
            'status': t.get_status_display(), 
            'created_at': t.created_at, 
            'icon': 'bi-headset',
            'color': 'warning'
        })
    
    recent_activity = sorted(events, key=lambda x: x['created_at'], reverse=True)[:8]

    # Announcements
    announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')[:3]

    recent_leads = leads_qs.select_related('partner', 'partner__user').order_by('-created_at')[:5]

    total_commission_paid = 0
    total_commission_pending = 0
    top_partners = []
    
    if is_staff:
        total_commission_paid = commission_paid
        total_commission_pending = Order.objects.filter(is_commission_paid=False).aggregate(total=Sum('commission_amount'))['total'] or 0
        
        top_partners = PartnerProfile.objects.annotate(
            total_earnings=Sum('orders__commission_amount', filter=Q(orders__is_commission_paid=True))
        ).filter(total_earnings__isnull=False).select_related('user').order_by('-total_earnings')[:5]
    else:
        profile = get_partner_profile(request.user)
        total_commission_paid = earnings
        if profile:
            total_commission_pending = Order.objects.filter(partner=profile, is_commission_paid=False).aggregate(total=Sum('commission_amount'))['total'] or 0
        else:
            total_commission_pending = 0

    total_commission_all = total_commission_paid + total_commission_pending
    commission_summary = {
        'paid': total_commission_paid,
        'pending': total_commission_pending,
        'total': total_commission_all,
        'paid_percent': round((total_commission_paid / total_commission_all) * 100) if total_commission_all > 0 else 0,
        'pending_percent': round((total_commission_pending / total_commission_all) * 100) if total_commission_all > 0 else 0
    }

    context = {
        'leads_count': leads_count,
        'orders_count': orders_count,
        'tickets_count': tickets_count,
        'earnings_compact': compact_currency(earnings),
        'trends': trends,
        'leads_chart': leads_chart,
        'orders_chart': orders_chart,
        'recent_activity': recent_activity,
        'announcements': announcements,
        'recent_leads': recent_leads,
        'commission_summary': commission_summary,
        'top_partners': top_partners,
    }
    return render(request, 'dashboard.html', context)


@login_required(login_url='/login/')
def profile_view(request):
    profile = get_partner_profile(request.user)
    return render(request, 'profile.html', {'profile': profile})


def register_view(request):
    if request.method == 'POST':
        form = PartnerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.email = form.cleaned_data.get('email', '')
            user.save()
            
            # New registrations create unapproved PartnerProfile
            PartnerProfile.objects.create(
                user=user,
                company_name=form.cleaned_data['company_name'],
                phone_number=form.cleaned_data['phone_number'],
                is_approved=False
            )
            
            messages.success(request, 'Account created. You can log in once an admin approves it.')
            return redirect('login')
    else:
        form = PartnerRegistrationForm()
        
    return render(request, 'register.html', {'form': form})


@login_required(login_url='/login/')
def profile_edit(request):
    profile = get_partner_profile(request.user)
    has_profile = profile is not None
    
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if has_profile:
            p_form = PartnerProfileUpdateForm(request.POST, instance=profile)
            p_valid = p_form.is_valid()
        else:
            p_form = None
            p_valid = True
            
        if u_form.is_valid() and p_valid:
            u_form.save()
            if has_profile:
                p_form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = PartnerProfileUpdateForm(instance=profile) if has_profile else None
        
    context = {
        'u_form': u_form,
        'p_form': p_form,
    }
    return render(request, 'profile_edit.html', context)


# -----------------------------------------------------------------
# Password reset request (rate-limited)
# -----------------------------------------------------------------

PASSWORD_RESET_LIMIT = 5          # requests per IP ...
PASSWORD_RESET_WINDOW = 60 * 60   # ... per hour


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class PasswordResetRequestView(PasswordResetView):
    """Password reset request form, throttled to 5 requests per IP per hour.

    Kept friendly on purpose: the underlying PasswordResetView already uses
    the same "done" page for known and unknown addresses, so no account
    enumeration is possible here either.
    """

    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    html_email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'

    def post(self, request, *args, **kwargs):
        cache_key = 'password-reset:{}'.format(get_client_ip(request))
        cache.add(cache_key, 0, PASSWORD_RESET_WINDOW)
        try:
            attempts = cache.incr(cache_key)
        except ValueError:  # key expired between add and incr
            cache.set(cache_key, 1, PASSWORD_RESET_WINDOW)
            attempts = 1

        if attempts > PASSWORD_RESET_LIMIT:
            messages.warning(
                request,
                'Too many password reset requests. Please wait about an hour before trying again.'
            )
            return self.get(request, *args, **kwargs)

        return super().post(request, *args, **kwargs)
