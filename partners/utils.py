from django.core.exceptions import ObjectDoesNotExist
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def get_partner_profile(user):
    """
    Safely retrieves the PartnerProfile for a user, or None if not found or unauthenticated.
    Never raises an exception.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    try:
        return user.partner_profile
    except (ObjectDoesNotExist, AttributeError):
        return None


def user_can_access_object(user, obj, partner_field='partner'):
    """
    Returns True if user is staff or if the object belongs to the user's PartnerProfile.
    Returns False otherwise. Never raises an exception.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False):
        return True
    profile = get_partner_profile(user)
    if not profile or not getattr(profile, 'is_approved', False):
        return False
    if hasattr(obj, partner_field):
        obj_partner = getattr(obj, partner_field)
        return obj_partner is not None and obj_partner.pk == profile.pk
    # If the object itself is a PartnerProfile
    from partners.models import PartnerProfile
    if isinstance(obj, PartnerProfile):
        return obj.pk == profile.pk
    return False


def approved_partner_required(view_func):
    """
    Decorator for views that require an approved partner profile or staff access.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.is_staff:
            return view_func(request, *args, **kwargs)
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
