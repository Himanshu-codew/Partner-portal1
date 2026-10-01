from django.contrib import admin
from .models import PartnerProfile

@admin.register(PartnerProfile)
class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company_name', 'phone_number', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'is_deleted',)
    search_fields = ('user__username', 'company_name', 'phone_number')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    
    actions = ['approve_partners', 'revoke_approval']
    def get_queryset(self, request):
        return self.model.all_objects.all()

    def delete_model(self, request, obj):
        obj.soft_delete(request.user)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.soft_delete(request.user)
            
    actions = ['restore_selected', 'soft_delete_selected']
    
    def restore_selected(self, request, queryset):
        for obj in queryset: obj.restore()
        self.message_user(request, 'Selected items restored.')
    restore_selected.short_description = 'Restore selected'
    
    def soft_delete_selected(self, request, queryset):
        for obj in queryset: obj.soft_delete(request.user)
        self.message_user(request, 'Selected items soft deleted.')
    soft_delete_selected.short_description = 'Soft delete selected'


    @admin.action(description='Approve selected partners')
    def approve_partners(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} partners successfully approved.')

    @admin.action(description='Revoke approval for selected partners')
    def revoke_approval(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'Approval revoked for {updated} partners.')
