from django.contrib import admin

from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ["student", "classroom", "date", "status", "term", "marked_by"]
    list_filter = ["status", "term", "classroom"]
    search_fields = ["student__username"]
    date_hierarchy = "date"
