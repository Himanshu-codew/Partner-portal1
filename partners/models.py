from django.db import models
from django.contrib.auth.models import User
from core.models import SoftDeleteModel

class PartnerProfile(SoftDeleteModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='partner_profile')
    company_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    address = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Contact & notification preferences (Phase 2A)
    whatsapp_number = models.CharField(
        max_length=20, blank=True, default='',
        help_text='WhatsApp number in E.164 format, e.g. +919876543210.'
    )
    whatsapp_opt_in = models.BooleanField(default=False)
    whatsapp_opt_in_at = models.DateTimeField(null=True, blank=True)
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.company_name}"
