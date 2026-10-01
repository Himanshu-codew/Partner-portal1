from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.apps import apps
from django.core.exceptions import PermissionDenied

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
    if active_tab not in models_map:
        active_tab = 'partnerprofile'
        
    context = {'active_tab': active_tab, 'tabs': {}}
    
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
        
    models_map = get_soft_deleted_models()
    if model_name in models_map:
        model = models_map[model_name]
        count = model.deleted_objects.count()
        model.deleted_objects.all().delete() # This calls the queryset delete. Wait, SoftDeleteQuerySet overrides delete!
        # I must call hard_delete() on the queryset if implemented, or loop, or use super() inside manager
        # Actually, let's just do it in a loop to be safe and trigger signals, or implement hard_delete on SoftDeleteQuerySet
        for item in model.deleted_objects.all():
            item.hard_delete()
        messages.success(request, f"Permanently deleted {count} {model._meta.verbose_name_plural}.")
    return redirect(f'/recycle-bin/?tab={model_name}')
