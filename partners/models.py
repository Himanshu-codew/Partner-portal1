from django.db import models
from django.contrib.auth.models import User

class PartnerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='partner_profile')
    company_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    address = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.company_name}"
