from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .access import SameSchoolSerializerMixin
from .authentication import end_sessions
from .models import Guardianship, User


class UserSerializer(serializers.ModelSerializer):
    """The logged-in user's own profile."""

    school_name = serializers.CharField(source="school.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "school",
            "school_name",
            "admission_number",
        ]
        read_only_fields = ["username", "role", "school", "admission_number"]


class _Ref(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class _SchoolDetails(_Ref):
    slug = serializers.CharField()
    system = serializers.CharField()
    system_name = serializers.CharField()
    show_position = serializers.BooleanField()
    use_gpa = serializers.BooleanField()
    term_labels = serializers.ListField(child=serializers.CharField())
    timezone = serializers.CharField()


class _TermRef(_Ref):
    session = _Ref()


class _Teaching(serializers.Serializer):
    classroom = _Ref()
    subject = _Ref()


class _Child(_Ref):
    admission_number = serializers.CharField()
    relationship = serializers.CharField()
    classroom = _Ref(allow_null=True, help_text="Their class in the current session")


def _ref(obj):
    return {"id": obj.pk, "name": obj.name}


class MeSerializer(UserSerializer):
    """Your profile plus what a client needs to draw its shell, in one call: the school's
    settings, the current session and term, and what you work with in it (a teacher's classes,
    a student's class, a parent's children). Role-specific lists are empty for other roles.
    """

    school_details = serializers.SerializerMethodField()
    current_session = serializers.SerializerMethodField()
    current_term = serializers.SerializerMethodField()
    form_classes = serializers.SerializerMethodField()
    teaching = serializers.SerializerMethodField()
    classroom = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    unread_notifications = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "school_details",
            "current_session",
            "current_term",
            "form_classes",
            "teaching",
            "classroom",
            "children",
            "unread_notifications",
        ]

    def get_unread_notifications(self, user) -> int:
        return user.notifications.filter(read_at__isnull=True).count()

    def _term(self, user):
        if not hasattr(self, "_cached_term"):
            from apps.academics.rules import current_term

            self._cached_term = current_term(user.school_id) if user.school_id else None
        return self._cached_term

    @extend_schema_field(_SchoolDetails(allow_null=True))
    def get_school_details(self, user):
        school = user.school
        if school is None:
            return None
        return {
            "id": school.pk,
            "name": school.name,
            "slug": school.slug,
            "system": school.system,
            "system_name": school.get_system_display(),
            "show_position": school.show_position,
            "use_gpa": school.use_gpa,
            "term_labels": school.term_labels,
            "timezone": school.timezone,
        }

    @extend_schema_field(_Ref(allow_null=True))
    def get_current_session(self, user):
        term = self._term(user)
        return _ref(term.session) if term else None

    @extend_schema_field(_TermRef(allow_null=True))
    def get_current_term(self, user):
        term = self._term(user)
        return {**_ref(term), "session": _ref(term.session)} if term else None

    @extend_schema_field(_Ref(many=True))
    def get_form_classes(self, user):
        if user.role != User.Role.TEACHER:
            return []
        return [_ref(c) for c in user.form_classes.select_related("level")]

    @extend_schema_field(_Teaching(many=True))
    def get_teaching(self, user):
        term = self._term(user)
        if user.role != User.Role.TEACHER or term is None:
            return []
        assignments = (
            user.teaching_assignments.filter(session_id=term.session_id)
            .select_related("classroom__level", "subject")
            .order_by("classroom__level__order", "classroom__arm", "subject__name")
        )
        return [{"classroom": _ref(a.classroom), "subject": _ref(a.subject)} for a in assignments]

    @extend_schema_field(_Ref(allow_null=True))
    def get_classroom(self, user):
        term = self._term(user)
        if user.role != User.Role.STUDENT or term is None:
            return None
        enrollment = (
            user.enrollments.filter(session_id=term.session_id)
            .select_related("classroom__level")
            .first()
        )
        return _ref(enrollment.classroom) if enrollment else None

    @extend_schema_field(_Child(many=True))
    def get_children(self, user):
        if user.role != User.Role.PARENT:
            return []
        from apps.academics.models import Enrollment

        term = self._term(user)
        links = list(user.children_links.select_related("student").order_by("student__first_name"))
        classes = {}
        if term is not None:
            for e in Enrollment.objects.filter(
                session_id=term.session_id, student__in=[link.student for link in links]
            ).select_related("classroom__level"):
                classes[e.student_id] = _ref(e.classroom)
        return [
            {
                "id": link.student.pk,
                "name": link.student.display_name,
                "admission_number": link.student.admission_number,
                "relationship": link.relationship,
                "classroom": classes.get(link.student_id),
            }
            for link in links
        ]


