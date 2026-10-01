from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Lead
from .forms import LeadForm, AdminLeadForm
from partners.models import PartnerProfile

@login_required(login_url='/login/')
def lead_list(request):
    if request.user.is_staff:
        leads_qs = Lead.objects.all().order_by('-created_at')
    else:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.warning(request, "Your account is pending approval.")
                return redirect('dashboard')
            leads_qs = Lead.objects.filter(partner=profile).order_by('-created_at')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to view leads.')
            return redirect('dashboard')

    # Search and Filter
    search_query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    if search_query:
        leads_qs = leads_qs.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(product_interest__icontains=search_query)
        )
    if status_filter:
        leads_qs = leads_qs.filter(status=status_filter)

    # Pagination
    paginator = Paginator(leads_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
            
    return render(request, 'leads/lead_list.html', {
        'leads': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'statuses': dict(Lead.STATUS_CHOICES)
    })

@login_required(login_url='/login/')
def lead_create(request):
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.error(request, 'Your account must be approved to add leads.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to add leads.')
            return redirect('dashboard')

    form_class = AdminLeadForm if request.user.is_staff else LeadForm
    
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            if not request.user.is_staff:
                lead.partner = request.user.partner_profile
            lead.save()
            messages.success(request, 'Lead successfully added!')
            return redirect('lead_list')
    else:
        form = form_class()
        
    return render(request, 'leads/lead_form.html', {'form': form})

@login_required(login_url='/login/')
@require_POST
def lead_update_status(request, lead_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('lead_list')
        
    try:
        lead = Lead.objects.get(id=lead_id)
        new_status = request.POST.get('status')
        if new_status in dict(Lead.STATUS_CHOICES):
            lead.status = new_status
            lead.save()
            messages.success(request, f'Lead #{lead.id} status updated to {lead.get_status_display()}.')
    except Lead.DoesNotExist:
        messages.error(request, 'Lead not found.')
            
    return redirect('lead_list')

@login_required(login_url='/login/')
def lead_update(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if lead.partner != profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')
        
    form_class = AdminLeadForm if request.user.is_staff else LeadForm
    if request.method == 'POST':
        form = form_class(request.POST, instance=lead)
        if form.is_valid():
            form.save()
            messages.success(request, 'Lead updated!')
            return redirect('lead_list')
    else:
        form = form_class(instance=lead)
    return render(request, 'leads/lead_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def lead_delete(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if not request.user.is_staff:
        try:
            if lead.partner != request.user.partner_profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')
            
    lead.delete()
    messages.success(request, 'Lead deleted!')
    return redirect('lead_list')
