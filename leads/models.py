from django.db import models
from partners.models import PartnerProfile

class Lead(models.Model):
    STATUS_CHOICES = (
        ('NEW', 'New'),
        ('IN_PROGRESS', 'In Progress'),
        ('CONVERTED', 'Converted'),
        ('LOST', 'Lost'),
    )

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='leads')
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20)
    product_interest = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer_name} - {self.status}"
