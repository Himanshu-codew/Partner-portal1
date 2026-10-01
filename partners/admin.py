from django.contrib import admin
from .models import PartnerProfile

@admin.register(PartnerProfile)
class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company_name', 'phone_number', 'is_approved', 'created_at')
    list_filter = ('is_approved',)
    search_fields = ('user__username', 'company_name', 'phone_number')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    
    actions = ['approve_partners', 'revoke_approval']

    @admin.action(description='Approve selected partners')
    def approve_partners(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} partners successfully approved.')

    @admin.action(description='Revoke approval for selected partners')
    def revoke_approval(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'Approval revoked for {updated} partners.')
