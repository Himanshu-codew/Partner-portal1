from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.models import User, Group
from django.db.models import Q
from django.core.paginator import Paginator
from .models import PartnerProfile
from .forms import UserForm, GroupForm, PartnerProfileForm

def on_partner_approval_changed(profile):
    """
    Hook called when a partner's approval status changes.
    Currently a no-op; reserved for notifications.
    """
    pass

@login_required(login_url='/login/')
def partner_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    partners_qs = PartnerProfile.objects.select_related('user').all().order_by('-created_at')
    
    if query:
        partners_qs = partners_qs.filter(
            Q(company_name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query)
        )
        
    paginator = Paginator(partners_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/partner_list.html', {'page_obj': page_obj})

@login_required(login_url='/login/')
@require_POST
def partner_approve(request, profile_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    profile = get_object_or_404(PartnerProfile, id=profile_id)
    is_approved = request.POST.get('is_approved') == 'true'
    profile.is_approved = is_approved
    profile.save()
    on_partner_approval_changed(profile)
    status_text = "Approved" if is_approved else "Rejected"
    messages.success(request, f'Partner {profile.company_name} status updated to {status_text}.')
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
        
    query = request.GET.get('q', '')
    users_qs = User.objects.filter(is_active=True).prefetch_related('groups').order_by('-date_joined')
    
    if query:
        users_qs = users_qs.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
        
    paginator = Paginator(users_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/user_list.html', {'page_obj': page_obj})

@login_required(login_url='/login/')
def user_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = UserForm(request.POST, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User successfully created!')
            return redirect('user_list')
    else:
        form = UserForm(current_user=request.user)
    return render(request, 'partners/user_form.html', {'form': form})

@login_required(login_url='/login/')
def group_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    groups_qs = Group.objects.prefetch_related('permissions').all().order_by('name')
    
    if query:
        groups_qs = groups_qs.filter(name__icontains=query)
        
    paginator = Paginator(groups_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/group_list.html', {'page_obj': page_obj})

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

    # Rule 3.2: A non-superuser staff member cannot edit a superuser account
    if u.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only superusers can edit superuser accounts.")
        return redirect('user_list')

    if request.method == 'POST':
        form = UserForm(request.POST, instance=u, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated!')
            return redirect('user_list')
    else:
        form = UserForm(instance=u, current_user=request.user)
    return render(request, 'partners/user_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def user_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    u = get_object_or_404(User, pk=pk)
    
    # Rule 3.3: Prevent deleting yourself
    if u == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('user_list')

    # Rule 3.2: A non-superuser staff member cannot delete a superuser account
    if u.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only superusers can delete superuser accounts.")
        return redirect('user_list')

    # Rule 3.3: The last remaining active superuser can never be deleted
    if u.is_superuser and u.is_active:
        active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=u.pk)
        if not active_superusers.exists():
            messages.error(request, "The last remaining active superuser cannot be deleted.")
            return redirect('user_list')
        
    u.is_active = False
    u.save()
    messages.success(request, f"User '{u.username}' moved to Recycle Bin.")
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
