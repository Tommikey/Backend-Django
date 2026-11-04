"""Shared access rules for the API viewsets and serializers.

Default policy for viewsets that use these mixins:
- every query is limited to the user's school (``SchoolScopedMixin``); this is the tenant boundary
- any logged-in member of the school can read (list / retrieve)
- teachers and admins can create, update and delete (``write_permissions`` to change that);
  with ``owner_scoped`` only the owner or an admin can update / delete
- students only see rows reachable through their own enrollments (``student_scope``)
"""

from django.core.exceptions import FieldDoesNotExist
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField

from .permissions import IsOwnerOrAdmin, IsTeacherOrAdmin

WRITE_ACTIONS = frozenset({"update", "partial_update", "destroy"})


class RolePermissionsMixin:
    # extra actions with their own rules, e.g. {"complete": (IsStudent,)}
    action_permissions: dict = {}
    # who may create / update / delete
    write_permissions: tuple = (IsTeacherOrAdmin,)
    # restrict update/delete to the object's owner (see IsOwnerOrAdmin / owner_field)
    owner_scoped = False

    def get_permissions(self):
        if self.action in self.action_permissions:
            classes = self.action_permissions[self.action]
        elif self.action == "create":
            classes = self.write_permissions
        elif self.action in WRITE_ACTIONS and self.owner_scoped:
            classes = (*self.write_permissions, IsOwnerOrAdmin)
        elif self.action in WRITE_ACTIONS:
            classes = self.write_permissions
        else:
            classes = (IsAuthenticated,)
        return [cls() for cls in classes]


class SaveKwargsMixin:
    """Collects extra fields to set on create from every mixin that contributes some."""

    def get_save_kwargs(self):
        return {}

    def perform_create(self, serializer):
        serializer.save(**self.get_save_kwargs())


class OwnedObjectMixin(SaveKwargsMixin):
    # user field stamped on create; also read by IsOwnerOrAdmin
    owner_field = "created_by"

    def get_save_kwargs(self):
        return {**super().get_save_kwargs(), self.owner_field: self.request.user}


class SchoolScopedMixin(SaveKwargsMixin):
    """Tenant boundary: only rows of the requesting user's school exist for them.

    ``school_path`` is the ORM lookup from the model to its school, e.g. ``classroom__school``.
    Models with a direct ``school`` field get it stamped on create.
    """

    school_path = "school"

    def get_queryset(self):
        # platform staff have no school and therefore see no school data through the API
        school_id = getattr(self.request.user, "school_id", None)
        return super().get_queryset().filter(**{f"{self.school_path}_id": school_id})

    def get_save_kwargs(self):
        kwargs = super().get_save_kwargs()
        if self.school_path == "school":
            kwargs["school"] = self.request.user.school
        return kwargs


class StudentScopedQuerysetMixin:
    # ORM lookup from this model to the student, e.g. "classroom__enrollments__student"
    student_scope: str = ""

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "student" and self.student_scope:
            qs = qs.filter(**{self.student_scope: user})
            if "__" in self.student_scope:
                # lookups through a related table can match the same row more than once
                qs = qs.distinct()
        return qs


def _has_school_field(model):
    try:
        model._meta.get_field("school")
    except FieldDoesNotExist:
        return False
    return True


class SameSchoolSerializerMixin:
    """Limits every writable ID field to objects of the requesting user's school.

    An ID from another school then fails exactly like a non-existent ID, so the API never
    confirms that another school's object exists.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return
        school_id = getattr(request.user, "school_id", None)
        for field in self.fields.values():
            rel = field.child_relation if isinstance(field, ManyRelatedField) else field
            if (
                isinstance(rel, PrimaryKeyRelatedField)
                and rel.queryset is not None
                and _has_school_field(rel.queryset.model)
            ):
                rel.queryset = rel.queryset.filter(school_id=school_id)

    def unique_in_school(self, field, value):
        """Validator helper: ``value`` must be unused for ``field`` within the user's school.

        Names (subjects, classes, levels) are unique per school, not globally; DRF can't
        generate that check itself because ``school`` isn't a serializer field.
        """
        model = self.Meta.model
        clash = model.objects.filter(
            school_id=self.context["request"].user.school_id, **{f"{field}__iexact": value}
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(
                f"Your school already has a {model._meta.verbose_name} with this {field}."
            )
        return value
