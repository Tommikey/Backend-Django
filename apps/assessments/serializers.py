from rest_framework import serializers

from apps.academics.serializers import TeachingScopeSerializerMixin, term_field
from apps.academics.validators import UPLOAD_VALIDATORS
from apps.accounts.access import SameSchoolSerializerMixin

from .models import Answer, Assessment, Choice, Question, Submission


class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ["id", "text", "is_correct"]


class ChoiceStudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ["id", "text"]


class QuestionSerializer(serializers.ModelSerializer):
    choices = ChoiceSerializer(many=True)

    class Meta:
        model = Question
        fields = ["id", "text", "points", "choices"]


class QuestionStudentSerializer(serializers.ModelSerializer):
    choices = ChoiceStudentSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = ["id", "text", "points", "choices"]


class AssessmentSerializer(
    TeachingScopeSerializerMixin, SameSchoolSerializerMixin, serializers.ModelSerializer
):
    questions = QuestionSerializer(many=True, required=False)
    term = term_field()
    term_name = serializers.CharField(source="term.name", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.display_name", read_only=True, default=None
    )

    class Meta:
        model = Assessment
        fields = [
            "id",
            "title",
            "description",
            "type",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "term",
            "term_name",
            "created_by",
            "created_by_name",
            "due_at",
            "max_points",
            "created_at",
            "questions",
        ]
        read_only_fields = ["created_by", "created_at"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            # a quiz's questions and grading depend on its type
            if "type" in attrs and attrs["type"] != self.instance.type:
                raise serializers.ValidationError({"type": "The type can't be changed."})
            return attrs  # update() leaves questions alone
        if attrs.get("type") == Assessment.Type.QUIZ:
            questions = attrs.get("questions")
            if not questions:
                raise serializers.ValidationError("A quiz needs at least one question.")
            errors = []
            for i, question in enumerate(questions, 1):
                choices = question.get("choices", [])
                if len(choices) < 2:
                    errors.append(f"Question {i}: give at least two choices.")
                elif sum(1 for c in choices if c.get("is_correct")) != 1:
                    errors.append(f"Question {i}: mark exactly one choice correct.")
            if errors:
                raise serializers.ValidationError({"questions": errors})
        return attrs

    # shortcut: questions are writable on create only; update patches basic fields
    def update(self, instance, validated_data):
        validated_data.pop("questions", None)
        return super().update(instance, validated_data)

    def create(self, validated_data):
        questions_data = validated_data.pop("questions", [])
        assessment = Assessment.objects.create(**validated_data)
        for question_data in questions_data:
            choices_data = question_data.pop("choices", [])
            question = Question.objects.create(
                assessment=assessment,
                text=question_data["text"],
                points=question_data.get("points", 1),
            )
            Choice.objects.bulk_create(
                [Choice(question=question, **choice) for choice in choices_data]
            )
        if assessment.type == Assessment.Type.QUIZ:
            # quizzes always derive max_points from questions, ignoring client input
            assessment.max_points = sum(q.get("points", 1) for q in questions_data)
            assessment.save(update_fields=["max_points"])
        return assessment


class AssessmentStudentSerializer(AssessmentSerializer):
    questions = QuestionStudentSerializer(many=True, read_only=True)


class AnswerInputSerializer(serializers.Serializer):
    question = serializers.PrimaryKeyRelatedField(queryset=Question.objects.all())
    choice = serializers.PrimaryKeyRelatedField(queryset=Choice.objects.all())


class SubmitSerializer(serializers.Serializer):
    answers = AnswerInputSerializer(many=True, required=False)
    text = serializers.CharField(required=False, allow_blank=True)
    file = serializers.FileField(required=False, validators=UPLOAD_VALIDATORS)

    def validate(self, attrs):
        assessment = self.context["assessment"]
        answers = attrs.get("answers", [])
        if assessment.type == Assessment.Type.QUIZ:
            if not answers:
                raise serializers.ValidationError("Quiz submissions require answers.")
        else:
            if not attrs.get("text") and not attrs.get("file"):
                raise serializers.ValidationError("Assignment submissions require text or a file.")
        seen = set()
        for answer in answers:
            if answer["question"].assessment_id != assessment.pk:
                raise serializers.ValidationError(
                    f"Question {answer['question'].pk} does not belong to this assessment."
                )
            if answer["choice"].question_id != answer["question"].pk:
                raise serializers.ValidationError(
                    f"Choice {answer['choice'].pk} does not belong to "
                    f"question {answer['question'].pk}."
                )
            if answer["question"].pk in seen:
                raise serializers.ValidationError(
                    f"Duplicate answer for question {answer['question'].pk}."
                )
            seen.add(answer["question"].pk)
        return attrs


class AnswerOutputSerializer(serializers.ModelSerializer):
    question_text = serializers.CharField(source="question.text", read_only=True)
    choice_text = serializers.CharField(source="choice.text", read_only=True)
    is_correct = serializers.BooleanField(source="choice.is_correct", read_only=True)

    class Meta:
        model = Answer
        fields = ["question", "question_text", "choice", "choice_text", "is_correct"]


class SubmissionSerializer(serializers.ModelSerializer):
    answers = AnswerOutputSerializer(many=True, read_only=True)
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)
    assessment_type = serializers.CharField(source="assessment.type", read_only=True)
    max_points = serializers.IntegerField(source="assessment.max_points", read_only=True)
    student_name = serializers.CharField(source="student.display_name", read_only=True)
    is_late = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = [
            "id",
            "assessment",
            "assessment_title",
            "assessment_type",
            "max_points",
            "student",
            "student_name",
            "answers",
            "text",
            "file",
            "score",
            "submitted_at",
            "is_late",
            "graded_at",
        ]
        read_only_fields = fields

    def get_is_late(self, submission):
        due = submission.assessment.due_at
        return due is not None and submission.submitted_at > due


class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = ["score"]

    def validate_score(self, value):
        submission = self.instance
        if value is not None and submission and not 0 <= value <= submission.assessment.max_points:
            raise serializers.ValidationError(
                f"Score must be between 0 and {submission.assessment.max_points}."
            )
        return value
