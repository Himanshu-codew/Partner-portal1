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

