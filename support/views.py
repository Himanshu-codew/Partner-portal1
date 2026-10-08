from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from core.services import notify
from .models import Ticket
from .forms import TicketForm, AdminTicketForm, TicketReplyForm
from partners.utils import get_partner_profile, user_can_access_object

@login_required(login_url='/login/')
def ticket_list(request):
    if request.user.is_staff:
        tickets_qs = Ticket.objects.select_related('partner', 'partner__user').all().order_by('-created_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')
        tickets_qs = Ticket.objects.select_related('partner', 'partner__user').filter(partner=profile).order_by('-created_at')

    tickets_qs = tickets_qs.annotate(reply_count=Count('replies', distinct=True))

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
    profile = None
    if not request.user.is_staff:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.error(request, 'Your account must be approved to create tickets.')
            return redirect('approval_pending')

    form_class = AdminTicketForm if request.user.is_staff else TicketForm
    
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            if not request.user.is_staff:
                ticket.partner = profile
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
        
    ticket = get_object_or_404(Ticket, id=ticket_id)
    new_status = request.POST.get('status')
    if new_status in dict(Ticket.STATUS_CHOICES):
        ticket.status = new_status
        ticket.save()
        messages.success(request, f'Ticket #{ticket.id} status updated to {ticket.get_status_display()}.')
            
    return redirect('ticket_list')

@login_required(login_url='/login/')
def ticket_update(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    
    if not user_can_access_object(request.user, ticket):
        messages.error(request, 'Unauthorized access.')
        return redirect('ticket_list')

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
    if not user_can_access_object(request.user, ticket):
        messages.error(request, 'Unauthorized access.')
        return redirect('ticket_list')
            
    ticket.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('ticket_list')

@login_required(login_url='/login/')
def ticket_detail(request, pk):
    """Conversation thread for one ticket: messages, replies, reply form."""
    ticket = get_object_or_404(
        Ticket.objects.select_related('partner', 'partner__user'), pk=pk
    )
    if not user_can_access_object(request.user, ticket):
        messages.error(request, 'You do not have permission to view this ticket.')
        return redirect('ticket_list')

    can_reply = request.user.is_staff or ticket.status != 'CLOSED'
    return render(request, 'support/ticket_detail.html', {
        'ticket': ticket,
        'replies': ticket.replies.select_related('author'),
        'form': TicketReplyForm(),
        'can_reply': can_reply,
    })

@login_required(login_url='/login/')
@require_POST
def ticket_reply(request, pk):
    """Post one message onto a ticket's conversation thread."""
    ticket = get_object_or_404(Ticket, pk=pk)
    if not user_can_access_object(request.user, ticket):
        messages.error(request, 'You do not have permission to reply to this ticket.')
        return redirect('ticket_list')

    if not request.user.is_staff and ticket.status == 'CLOSED':
        messages.error(request, 'This ticket is closed. Raise a new ticket if you need more help.')
        return redirect('ticket_detail', pk=ticket.pk)

    form = TicketReplyForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect('ticket_detail', pk=ticket.pk)

    reply = form.save(commit=False)
    reply.ticket = ticket
    reply.author = request.user
    reply.source = 'portal'
    reply.save()
    ticket.save()  # bump updated_at

    if request.user.is_staff:
        notify(
            ticket.partner.user,
            'ticket_reply',
            {'ticket': ticket, 'reply': reply, 'actor': request.user},
        )
        messages.success(request, 'Reply sent to the partner.')
    else:
        messages.success(request, 'Reply posted.')

    return redirect('ticket_detail', pk=ticket.pk)
