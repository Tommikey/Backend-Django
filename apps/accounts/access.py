"""Shared access rules for the API viewsets and serializers.

Default policy for viewsets that use these mixins:
- every query is limited to the user's school (``SchoolScopedMixin``); this is the tenant boundary
- which rows each role sees inside the school is decided per viewset (``AudienceScopedMixin``)
- any logged-in member can call read actions; ``write_permissions`` says who may create, update
  and delete, and ``write_object_permissions`` adds per-object checks for update / delete
"""

from django.core.exceptions import FieldDoesNotExist
from django.db.models import ProtectedError
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField

from .permissions import IsTeacherOrAdmin

WRITE_ACTIONS = frozenset({"update", "partial_update", "destroy"})


class RolePermissionsMixin:
    # extra actions with their own rules, e.g. {"complete": (IsStudent,)}
    action_permissions: dict = {}
    # who may create / update / delete
    write_permissions: tuple = (IsTeacherOrAdmin,)
    # extra object-level checks for update / delete, e.g. (TeachesSubjectOrAdmin,)
    write_object_permissions: tuple = ()

    def get_permissions(self):
        if self.action in self.action_permissions:
            classes = self.action_permissions[self.action]
        elif self.action == "create":
            classes = self.write_permissions
        elif self.action in WRITE_ACTIONS:
            classes = (*self.write_permissions, *self.write_object_permissions)
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
    # user field stamped with the creator on create
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


class InUse(APIException):
    status_code = 409
    default_detail = "This is still in use; remove what depends on it first."
    default_code = "in_use"


class SafeDestroyMixin:
    """Deleting something other rows still need (PROTECT) is a 409, not a server error."""

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise InUse() from exc


class AudienceScopedMixin:
    """Which rows each role sees inside its school.

    Admins see everything. Each other role is handled by ``scope_<role>(qs, user)``; the
    defaults let teachers see everything and students and parents nothing, so a viewset
    must opt them in explicitly.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "admin":
            return qs
        scope = getattr(self, f"scope_{user.role}", None)
        return scope(qs, user) if scope else qs.none()

    def scope_teacher(self, qs, user):
        return qs

    def scope_student(self, qs, user):
        return qs.none()

    def scope_parent(self, qs, user):
        return qs.none()


def _school_path(model):
    """Lookup from ``model`` to its school: a ``school_path`` attribute, else a direct field."""
    if hasattr(model, "school_path"):
        return model.school_path
    try:
        model._meta.get_field("school")
    except FieldDoesNotExist:
        return None
    return "school"


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
            if not isinstance(rel, PrimaryKeyRelatedField) or rel.queryset is None:
                continue
            path = _school_path(rel.queryset.model)
            if path:
                rel.queryset = rel.queryset.filter(**{f"{path}_id": school_id})

    def unique_in_school(self, field, value):
        """Validator helper: ``value`` must be unused for ``field`` within the user's school.

        Names (subjects, levels, sessions) are unique per school, not globally; DRF can't
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
