from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Read-only: the log is only ever added to."""

    list_display = ["created_at", "school", "actor_name", "action", "target_label", "ip"]
    list_filter = ["action"]
    search_fields = ["actor_name", "target_label", "action"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
