from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.models import User, Group
from .models import PartnerProfile
from .forms import UserForm, GroupForm, PartnerProfileForm

@login_required(login_url='/login/')
def partner_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    partners = PartnerProfile.objects.all().order_by('-created_at')
    return render(request, 'partners/partner_list.html', {'partners': partners})

@login_required(login_url='/login/')
@require_POST
def partner_approve(request, profile_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    try:
        profile = PartnerProfile.objects.get(id=profile_id)
        is_approved = request.POST.get('is_approved') == 'true'
        profile.is_approved = is_approved
        profile.save()
        status_text = "Approved" if is_approved else "Rejected"
        messages.success(request, f'Partner {profile.company_name} status updated to {status_text}.')
    except PartnerProfile.DoesNotExist:
        messages.error(request, 'Partner not found.')
            
    return redirect('partner_list')

@login_required(login_url='/login/')
def partner_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = PartnerProfileForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Partner Profile successfully created!')
            return redirect('partner_list')
    else:
        form = PartnerProfileForm()
    return render(request, 'partners/partner_form.html', {'form': form})

@login_required(login_url='/login/')
def user_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'partners/user_list.html', {'users': users})

@login_required(login_url='/login/')
def user_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'User successfully created!')
            return redirect('user_list')
    else:
        form = UserForm()
    return render(request, 'partners/user_form.html', {'form': form})

@login_required(login_url='/login/')
def group_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    groups = Group.objects.all()
    return render(request, 'partners/group_list.html', {'groups': groups})

@login_required(login_url='/login/')
def group_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Group successfully created!')
            return redirect('group_list')
    else:
        form = GroupForm()
    return render(request, 'partners/group_form.html', {'form': form})

@login_required(login_url='/login/')
def partner_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    partner = get_object_or_404(PartnerProfile, pk=pk)
    if request.method == 'POST':
        form = PartnerProfileForm(request.POST, instance=partner)
        if form.is_valid():
            form.save()
            messages.success(request, 'Partner updated!')
            return redirect('partner_list')
    else:
        form = PartnerProfileForm(instance=partner)
    return render(request, 'partners/partner_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def partner_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    partner = get_object_or_404(PartnerProfile, pk=pk)
    partner.soft_delete(request.user)
    partner.user.is_active = False
    partner.user.save()
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('partner_list')

@login_required(login_url='/login/')
def user_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    u = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=u)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated!')
            return redirect('user_list')
    else:
        form = UserForm(instance=u)
    return render(request, 'partners/user_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def user_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    u = get_object_or_404(User, pk=pk)
    u.is_active = not u.is_active
    u.save()
    status = 'activated' if u.is_active else 'deactivated'
    messages.success(request, f'User {status}!')
    return redirect('user_list')

@login_required(login_url='/login/')
def group_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    g = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=g)
        if form.is_valid():
            form.save()
            messages.success(request, 'Group updated!')
            return redirect('group_list')
    else:
        form = GroupForm(instance=g)
    return render(request, 'partners/group_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def group_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    g = get_object_or_404(Group, pk=pk)
    g.delete()
    messages.success(request, 'Group deleted!')
    return redirect('group_list')
