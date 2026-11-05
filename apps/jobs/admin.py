from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["kind", "school", "status", "created_by", "created_at", "finished_at"]
    list_filter = ["kind", "status"]
    readonly_fields = [f.name for f in Job._meta.fields]
