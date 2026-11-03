from django.contrib import admin

from .models import Assessment, Choice, Question, Submission


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ["title", "type", "classroom", "subject", "due_at", "max_points", "created_by"]
    list_filter = ["type", "classroom", "subject"]
    search_fields = ["title"]
    inlines = [QuestionInline]


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["text", "assessment", "points"]
    search_fields = ["text"]
    inlines = [ChoiceInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["assessment", "student", "score", "submitted_at", "graded_at"]
    list_filter = ["assessment__classroom", "assessment__type"]
    search_fields = ["student__username"]
