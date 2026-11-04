from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ActivationCode, Guardianship, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ["username", "email", "role", "school", "is_active"]
    list_filter = UserAdmin.list_filter + ("role", "school")
    fieldsets = UserAdmin.fieldsets + (("School", {"fields": ("school", "role")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("School", {"fields": ("school", "role")}),)


@admin.register(Guardianship)
class GuardianshipAdmin(admin.ModelAdmin):
    list_display = ["parent", "student", "relationship", "created_at"]
    search_fields = ["parent__username", "student__username"]


@admin.register(ActivationCode)
class ActivationCodeAdmin(admin.ModelAdmin):
    list_display = ["user", "expires_at", "created_by", "created_at"]
    search_fields = ["user__username"]
    readonly_fields = ["code_hash"]
