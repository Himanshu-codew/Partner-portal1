from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from leads.models import Lead
from orders.models import Order
from support.models import Ticket

@login_required(login_url='/login/')
def dashboard(request):
    if request.user.is_staff:
        leads_count = Lead.objects.count()
        orders_count = Order.objects.count()
        tickets_count = Ticket.objects.filter(status__in=['OPEN', 'IN_PROGRESS']).count()
        earnings = sum(order.commission_amount for order in Order.objects.filter(is_commission_paid=True))
    else:
        try:
            profile = request.user.partner_profile
            leads_count = Lead.objects.filter(partner=profile).count()
            orders_count = Order.objects.filter(partner=profile).count()
            tickets_count = Ticket.objects.filter(partner=profile, status__in=['OPEN', 'IN_PROGRESS']).count()
            earnings = sum(order.commission_amount for order in Order.objects.filter(partner=profile, is_commission_paid=True))
        except:
            leads_count = 0
            orders_count = 0
            tickets_count = 0
            earnings = 0
            
    context = {
        'leads_count': leads_count,
        'orders_count': orders_count,
        'tickets_count': tickets_count,
        'earnings': earnings,
    }
    return render(request, 'dashboard.html', context)

@login_required(login_url='/login/')
def profile_view(request):
    try:
        profile = request.user.partner_profile
    except:
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
            user.save()
            
            # Create the partner profile and auto-approve them
            PartnerProfile.objects.create(
                user=user,
                company_name=form.cleaned_data['company_name'],
                phone_number=form.cleaned_data['phone_number'],
                is_approved=True
            )
            
            messages.success(request, 'Account created successfully! You are now logged in and can start using the portal.')
            return redirect('login')
    else:
        form = PartnerRegistrationForm()
        
    return render(request, 'register.html', {'form': form})
