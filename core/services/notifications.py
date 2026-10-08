"""Notification service (Phase 2A/2B).

Fan-out of portal events (ticket replies, status changes, announcements…)
to the channels a user allows. Emails go through Django's configured
email backend (Brevo HTTPS API in production); WhatsApp goes through the
Twilio WhatsApp sandbox (``core.services.whatsapp``).

Design rules:
  * ``notify()`` never raises — delivery problems are logged, and every
    attempt is recorded in ``core.NotificationLog``.
  * Delivery runs inside ``transaction.on_commit`` so nothing escapes a
    transaction that later rolls back.
  * Identical events are deduplicated for a short window, and the daily
    volume of each channel is capped (``NOTIFY_EMAIL_DAILY_LIMIT`` /
    ``NOTIFY_WHATSAPP_DAILY_LIMIT``).
  * A failing channel can never take another channel down with it.
"""

import hashlib
import json
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import NotificationLog
from core.utils import normalize_phone
from core.services.whatsapp import get_provider
from partners.utils import get_partner_profile

logger = logging.getLogger('core.notifications')

# event name -> short email subject
EVENTS = {
    'ticket_reply': 'Support replied to your ticket',
    'lead_status_changed': 'Your lead status was updated',
    'order_status_changed': 'Your order status was updated',
    'commission_paid': 'Commission paid for your order',
    'partner_approval_changed': 'Your partner account status changed',
    'announcement_published': 'New announcement on the Partner Portal',
    'kyc_reviewed': 'Your KYC document was reviewed',
}

CHANNELS = ('email', 'whatsapp')

DEDUPE_TTL = 60           # seconds an identical event is suppressed for
QUOTA_TTL = 60 * 60 * 24  # lifetime of the daily channel counters
MAX_WA_BODY = 400         # characters — WhatsApp texts stay short


@dataclass
class ChannelResult:
    """Outcome of one delivery attempt (or of scheduling one)."""

    status: str
    error: str = ''
    # Provider receipt (Twilio SID) when an external provider delivered it.
    provider_message_id: str = ''

    def __str__(self):
        return self.status if not self.error else f'{self.status}: {self.error}'


def _redact(text):
    """Strip configured secrets from a string before it is recorded."""
    text = str(text)
    for secret in (
        getattr(settings, 'BREVO_API_KEY', ''),
        getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
        getattr(settings, 'TWILIO_AUTH_TOKEN', ''),
        getattr(settings, 'TWILIO_ACCOUNT_SID', ''),
    ):
        if secret and secret in text:
            text = text.replace(secret, '[redacted]')
    return text


def _short(text, limit=200):
    return ' '.join(_redact(str(text)).split())[:limit]


def _stable(value):
    """Make a context value JSON-safe and stable across processes."""
    if hasattr(value, '_meta') and hasattr(value, 'pk'):
        return f'{value.__class__.__name__}:{value.pk}'
    if isinstance(value, dict):
        return {str(k): _stable(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return str(value)


def _dedupe_key(user, event, context):
    payload = {
        key: _stable(value)
        for key, value in context.items()
        if key != 'actor'  # the actor does not change the message
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True).encode('utf-8')
    ).hexdigest()[:16]
    return f'notify:{user.pk}:{event}:{digest}'


def _quota_key():
    return f'notify:email-count:{timezone.localdate().isoformat()}'


def _email_quota_available():
    limit = getattr(settings, 'NOTIFY_EMAIL_DAILY_LIMIT', 200)
    if limit <= 0:
        return True
    return int(cache.get(_quota_key(), 0)) < limit


def _bump_email_quota():
    key = _quota_key()
    cache.add(key, 0, QUOTA_TTL)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, QUOTA_TTL)


def _whatsapp_quota_key():
    return f'notify:whatsapp-count:{timezone.localdate().isoformat()}'


def _whatsapp_quota_available():
    limit = getattr(settings, 'NOTIFY_WHATSAPP_DAILY_LIMIT', 50)
    if limit <= 0:
        return True
    return int(cache.get(_whatsapp_quota_key(), 0)) < limit


def _bump_whatsapp_quota():
    key = _whatsapp_quota_key()
    cache.add(key, 0, QUOTA_TTL)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, QUOTA_TTL)


def build_context(event, subject, user, context):
    full = dict(context)
    full.update({
        'event': event,
        'subject': subject,
        'recipient': user,
        'site_url': getattr(settings, 'SITE_URL', ''),
    })
    return full


class EmailChannel:
    """Plain Django email, sent through the configured email backend."""

    name = NotificationLog.CHANNEL_EMAIL

    def send(self, user, subject, context):
        email = (getattr(user, 'email', '') or '').strip()
        if not email:
            return ChannelResult('skipped', 'no email address')
        profile = get_partner_profile(user)
        # Staff (and other users without a profile) may always be emailed.
        if profile is not None and not profile.notify_email:
            return ChannelResult('skipped', 'email notifications disabled')
        if not _email_quota_available():
            return ChannelResult('skipped', 'daily email limit reached')

        template = f'notifications/{context["event"]}'
        text_body = render_to_string(f'{template}.txt', context)
        try:
            html_body = render_to_string(f'{template}.html', context)
        except TemplateDoesNotExist:
            html_body = None

        send_mail(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_body,
        )
        _bump_email_quota()
        return ChannelResult('sent')


