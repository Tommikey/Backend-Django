from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User

from .models import School
from .presets import apply_preset


def unique_slug(name):
    base = slugify(name)[:70] or "school"
    slug, n = base, 1
    while School.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


@transaction.atomic
def onboard_school(*, name, system, admin):
    """Create a school, fill it from its system's preset and create its first admin.

    ``admin`` holds the admin user's fields: username, email, password, first_name, last_name.
    """
    school = School.objects.create(name=name, slug=unique_slug(name), system=system)
    apply_preset(school)
    user = User.objects.create_user(**admin, role=User.Role.ADMIN, school=school)
    return school, user
