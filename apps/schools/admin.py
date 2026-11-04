from django.contrib import admin

from .models import AssessmentComponent, GradeBand, Level, School


class LevelInline(admin.TabularInline):
    model = Level
    extra = 0


class AssessmentComponentInline(admin.TabularInline):
    model = AssessmentComponent
    extra = 0


class GradeBandInline(admin.TabularInline):
    model = GradeBand
    extra = 0


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "system", "is_active", "created_at"]
    list_filter = ["system", "is_active"]
    search_fields = ["name", "slug"]
    inlines = [LevelInline, AssessmentComponentInline, GradeBandInline]
