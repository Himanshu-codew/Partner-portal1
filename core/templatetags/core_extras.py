from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key) if isinstance(dictionary, dict) else None

@register.simple_tag
def get_recycle_bin_count():
    from core.views import get_soft_deleted_models
    count = sum(model.deleted_objects.count() for model in get_soft_deleted_models().values())
    return count

@register.simple_tag(takes_context=True)
def get_notifications_count(context):
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return 0
    from support.models import Ticket
    from portal_content.models import Announcement
    from django.utils import timezone
    import datetime
    
    recent_date = timezone.now() - datetime.timedelta(days=7)
    announcements = Announcement.objects.filter(is_active=True, created_at__gte=recent_date).count()
    
    tickets = 0
    if request.user.is_staff:
        tickets = Ticket.objects.filter(status__in=['OPEN', 'IN_PROGRESS']).count()
    else:
        try:
            profile = request.user.partner_profile
            tickets = Ticket.objects.filter(partner=profile, status__in=['OPEN', 'IN_PROGRESS']).count()
        except:
            pass
            
    return announcements + tickets
