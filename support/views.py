from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Ticket
from .forms import TicketForm

@login_required(login_url='/login/')
def ticket_list(request):
    if request.user.is_staff:
        tickets = Ticket.objects.all().order_by('-created_at')
    else:
        try:
            tickets = Ticket.objects.filter(partner=request.user.partner_profile).order_by('-created_at')
        except:
            tickets = []
            
    return render(request, 'support/ticket_list.html', {'tickets': tickets})

from .forms import TicketForm, AdminTicketForm

@login_required(login_url='/login/')
def ticket_create(request):
    form_class = AdminTicketForm if request.user.is_staff else TicketForm
    
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            if not request.user.is_staff:
                try:
                    ticket.partner = request.user.partner_profile
                except Exception as e:
                    messages.error(request, 'Error: You must have a Partner Profile to create tickets.')
                    return redirect('ticket_list')
            ticket.save()
            messages.success(request, 'Support ticket successfully created!')
            return redirect('ticket_list')
    else:
        form = form_class()
        
    return render(request, 'support/ticket_form.html', {'form': form})

@login_required(login_url='/login/')
def ticket_update_status(request, ticket_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('ticket_list')
        
    if request.method == 'POST':
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

from django.shortcuts import get_object_or_404

@login_required(login_url='/login/')
def ticket_update(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_staff and ticket.partner != request.user.partner_profile:
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
def ticket_delete(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_staff and ticket.partner != request.user.partner_profile:
        return redirect('dashboard')
    ticket.delete()
    messages.success(request, 'Ticket deleted!')
    return redirect('ticket_list')
