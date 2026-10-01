from django.contrib import admin
from .models import Order

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'partner', 'amount', 'commission_amount', 'is_commission_paid', 'status', 'created_at')
    list_filter = ('status', 'is_commission_paid', 'partner', 'is_deleted')
    search_fields = ('order_number', 'partner__company_name')
    list_editable = ('is_commission_paid', 'status')
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
