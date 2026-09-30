from django.contrib import admin
from .models import Order

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'partner', 'amount', 'commission_amount', 'is_commission_paid', 'status', 'created_at')
    list_filter = ('status', 'is_commission_paid', 'partner')
    search_fields = ('order_number', 'partner__company_name')
