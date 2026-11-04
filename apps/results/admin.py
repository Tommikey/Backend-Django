from django.contrib import admin

from .models import Publication, Score, SubjectResult, TermResult


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ["student", "subject", "term", "component", "value", "updated_at"]
    list_filter = ["term", "subject"]
    search_fields = ["student__username"]


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ["term", "published_at", "published_by"]


class SubjectResultInline(admin.TabularInline):
    model = SubjectResult
    extra = 0


@admin.register(TermResult)
class TermResultAdmin(admin.ModelAdmin):
    list_display = ["student", "term", "classroom", "average", "position", "gpa"]
    list_filter = ["term", "classroom"]
    search_fields = ["student__username"]
    inlines = [SubjectResultInline]
