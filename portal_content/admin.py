from django.contrib import admin
from .models import Announcement, Document

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_deleted',)
    search_fields = ('title',)
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


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'uploaded_at')
    search_fields = ('title',)

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
