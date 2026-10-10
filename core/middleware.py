from django.shortcuts import redirect
from django.urls import reverse, NoReverseMatch
from django.http import JsonResponse
from partners.utils import get_partner_profile

class PartnerApprovalMiddleware:
    """
    Guards non-staff users:
    If the user has no PartnerProfile or the profile is not approved,
    they can log in and see only the approval-pending page, profile, and logout.
    Leads, orders, tickets, documents, announcements, and dashboard data are unreachable until approved.
    Staff users are unaffected.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Attach partner_profile safely to request for all downstream views & templates
        if getattr(request, 'user', None) and request.user.is_authenticated:
            request.partner_profile = get_partner_profile(request.user)
        else:
            request.partner_profile = None

        if getattr(request, 'user', None) and request.user.is_authenticated and not request.user.is_staff:
            profile = request.partner_profile
            is_approved = bool(profile and profile.is_approved)

            if not is_approved:
                path = request.path
                
                # Build allowed prefixes
                allowed_prefixes = ['/static/', '/media/']
                # PWA assets must be reachable while waiting for approval so the
                # installable app and its offline page keep working.
                allowed_prefixes += ['/manifest.webmanifest', '/service-worker.js', '/offline/']
                # Password reset pages must stay reachable while waiting for
                # approval (matched as prefixes because the confirm URL carries
                # uid/token arguments).
                allowed_prefixes += ['/password-reset/', '/reset/']
                for view_name in ['logout', 'profile', 'profile_edit', 'password_change', 'approval_pending']:
                    try:
                        allowed_prefixes.append(reverse(view_name))
                    except NoReverseMatch:
                        pass

                is_allowed = any(path.startswith(prefix) for prefix in allowed_prefixes)

                if not is_allowed:
                    # For AJAX / JSON requests, return 403 Forbidden with JSON
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or path.startswith('/notifications/'):
                        return JsonResponse({
                            'error': 'Account waiting for approval.',
                            'notifications': [],
                            'unread_count': 0
                        }, status=403)
                    
                    try:
                        return redirect('approval_pending')
                    except NoReverseMatch:
                        return redirect('/approval-pending/')
            else:
                # If approved partner visits approval_pending, send them to dashboard
                try:
                    if request.path == reverse('approval_pending'):
                        return redirect('dashboard')
                except NoReverseMatch:
                    pass

        return self.get_response(request)
