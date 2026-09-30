from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Lead
from .forms import LeadForm

@login_required(login_url='/login/')
def lead_list(request):
    if request.user.is_staff:
        leads = Lead.objects.all().order_by('-created_at')
    else:
        try:
            leads = Lead.objects.filter(partner=request.user.partner_profile).order_by('-created_at')
        except:
            leads = []
            
    return render(request, 'leads/lead_list.html', {'leads': leads})

from .forms import LeadForm, AdminLeadForm

@login_required(login_url='/login/')
def lead_create(request):
    form_class = AdminLeadForm if request.user.is_staff else LeadForm
    
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            if not request.user.is_staff:
                try:
                    lead.partner = request.user.partner_profile
                except Exception as e:
                    messages.error(request, 'Error: You must have a Partner Profile to add leads.')
                    return redirect('lead_list')
            lead.save()
            messages.success(request, 'Lead successfully added!')
            return redirect('lead_list')
    else:
        form = form_class()
        
    return render(request, 'leads/lead_form.html', {'form': form})

@login_required(login_url='/login/')
def lead_update_status(request, lead_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('lead_list')
        
    if request.method == 'POST':
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

from django.shortcuts import get_object_or_404

@login_required(login_url='/login/')
def lead_update(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if not request.user.is_staff and lead.partner != request.user.partner_profile:
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
def lead_delete(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if not request.user.is_staff and lead.partner != request.user.partner_profile:
        return redirect('dashboard')
    lead.delete()
    messages.success(request, 'Lead deleted!')
    return redirect('lead_list')
