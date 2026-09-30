from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('subject', 'partner', 'status', 'created_at')
    list_filter = ('status', 'partner')
    search_fields = ('subject', 'partner__company_name')