class SchoolUserSerializer(serializers.ModelSerializer):
    """Users as managed by their school's admin. The school is set by the view, never sent."""

    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )
    has_password = serializers.SerializerMethodField(
        help_text="False until an imported person activates their account"
    )
    activation_expires_at = serializers.SerializerMethodField(
        help_text="When their unused activation code expires; null if none is pending"
    )

    def get_has_password(self, user) -> bool:
        return user.has_usable_password()

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_activation_expires_at(self, user):
        code = getattr(user, "activation_code", None)
        return code.expires_at if code else None

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "admission_number",
            "is_active",
            "password",
            "date_joined",
            "has_password",
            "activation_expires_at",
        ]
        read_only_fields = ["date_joined"]
        # form posts leave out unticked checkboxes; a missing is_active must not deactivate
        extra_kwargs = {"is_active": {"default": True}}

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_username(self, value):
        clash = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This username is taken.")
        return value

    def validate_admission_number(self, value):
        value = value.strip()
        if value:
            clash = User.objects.filter(
                school_id=self.context["request"].user.school_id, admission_number__iexact=value
            )
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError("Another student has this admission number.")
        return value

    def validate(self, attrs):
        user = self.instance
        role = attrs.get("role", user.role if user else None)
        if attrs.get("admission_number") and role != User.Role.STUDENT:
            raise serializers.ValidationError(
                {"admission_number": "Only students have an admission number."}
            )
        if user is None:
            if not attrs.get("password"):
                raise serializers.ValidationError({"password": "Required when creating a user."})
            return attrs
        # a role decides what a user's records mean (a student's marks, a teacher's classes),
        # so it is fixed at creation; make a new account for a different role
        if "role" in attrs and attrs["role"] != user.role:
            raise serializers.ValidationError(
                {"role": "A role can't be changed; create a new account instead."}
            )
        # only active admins edit users, so refusing self-deactivation always leaves one
        if attrs.get("is_active") is False and user == self.context["request"].user:
            raise serializers.ValidationError(
                {"is_active": "You can't deactivate your own account."}
            )
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:  # an admin reset: the person must sign in again everywhere
            user.set_password(password)
            user.save(update_fields=["password"])
            end_sessions(user)
        return user


class ActivateSerializer(serializers.Serializer):
    username = serializers.CharField()
    code = serializers.CharField(help_text="As printed, e.g. K7M2-QX9P (case and dash optional)")
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})


class PasswordResetRequestSerializer(serializers.Serializer):
    login = serializers.CharField(help_text="Your username or email address")


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})


class ActivationCodeIssuedSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    username = serializers.CharField()
    code = serializers.CharField(help_text="Shown once; give it to the person")
    expires_at = serializers.DateTimeField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("That isn't your current password.")
        return value

    def validate(self, attrs):
        validate_password(attrs["new_password"], self.context["request"].user)
        return attrs


class GuardianshipSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.display_name", read_only=True)
    student_name = serializers.CharField(source="student.display_name", read_only=True)
    student_admission_number = serializers.CharField(
        source="student.admission_number", read_only=True
    )

    class Meta:
        model = Guardianship
        fields = [
            "id",
            "parent",
            "parent_name",
            "student",
            "student_name",
            "student_admission_number",
            "relationship",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_parent(self, value):
        if value.role != User.Role.PARENT:
            raise serializers.ValidationError("Must be a parent account.")
        return value

    def validate_student(self, value):
        if value.role != User.Role.STUDENT:
            raise serializers.ValidationError("Must be a student account.")
        return value
