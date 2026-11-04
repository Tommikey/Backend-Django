from django.contrib import admin

from .models import LiveClass


@admin.register(LiveClass)
class LiveClassAdmin(admin.ModelAdmin):
    list_display = ["title", "classroom", "subject", "hosted_by", "starts_at", "ends_at"]
    list_filter = ["classroom"]
    search_fields = ["title"]
