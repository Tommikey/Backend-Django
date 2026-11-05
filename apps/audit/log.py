"""Writing the audit log.

``record(...)`` adds one entry. ``AuditedMixin`` does it for a viewset's creates, updates and
deletes, with a field-by-field before -> after of ``audit_fields``.
"""

import datetime
from decimal import Decimal

from django.db import models
from rest_framework.throttling import BaseThrottle

from .models import AuditEntry


def jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, models.Model):
        return value.pk
    return value


def client_ip(request):
    # the same address rate limits use: honours NUM_PROXIES, can't be spoofed beyond it
    ident = BaseThrottle().get_ident(request)
    return ident or None


def record(
    action,
    *,
    school,
    request=None,
    actor=None,
    target=None,
    target_type="",
    target_id=None,
    label="",
    changes=None,
    context=None,
):
    if request is not None and actor is None and request.user.is_authenticated:
        actor = request.user
    return AuditEntry.objects.create(
        school=school,
        actor=actor,
        actor_name=f"{actor.display_name} ({actor.username})" if actor else "",
        action=action,
        target_type=target._meta.model_name if target is not None else target_type,
        target_id=target.pk if target is not None else target_id,
        target_label=(label or (str(target) if target is not None else ""))[:300],
        changes=changes if changes is not None else {},
        context=context or {},
        ip=client_ip(request) if request is not None else None,
    )


def ref(obj):
    """{"id", "name"} of a related object, for context."""
    if obj is None:
        return None
    name = getattr(obj, "display_name", None) or getattr(obj, "name", None) or str(obj)
    return {"id": obj.pk, "name": name}


def snapshot(instance, fields):
    values = {}
    for name in fields:
        field = instance._meta.get_field(name)
        values[name] = jsonable(getattr(instance, field.attname))
    return values


def diff(before, after):
    return {k: [before[k], after[k]] for k in after if before.get(k) != after[k]}


class AuditedMixin:
    """Records creates, updates and deletes. Put it first among the viewset's bases; a viewset
    that overrides perform_* calls super() (update: ``super().perform_update(serializer,
    **save_kwargs)``)."""

    audit_fields: tuple = ()

    def audit_name(self, instance):
        return instance._meta.model_name

    def audit_label(self, instance):
        return str(instance)

    def audit_context(self, instance):
        """Where it happened, e.g. {"student": ref(...), "classroom": ref(...)}."""
        return {}

    def audit_extra_changes(self, serializer):
        """Changes that aren't model fields (e.g. a password reset)."""
        return {}

    def _school(self):
        return self.request.user.school

    def perform_create(self, serializer):
        super().perform_create(serializer)
        instance = serializer.instance
        values = snapshot(instance, self.audit_fields)
        record(
            f"{self.audit_name(instance)}.created",
            school=self._school(),
            request=self.request,
            target=instance,
            label=self.audit_label(instance),
            changes={k: [None, v] for k, v in values.items() if v not in (None, "")},
            context=self.audit_context(instance),
        )

    def perform_update(self, serializer, **save_kwargs):
        before = snapshot(serializer.instance, self.audit_fields)
        serializer.save(**save_kwargs)
        instance = serializer.instance
        changes = diff(before, snapshot(instance, self.audit_fields))
        changes.update(self.audit_extra_changes(serializer))
        if changes:
            record(
                f"{self.audit_name(instance)}.updated",
                school=self._school(),
                request=self.request,
                target=instance,
                label=self.audit_label(instance),
                changes=changes,
                context=self.audit_context(instance),
            )

    def perform_destroy(self, instance):
        values = snapshot(instance, self.audit_fields)
        name, label, pk = self.audit_name(instance), self.audit_label(instance), instance.pk
        context = self.audit_context(instance)
        super().perform_destroy(instance)
        record(
            f"{name}.deleted",
            school=self._school(),
            request=self.request,
            target_type=instance._meta.model_name,
            target_id=pk,
            label=label,
            changes={k: [v, None] for k, v in values.items() if v not in (None, "")},
            context=context,
        )
