from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('subject', 'partner', 'status', 'created_at')
    list_filter = ('status', 'partner', 'is_deleted')
    search_fields = ('subject', 'partner__company_name')
    list_editable = ('status',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)

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
