from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Ticket
from .forms import TicketForm, AdminTicketForm
from partners.models import PartnerProfile

@login_required(login_url='/login/')
def ticket_list(request):
    if request.user.is_staff:
        tickets_qs = Ticket.objects.all().order_by('-created_at')
    else:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.warning(request, "Your account is pending approval.")
                return redirect('dashboard')
            tickets_qs = Ticket.objects.filter(partner=profile).order_by('-created_at')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to view tickets.')
            return redirect('dashboard')

    search_query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    if search_query:
        tickets_qs = tickets_qs.filter(
            Q(subject__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    if status_filter:
        tickets_qs = tickets_qs.filter(status=status_filter)

    paginator = Paginator(tickets_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
            
    return render(request, 'support/ticket_list.html', {
        'tickets': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'statuses': dict(Ticket.STATUS_CHOICES)
    })

@login_required(login_url='/login/')
def ticket_create(request):
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.error(request, 'Your account must be approved to create tickets.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to create tickets.')
            return redirect('dashboard')

    form_class = AdminTicketForm if request.user.is_staff else TicketForm
    
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            if not request.user.is_staff:
                ticket.partner = request.user.partner_profile
            ticket.save()
            messages.success(request, 'Support ticket successfully created!')
            return redirect('ticket_list')
    else:
        form = form_class()
        
    return render(request, 'support/ticket_form.html', {'form': form})

@login_required(login_url='/login/')
@require_POST
def ticket_update_status(request, ticket_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('ticket_list')
        
    try:
        ticket = Ticket.objects.get(id=ticket_id)
        new_status = request.POST.get('status')
        if new_status in dict(Ticket.STATUS_CHOICES):
            ticket.status = new_status
            ticket.save()
            messages.success(request, f'Ticket #{ticket.id} status updated to {ticket.get_status_display()}.')
    except Ticket.DoesNotExist:
        messages.error(request, 'Ticket not found.')
            
    return redirect('ticket_list')

@login_required(login_url='/login/')
def ticket_update(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if ticket.partner != profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')

    form_class = AdminTicketForm if request.user.is_staff else TicketForm
    if request.method == 'POST':
        form = form_class(request.POST, instance=ticket)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ticket updated!')
            return redirect('ticket_list')
    else:
        form = form_class(instance=ticket)
    return render(request, 'support/ticket_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def ticket_delete(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if ticket.partner != profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')
            
    ticket.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('ticket_list')
