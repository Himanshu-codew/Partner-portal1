from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, F, ExpressionWrapper, DecimalField
from .models import Order
from .forms import OrderForm
from partners.utils import get_partner_profile

def on_commission_paid(order):
    """
    Hook called when an order's commission is marked as paid.
    Currently does nothing; reserved for future notifications.
    """
    pass

@login_required(login_url='/login/')
def order_list(request):
    if request.user.is_staff:
        orders_qs = Order.objects.select_related('partner', 'partner__user', 'lead').all().order_by('-created_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')
        orders_qs = Order.objects.select_related('partner', 'partner__user', 'lead').filter(partner=profile).order_by('-created_at')

    search_query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    if search_query:
        orders_qs = orders_qs.filter(
            Q(order_number__icontains=search_query) |
            Q(partner__company_name__icontains=search_query)
        )
    if status_filter:
        orders_qs = orders_qs.filter(status=status_filter)

    paginator = Paginator(orders_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
            
    return render(request, 'orders/order_list.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'statuses': dict(Order.STATUS_CHOICES)
    })

@login_required(login_url='/login/')
def commission_list(request):
    if request.user.is_staff:
        orders_qs = Order.objects.select_related('partner', 'partner__user').all().order_by('-created_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')
        orders_qs = Order.objects.select_related('partner', 'partner__user').filter(partner=profile).order_by('-created_at')

    total_earned = orders_qs.filter(is_commission_paid=True).aggregate(total=Sum('commission_amount'))['total'] or 0
    pending_commission = orders_qs.filter(is_commission_paid=False).aggregate(total=Sum('commission_amount'))['total'] or 0
    total_orders = orders_qs.count()

    # Admin-specific: Net Revenue = Total Amount collected - Total Commission paid out
    total_amount_collected = orders_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_commission_all = orders_qs.aggregate(total=Sum('commission_amount'))['total'] or 0
    admin_net_revenue = total_amount_collected - total_commission_all
    admin_total_revenue = total_amount_collected

    # Annotate each order with net_profit for admin table
    orders_qs = orders_qs.annotate(
        net_profit=ExpressionWrapper(F('amount') - F('commission_amount'), output_field=DecimalField())
    )

    # Card filter: ?filter=paid / pending / all
    commission_filter = request.GET.get('filter', 'all')
    if commission_filter == 'paid':
        orders_qs = orders_qs.filter(is_commission_paid=True)
    elif commission_filter == 'pending':
        orders_qs = orders_qs.filter(is_commission_paid=False)

    paginator = Paginator(orders_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
            
    return render(request, 'orders/commission_list.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'total_earned': total_earned,
        'pending_commission': pending_commission,
        'total_orders': total_orders,
        'admin_net_revenue': admin_net_revenue,
        'admin_total_revenue': admin_total_revenue,
        'is_staff': request.user.is_staff,
        'commission_filter': commission_filter,
    })

@login_required(login_url='/login/')
def order_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Order successfully created!')
            return redirect('order_list')
    else:
        form = OrderForm()
        
    return render(request, 'orders/order_form.html', {'form': form})

@login_required(login_url='/login/')
@require_POST
def order_update_status(request, order_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    if new_status in dict(Order.STATUS_CHOICES):
        order.status = new_status
        order.save()
        messages.success(request, f'Order #{order.order_number} status updated to {order.get_status_display()}.')
            
    return redirect('order_list')

@login_required(login_url='/login/')
def order_update(request, pk):
    # Rule 1.1: order_update is admin (is_staff) only
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, 'Order updated!')
            return redirect('order_list')
    else:
        form = OrderForm(instance=order)
    return render(request, 'orders/order_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def order_delete(request, pk):
    # Rule 1.1: order_delete is admin (is_staff) only
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    order.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('order_list')

@login_required(login_url='/login/')
@require_POST
def order_mark_commission_paid(request, pk):
    """Admin-only action to mark order commission as paid."""
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    order.is_commission_paid = True
    order.save()
    on_commission_paid(order)
    messages.success(request, f'Order #{order.order_number} marked as commission paid.')
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('order_list')

@login_required(login_url='/login/')
@require_POST
def order_mark_commission_unpaid(request, pk):
    """Admin-only action to mark order commission as unpaid."""
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    order.is_commission_paid = False
    order.save()
    messages.success(request, f'Order #{order.order_number} marked as commission unpaid.')
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('order_list')
