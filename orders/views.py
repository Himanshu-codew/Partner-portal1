from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Order
from .forms import OrderForm
from partners.models import PartnerProfile

@login_required(login_url='/login/')
def order_list(request):
    if request.user.is_staff:
        orders_qs = Order.objects.all().order_by('-created_at')
    else:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.warning(request, "Your account is pending approval.")
                return redirect('dashboard')
            orders_qs = Order.objects.filter(partner=profile).order_by('-created_at')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to view orders.')
            return redirect('dashboard')

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
        orders_qs = Order.objects.all().order_by('-created_at')
    else:
        try:
            profile = request.user.partner_profile
            if not profile.is_approved:
                messages.warning(request, "Your account is pending approval.")
                return redirect('dashboard')
            orders_qs = Order.objects.filter(partner=profile).order_by('-created_at')
        except PartnerProfile.DoesNotExist:
            messages.error(request, 'Error: You must have a Partner Profile to view commissions.')
            return redirect('dashboard')

    paginator = Paginator(orders_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
            
    return render(request, 'orders/commission_list.html', {
        'orders': page_obj,
        'page_obj': page_obj
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
        
    try:
        order = Order.objects.get(id=order_id)
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            order.save()
            messages.success(request, f'Order #{order.id} status updated to {order.get_status_display()}.')
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
            
    return redirect('order_list')

@login_required(login_url='/login/')
def order_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if order.partner != profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')
        
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
    order = get_object_or_404(Order, pk=pk)
    if not request.user.is_staff:
        try:
            profile = request.user.partner_profile
            if order.partner != profile:
                messages.error(request, 'Unauthorized.')
                return redirect('dashboard')
        except PartnerProfile.DoesNotExist:
            return redirect('dashboard')
            
    order.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('order_list')
