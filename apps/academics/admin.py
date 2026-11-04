from django.contrib import admin

from .models import (
    AcademicSession,
    Classroom,
    Completion,
    Enrollment,
    Lesson,
    Subject,
    TeachingAssignment,
    Term,
)


class TermInline(admin.TabularInline):
    model = Term
    extra = 0


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ["name", "school", "starts_on", "ends_on", "is_current"]
    list_filter = ["school", "is_current"]
    inlines = [TermInline]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name", "school"]
    list_filter = ["school"]


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ["name", "school", "form_teacher"]
    list_filter = ["school", "level"]


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = ["teacher", "subject", "classroom", "session"]
    list_filter = ["session", "subject"]
    search_fields = ["teacher__username"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "classroom", "session", "created_at"]
    list_filter = ["session", "classroom"]
    search_fields = ["student__username"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["title", "classroom", "subject", "term", "created_by", "created_at"]
    list_filter = ["subject", "term"]
    search_fields = ["title"]


@admin.register(Completion)
class CompletionAdmin(admin.ModelAdmin):
    list_display = ["lesson", "student", "completed_at"]
    search_fields = ["student__username"]
