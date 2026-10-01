from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from django.core.exceptions import ObjectDoesNotExist

from leads.models import Lead
from orders.models import Order
from support.models import Ticket
from partners.models import PartnerProfile
from portal_content.models import Announcement

@login_required(login_url='/login/')
def dashboard(request):
    is_staff = request.user.is_staff
    
    if is_staff:
        leads_qs = Lead.objects.all()
        orders_qs = Order.objects.all()
        tickets_qs = Ticket.objects.all()
        earnings = Order.objects.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
    else:
        try:
            profile = request.user.partner_profile
            leads_qs = Lead.objects.filter(partner=profile)
            orders_qs = Order.objects.filter(partner=profile)
            tickets_qs = Ticket.objects.filter(partner=profile)
            earnings = Order.objects.filter(partner=profile, is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
        except (PartnerProfile.DoesNotExist, ObjectDoesNotExist):
            leads_qs = Lead.objects.none()
            orders_qs = Order.objects.none()
            tickets_qs = Ticket.objects.none()
            earnings = 0

    leads_count = leads_qs.count()
    orders_count = orders_qs.count()
    tickets_count = tickets_qs.filter(status__in=['OPEN', 'IN_PROGRESS']).count()

    # Chart 1: Leads by status
    leads_chart = list(leads_qs.values('status').annotate(count=Count('id')))
    # Translate DB status choices to friendly names if needed
    status_map = dict(Lead.STATUS_CHOICES)
    for l in leads_chart:
        l['status_label'] = status_map.get(l['status'], l['status'])

    # Chart 2: Orders by month
    orders_chart_raw = list(orders_qs.annotate(month=TruncMonth('created_at'))
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

    # Recent Activity
    events = []
    for l in leads_qs.order_by('-created_at')[:8]:
        events.append({
            'type': 'Lead', 
            'title': f"New Lead: {l.customer_name}", 
            'status': l.get_status_display(), 
            'created_at': l.created_at, 
            'icon': 'bi-person-lines-fill',
            'color': 'primary'
        })
    for o in orders_qs.order_by('-created_at')[:8]:
        events.append({
            'type': 'Order', 
            'title': f"Order #{o.order_number}", 
            'status': o.get_status_display(), 
            'created_at': o.created_at, 
            'icon': 'bi-cart-check',
            'color': 'success'
        })
    for t in tickets_qs.order_by('-created_at')[:8]:
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

    context = {
        'leads_count': leads_count,
        'orders_count': orders_count,
        'tickets_count': tickets_count,
        'earnings': earnings,
        'leads_chart': leads_chart,
        'orders_chart': orders_chart,
        'recent_activity': recent_activity,
        'announcements': announcements,
    }
    return render(request, 'dashboard.html', context)

@login_required(login_url='/login/')
def profile_view(request):
    try:
        profile = request.user.partner_profile
    except (PartnerProfile.DoesNotExist, ObjectDoesNotExist):
        profile = None
    return render(request, 'profile.html', {'profile': profile})

def register_view(request):
    from .forms import PartnerRegistrationForm
    from partners.models import PartnerProfile
    from django.contrib import messages
    
    if request.method == 'POST':
        form = PartnerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.email = form.cleaned_data.get('email', '')
            user.save()
            
            # Create the partner profile and auto-approve them
            PartnerProfile.objects.create(
                user=user,
                company_name=form.cleaned_data['company_name'],
                phone_number=form.cleaned_data['phone_number'],
                is_approved=False
            )
            
            messages.success(request, 'Application submitted! You can log in now; full access is enabled after admin approval.')
            return redirect('login')
    else:
        form = PartnerRegistrationForm()
        
    return render(request, 'register.html', {'form': form})
