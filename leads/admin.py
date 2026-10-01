from django.contrib import admin
from .models import Lead

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('customer_name', 'partner', 'product_interest', 'status', 'created_at')
    list_filter = ('status', 'partner')
    search_fields = ('customer_name', 'customer_phone', 'partner__company_name')
    list_editable = ('status',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
