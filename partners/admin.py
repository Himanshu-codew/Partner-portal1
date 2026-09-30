from django.contrib import admin
from .models import PartnerProfile

@admin.register(PartnerProfile)
class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company_name', 'phone_number', 'is_approved', 'created_at')
    list_filter = ('is_approved',)
    search_fields = ('user__username', 'company_name', 'phone_number')
