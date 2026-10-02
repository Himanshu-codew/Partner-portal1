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
    """Return count of unread notifications (items created after last_read_at)."""
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return 0
    from support.models import Ticket
    from partners.models import PartnerProfile
    from leads.models import Lead
    from orders.models import Order
    from portal_content.models import Announcement
    from core.models import UserNotificationRead
    from django.utils import timezone
    import datetime

    user = request.user

    # Get last-read timestamp
    try:
        last_read = user.notification_read.last_read_at
    except UserNotificationRead.DoesNotExist:
        last_read = timezone.now() - datetime.timedelta(days=7)

    count = 0
    if user.is_staff:
        count += Ticket.objects.filter(status__in=['OPEN', 'IN_PROGRESS'], created_at__gt=last_read).count()
        count += PartnerProfile.objects.filter(is_approved=False, is_deleted=False, created_at__gt=last_read).count()
        count += Lead.objects.filter(created_at__gt=last_read).count()
        count += Order.objects.filter(created_at__gt=last_read).count()
    else:
        try:
            profile = user.partner_profile
            count += Ticket.objects.filter(partner=profile, updated_at__gt=last_read).count()
            count += Lead.objects.filter(partner=profile, created_at__gt=last_read).count()
            count += Order.objects.filter(partner=profile, is_commission_paid=True, created_at__gt=last_read).count()
        except Exception:
            pass

    return min(count, 99)  # cap display
