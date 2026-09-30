from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Order

@login_required(login_url='/login/')
def order_list(request):
    if request.user.is_staff:
        orders = Order.objects.all().order_by('-created_at')
    else:
        try:
            orders = Order.objects.filter(partner=request.user.partner_profile).order_by('-created_at')
        except:
            orders = []
            
    return render(request, 'orders/order_list.html', {'orders': orders})

@login_required(login_url='/login/')
def commission_list(request):
    if request.user.is_staff:
        orders = Order.objects.all().order_by('-created_at')
    else:
        try:
            orders = Order.objects.filter(partner=request.user.partner_profile).order_by('-created_at')
        except:
            orders = []
            
    return render(request, 'orders/commission_list.html', {'orders': orders})

from django.shortcuts import redirect
from django.contrib import messages
from .forms import OrderForm

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
def order_update_status(request, order_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('order_list')
        
    if request.method == 'POST':
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

from django.shortcuts import get_object_or_404

@login_required(login_url='/login/')
def order_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if not request.user.is_staff and order.partner != request.user.partner_profile:
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
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if not request.user.is_staff and order.partner != request.user.partner_profile:
        return redirect('dashboard')
    order.delete()
    messages.success(request, 'Order deleted!')
    return redirect('order_list')