class WhatsAppChannel:
    """
    Outbound WhatsApp text through the Twilio sandbox (Phase 2B).

    Every skip reason is reported instead of pretending to send, and a
    provider problem is returned as a ``failed`` result — never raised —
    so the email channel and the request are unaffected.
    """

    name = NotificationLog.CHANNEL_WHATSAPP

    def send(self, user, subject, context):
        if not getattr(settings, 'WHATSAPP_ENABLED', False):
            return ChannelResult('skipped', 'not configured')
        profile = get_partner_profile(user)
        if profile is None:
            return ChannelResult('skipped', 'no whatsapp profile')
        if not profile.is_approved:
            return ChannelResult('skipped', 'partner not approved')
        if not profile.whatsapp_opt_in or not profile.notify_whatsapp:
            return ChannelResult('skipped', 'whatsapp notifications disabled')
        if not profile.whatsapp_number:
            return ChannelResult('skipped', 'missing whatsapp number')
        try:
            number = normalize_phone(profile.whatsapp_number)
        except Exception:  # noqa: BLE001 - invalid stored number
            return ChannelResult('skipped', 'invalid whatsapp number')

        provider = get_provider()
        if provider is None:
            return ChannelResult('skipped', 'not configured')

        allowed = getattr(settings, 'WHATSAPP_ALLOWED_NUMBERS', None) or []
        if allowed and number not in allowed:
            return ChannelResult('skipped', 'number not in allowed list')
        if not _whatsapp_quota_available():
            return ChannelResult('skipped', 'daily whatsapp limit reached')

        body = self._build_body(context)
        if not body:
            return ChannelResult('failed', 'missing whatsapp template')

        result = provider.send_text(number, body)
        if not result.ok:
            error = (
                f'twilio {result.error_code}: {result.error_message}'
                if result.error_code else result.error_message
            )
            return ChannelResult('failed', error or 'send failed')

        _bump_whatsapp_quota()
        return ChannelResult('sent', provider_message_id=result.message_id)

    @staticmethod
    def _build_body(context):
        """Render the short plain text for this event (max 400 chars)."""
        template = f'notifications/{context["event"]}.wa.txt'
        try:
            body = render_to_string(template, context).strip()
        except TemplateDoesNotExist:
            return ''
        if len(body) > MAX_WA_BODY:
            body = body[:MAX_WA_BODY - 3].rstrip() + '...'
        return body


def _preflight(user, event, context):
    """Cheap checks run before anything is scheduled. None = go ahead."""
    if event not in EVENTS:
        return ChannelResult('skipped', 'unknown event')
    if user is None or not getattr(user, 'is_authenticated', False):
        return ChannelResult('skipped', 'no recipient')
    if not getattr(user, 'is_active', False):
        return ChannelResult('skipped', 'inactive user')
    actor = context.get('actor')
    if actor is not None and getattr(actor, 'pk', None) == user.pk:
        return ChannelResult('skipped', 'actor is recipient')
    profile = get_partner_profile(user)
    if profile is not None and not profile.is_approved and event != 'partner_approval_changed':
        return ChannelResult('skipped', 'partner not approved')
    return None


def notify(user, event, context=None):
    """
    Schedule delivery of ``event`` to ``user``.

    Returns a :class:`ChannelResult` describing the scheduling decision
    (``queued`` when delivery was scheduled, ``skipped`` with a reason
    otherwise). The per-channel results are written to NotificationLog
    once the surrounding transaction commits.
    """
    context = dict(context or {})
    try:
        blocked = _preflight(user, event, context)
        if blocked is not None:
            logger.info('notification %s skipped for %s: %s', event, user, blocked.error)
            return blocked

        dedupe_key = _dedupe_key(user, event, context)
        if cache.get(dedupe_key):
            return ChannelResult('skipped', 'duplicate')

        transaction.on_commit(lambda: _deliver(user, event, context, dedupe_key))
        return ChannelResult('queued')
    except Exception as exc:  # noqa: BLE001 - notify must never raise
        logger.exception('notify(%s) failed: %s', event, _short(exc))
        return ChannelResult('failed', _short(exc))


def _deliver(user, event, context, dedupe_key):
    """Actually send the message. Runs after the transaction commits."""
    try:
        # Re-check: a concurrent call may have delivered it already.
        if cache.get(dedupe_key):
            return
        cache.set(dedupe_key, 1, DEDUPE_TTL)

        subject = EVENTS[event]
        full_context = build_context(event, subject, user, context)

        for channel in (EmailChannel(), WhatsAppChannel()):
            try:
                result = channel.send(user, subject, full_context)
            except Exception as exc:  # noqa: BLE001 - keep going
                logger.error('notification %s via %s failed: %s', event, channel.name, _short(exc))
                result = ChannelResult('failed', _short(exc))

            NotificationLog.objects.create(
                user=user,
                event=event,
                channel=channel.name,
                status=result.status,
                error=_redact(result.error)[:200],
                provider_message_id=(result.provider_message_id or '')[:100],
            )
            logger.info('notification %s via %s: %s', event, channel.name, result)
    except Exception as exc:  # noqa: BLE001 - notify must never raise
        logger.exception('delivery of %s failed: %s', event, _short(exc))
