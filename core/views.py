from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User

def get_soft_deleted_models():
    # Dictionary of model name to actual model class
    return {
        'partnerprofile': apps.get_model('partners', 'PartnerProfile'),
        'lead': apps.get_model('leads', 'Lead'),
        'order': apps.get_model('orders', 'Order'),
        'ticket': apps.get_model('support', 'Ticket'),
        'announcement': apps.get_model('portal_content', 'Announcement'),
        'document': apps.get_model('portal_content', 'Document'),
    }

@login_required(login_url='/login/')
def recycle_bin(request):
    if not request.user.is_staff:
        raise PermissionDenied
        
    models_map = get_soft_deleted_models()
    active_tab = request.GET.get('tab', 'partnerprofile')
    if active_tab not in models_map and active_tab != 'user':
        active_tab = 'partnerprofile'
        
    context = {'active_tab': active_tab, 'tabs': {}}
    
    # Custom logic for User
    deleted_users = list(User.objects.filter(is_active=False).order_by('-date_joined'))
    for u in deleted_users:
        u.deleted_at = u.last_login or u.date_joined
        u.deleted_by = None
        
    context['tabs']['user'] = {
        'verbose_name': 'Users',
        'count': len(deleted_users),
        'items': deleted_users if active_tab == 'user' else []
    }
    
    for name, model in models_map.items():
        deleted_items = model.deleted_objects.all().order_by('-deleted_at')
        context['tabs'][name] = {
            'verbose_name': model._meta.verbose_name_plural.title(),
            'count': deleted_items.count(),
            'items': deleted_items if name == active_tab else []
        }
        
    return render(request, 'core/recycle_bin.html', context)

@login_required(login_url='/login/')
@require_POST
def restore_item(request, model_name, pk):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        from django.contrib.auth.models import User
        user = get_object_or_404(User, pk=pk)
        user.is_active = True
        user.save()
        messages.success(request, "User successfully restored.")
        return redirect(f'/recycle-bin/?tab={model_name}')
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        item = get_object_or_404(model.deleted_objects.all(), pk=pk)
        item.restore()
        
        # Special logic for PartnerProfile restore
        if model_name == 'partnerprofile':
            item.user.is_active = True
            item.user.save()
            
        messages.success(request, f"{model._meta.verbose_name.title()} successfully restored.")
    return redirect(f'/recycle-bin/?tab={model_name}')

@login_required(login_url='/login/')
@require_POST
def hard_delete_item(request, model_name, pk):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        from django.contrib.auth.models import User
        user = get_object_or_404(User, pk=pk)
        user.delete()
        messages.success(request, "User permanently deleted.")
        return redirect(f'/recycle-bin/?tab={model_name}')
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        item = get_object_or_404(model.deleted_objects.all(), pk=pk)
        item.hard_delete()
        messages.success(request, f"{model._meta.verbose_name.title()} permanently deleted.")
    return redirect(f'/recycle-bin/?tab={model_name}')

@login_required(login_url='/login/')
@require_POST
def empty_bin(request, model_name):
    if not request.user.is_staff:
        raise PermissionDenied
        
    if model_name == 'user':
        users = User.objects.filter(is_active=False)
        count = users.count()
        users.delete()
        messages.success(request, f"Permanently deleted {count} Users.")
        return redirect(f'/recycle-bin/?tab={model_name}')
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        count = model.deleted_objects.count()
        for item in model.deleted_objects.all():
            item.hard_delete()
        messages.success(request, f"Permanently deleted {count} {model._meta.verbose_name_plural}.")
    return redirect(f'/recycle-bin/?tab={model_name}')
