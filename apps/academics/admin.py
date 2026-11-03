from django.contrib import admin

from .models import Classroom, Completion, Enrollment, Lesson, Subject


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name"]


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at"]
    search_fields = ["name"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["classroom", "student", "created_at"]
    list_filter = ["classroom"]
    search_fields = ["student__username"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["title", "classroom", "subject", "created_by", "created_at"]
    list_filter = ["classroom", "subject"]
    search_fields = ["title"]


@admin.register(Completion)
class CompletionAdmin(admin.ModelAdmin):
    list_display = ["lesson", "student", "completed_at"]
    list_filter = ["lesson__classroom"]
