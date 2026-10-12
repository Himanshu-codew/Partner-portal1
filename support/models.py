from core.models import SoftDeleteModel
from django.contrib.auth.models import User
from django.db import models
from partners.models import PartnerProfile

class Ticket(SoftDeleteModel):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    )

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='tickets')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    admin_reply = models.TextField(blank=True, null=True, help_text='Admin response visible to the partner.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.subject} - {self.status}"


class TicketReply(models.Model):
    """One message in a support ticket conversation thread."""

    SOURCE_CHOICES = (
        ('portal', 'Portal'),
        ('whatsapp', 'WhatsApp'),
    )

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='ticket_replies'
    )
    message = models.TextField()
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='portal')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        who = self.author.username if self.author else 'system'
        return f"Reply on ticket #{self.ticket_id} by {who}"

    @property
    def is_staff_reply(self):
        return self.author is None or self.author.is_staff


class InboundWhatsAppMessage(models.Model):
    """One inbound webhook message from the 360dialog provider.

    Stored mainly for idempotency: ``wa_message_id`` is the provider message
    id, so a re-delivered webhook is recognised and ignored. Never holds any
    API key or credential.
    """

    STATUS_PROCESSED = 'processed'
    STATUS_IGNORED = 'ignored'
    STATUS_DUPLICATE = 'duplicate'
    STATUS_CHOICES = (
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_IGNORED, 'Ignored'),
        (STATUS_DUPLICATE, 'Duplicate'),
    )

    wa_message_id = models.CharField(max_length=200, unique=True)
    from_number = models.CharField(max_length=32, blank=True, default='')
    body = models.TextField(blank=True, default='')
    matched_ticket = models.ForeignKey(
        Ticket, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='inbound_whatsapp_messages',
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_IGNORED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.wa_message_id} ({self.status})"

