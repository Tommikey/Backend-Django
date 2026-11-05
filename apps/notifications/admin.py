from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "recipient", "school", "created_at", "read_at", "emailed_at"]
    list_filter = ["kind"]
    raw_id_fields = ["recipient", "school"]
