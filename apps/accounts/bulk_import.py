"""Importing a school's people from a CSV: students (into their class), teachers and parents
(linked to their children). Everyone gets an activation code instead of a password.

Columns (header names are case-insensitive; "First Name" works too):

    role          student | teacher | parent                          required
    first_name                                                         required
    last_name                                                          required
    admission_number  students: the school's number, e.g. DSS/2025/014  optional
                  (headers "Admission No", "Adm No", "Reg No" work too)
    username      blank: made from the name (ada.obi, ada.obi2, ...)
    email         optional
    classroom     students: their class this session, e.g. JSS1A    optional
    children      parents: each child's admission number or username, or #<row> for a
                  student row in this file, separated by ; (e.g. "DSS/2025/014; #7")
    relationship  parents: e.g. Mother                                 optional

Validation runs over the whole file first and reports every problem by spreadsheet row
number; nothing is written unless the whole file is valid. Queries don't grow with the number
of rows.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from django.contrib.auth.hashers import make_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Upper
from rest_framework.exceptions import ValidationError

from .access import InUse
from .activation import issue_codes
from .models import Guardianship, User

COLUMNS = [
    "role",
    "first_name",
    "last_name",
    "admission_number",
    "username",
    "email",
    "classroom",
    "children",
    "relationship",
]
REQUIRED_COLUMNS = {"role", "first_name", "last_name"}
# other names schools give a column, after lower-casing and _ for spaces
ALIASES = {
    "admission_no": "admission_number",
    "admission": "admission_number",
    "adm_no": "admission_number",
    "reg_no": "admission_number",
    "registration_number": "admission_number",
    "firstname": "first_name",
    "surname": "last_name",
    "lastname": "last_name",
    "class": "classroom",
}
ROLES = {User.Role.STUDENT, User.Role.TEACHER, User.Role.PARENT}
MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024

TEMPLATE = (
    ",".join(COLUMNS)
    + "\n"
    + "student,Ada,Obi,DSS/2025/001,,,JSS1A,,\n"
    + "student,Tunde,Bello,DSS/2025/002,tunde.b,,JSS1A,,\n"
    + "parent,Ngozi,Obi,,,ngozi@example.com,,DSS/2025/001;#3,Mother\n"
    + "teacher,Musa,Ibrahim,,,musa@example.com,,,\n"
)


@dataclass
class Row:
    number: int  # the spreadsheet row (the header is row 1)
    role: str
    first_name: str
    last_name: str
    admission_number: str
    username: str
    email: str
    classroom_name: str
    children_refs: list
    relationship: str
    errors: list = field(default_factory=list)
    classroom: object = None
    children: list = field(default_factory=list)  # Row (in this file) or User (existing)
    user: object = None

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}".strip()


def _header(name):
    key = re.sub(r"[\s\-.]+", "_", (name or "").strip().lower()).strip("_")
    return ALIASES.get(key, key)


def parse(upload):
    """The uploaded file -> (rows, ignored column names). File-level problems are a 400."""
    if upload.size > MAX_BYTES:
        raise ValidationError({"file": f"The file can be at most {MAX_BYTES // 1024 // 1024} MB."})
    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")  # Excel adds a byte-order mark
    except UnicodeDecodeError as exc:
        raise ValidationError({"file": "Save the file as CSV UTF-8 and try again."}) from exc
    reader = csv.reader(io.StringIO(text))
    try:
        header = [_header(h) for h in next(reader)]
    except StopIteration as exc:
        raise ValidationError({"file": "The file is empty."}) from exc
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise ValidationError(
            {"file": f"Missing column(s): {', '.join(sorted(missing))}. Download the template."}
        )
    ignored = [h for h in header if h and h not in COLUMNS]

    rows = []
    for number, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue  # blank line
        cells = {h: (values[i].strip() if i < len(values) else "") for i, h in enumerate(header)}
        rows.append(
            Row(
                number=number,
                role=cells.get("role", "").lower(),
                first_name=cells.get("first_name", ""),
                last_name=cells.get("last_name", ""),
                admission_number=cells.get("admission_number", ""),
                username=cells.get("username", ""),
                email=cells.get("email", ""),
                classroom_name=cells.get("classroom", ""),
                children_refs=[r.strip() for r in re.split(r"[;,]", cells.get("children", ""))],
                relationship=cells.get("relationship", ""),
            )
        )
        rows[-1].children_refs = [r for r in rows[-1].children_refs if r]
        if len(rows) > MAX_ROWS:
            raise ValidationError({"file": f"Import at most {MAX_ROWS} people at a time."})
    if not rows:
        raise ValidationError({"file": "The file has a header but no people."})
    return rows, ignored


# --- validation ----------------------------------------------------------------------------


def _check_fields(row):
    if row.role not in ROLES:
        row.errors.append("role must be student, teacher or parent.")
    for label, value in (("first_name", row.first_name), ("last_name", row.last_name)):
        if not value:
            row.errors.append(f"{label} is required.")
        elif len(value) > 150:
            row.errors.append(f"{label} is too long.")
    if row.email:
        try:
            validate_email(row.email)
        except DjangoValidationError:
            row.errors.append(f"{row.email!r} isn't a valid email address.")
    if row.username:
        try:
            UnicodeUsernameValidator()(row.username)
        except DjangoValidationError:
            row.errors.append("username may only contain letters, digits and @ . + - _")
        if len(row.username) > 150:
            row.errors.append("username is too long.")
    if row.admission_number and row.role != User.Role.STUDENT:
        row.errors.append("Only students have an admission number.")
    if len(row.admission_number) > 30:
        row.errors.append("admission_number is too long.")
    if row.classroom_name and row.role != User.Role.STUDENT:
        row.errors.append("Only students have a classroom.")
    if (row.children_refs or row.relationship) and row.role != User.Role.PARENT:
        row.errors.append("Only parents have children / a relationship.")
    if len(row.relationship) > 30:
        row.errors.append("relationship is too long.")


def _username_base(row):
    base = re.sub(r"[^a-z0-9]+", "", row.first_name.lower())
    last = re.sub(r"[^a-z0-9]+", "", row.last_name.lower())
    if last:
        base = f"{base}.{last}" if base else last
    return (base or "user")[:140]


def _assign_usernames(rows):
    given = [r for r in rows if r.username]
    lowered = {}
    for row in given:
        key = row.username.lower()
        if key in lowered:
            row.errors.append(f"username {row.username!r} is also on row {lowered[key].number}.")
        else:
            lowered[key] = row
    taken = set(
        User.objects.annotate(u=Lower("username"))
        .filter(u__in=list(lowered))
        .values_list("u", flat=True)
    )
    for key in taken:
        lowered[key].errors.append(f"username {lowered[key].username!r} is taken.")

    # generated names avoid every existing username that starts with the same base
    pending = [r for r in rows if not r.username]
    bases = {_username_base(r) for r in pending}
    in_use = set(lowered)
    base_list = sorted(bases)
    for i in range(0, len(base_list), 200):
        match = Q()
        for base in base_list[i : i + 200]:
            match |= Q(username__istartswith=base)
        in_use |= {u.lower() for u in User.objects.filter(match).values_list("username", flat=True)}
    for row in pending:
        base = _username_base(row)
        candidate, n = base, 1
        while candidate in in_use:
            n += 1
            candidate = f"{base}{n}"
        in_use.add(candidate)
        row.username = candidate


def _resolve_classrooms(rows, school, session):
    classes = {
        c.name.upper().replace(" ", ""): c for c in school.classrooms.select_related("level")
    }
    for row in rows:
        if not row.classroom_name:
            continue
        if session is None:
            row.errors.append("Your school has no current session to enroll students in.")
            continue
        row.classroom = classes.get(row.classroom_name.upper().replace(" ", ""))
        if row.classroom is None:
            row.errors.append(f"No class called {row.classroom_name!r}.")


def _check_admission_numbers(rows, school):
    """Unique in the file and in the school, ignoring case."""
    seen = {}
    for row in rows:
        key = row.admission_number.upper()
        if not key:
            continue
        if key in seen:
            row.errors.append(
                f"admission number {row.admission_number!r} is also on row {seen[key].number}."
            )
        else:
            seen[key] = row
    taken = (
        User.objects.filter(school=school)
        .annotate(a=Upper("admission_number"))
        .filter(a__in=list(seen))
        .values_list("a", flat=True)
    )
    for key in taken:
        seen[key].errors.append(
            f"admission number {seen[key].admission_number!r} already belongs to a student."
        )


def _resolve_children(rows, school):
    """A child reference is #<row>, or an admission number or username of a student in this
    file or already in the school. A reference that fits two different students is an error,
    never a guess."""
    by_number = {r.number: r for r in rows}
    students = [r for r in rows if r.role == User.Role.STUDENT]
    file_by_username = {r.username.lower(): r for r in students}
    file_by_admission = {r.admission_number.upper(): r for r in students if r.admission_number}
    refs = {ref for r in rows for ref in r.children_refs if not ref.startswith("#")}
    existing = list(
        User.objects.filter(school=school, role=User.Role.STUDENT)
        .annotate(u=Lower("username"), a=Upper("admission_number"))
        .filter(Q(u__in=[x.lower() for x in refs]) | Q(a__in=[x.upper() for x in refs]))
    )
    school_by_username = {u.username.lower(): u for u in existing}
    school_by_admission = {u.admission_number.upper(): u for u in existing if u.admission_number}

    def lookup(ref):
        found = [
            file_by_admission.get(ref.upper()),
            school_by_admission.get(ref.upper()),
            file_by_username.get(ref.lower()),
            school_by_username.get(ref.lower()),
        ]
        distinct = {id(t): t for t in found if t is not None}
        return list(distinct.values())

    for row in rows:
        seen = set()
        for ref in row.children_refs:
            if ref.startswith("#"):
                target = by_number.get(int(ref[1:])) if ref[1:].isdigit() else None
                if target is None or target.role != User.Role.STUDENT:
                    row.errors.append(f"{ref} isn't a student row in this file.")
                    continue
            else:
                matches = lookup(ref)
                if not matches:
                    row.errors.append(f"No student {ref!r} in this file or your school.")
                    continue
                if len(matches) > 1:
                    row.errors.append(
                        f"{ref!r} is one student's admission number and another's username; "
                        "use #<row> or the other identifier."
                    )
                    continue
                target = matches[0]
            if id(target) not in seen:
                seen.add(id(target))
                row.children.append(target)


def validate(rows, school, session):
    for row in rows:
        _check_fields(row)
    _assign_usernames(rows)
    _check_admission_numbers(rows, school)
    _resolve_classrooms(rows, school, session)
    _resolve_children(rows, school)
    for row in rows:  # a parent linked to a broken student row can't be imported either
        for child in row.children:
            if isinstance(child, Row) and child.errors:
                row.errors.append(f"Linked student on row {child.number} has errors.")
    return not any(row.errors for row in rows)


# --- writing -----------------------------------------------------------------------------


@transaction.atomic
def commit(rows, school, session, admin):
    """Create everyone, enrollments and parent links; returns {user_id: (code, expires_at)}."""
    from apps.academics.models import Enrollment

    unusable = make_password(None)  # no password until they activate
    users = [
        User(
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            admission_number=row.admission_number,
            email=row.email,
            role=row.role,
            school=school,
            password=unusable,
        )
        for row in rows
    ]
    try:
        with transaction.atomic():
            User.objects.bulk_create(users)
    except IntegrityError as exc:
        raise InUse(
            "Someone took one of these usernames while you were importing; run it again."
        ) from exc
    for row, user in zip(rows, users, strict=True):
        row.user = user

    Enrollment.objects.bulk_create(
        Enrollment(session=session, classroom=row.classroom, student=row.user)
        for row in rows
        if row.classroom is not None
    )
    Guardianship.objects.bulk_create(
        Guardianship(
            parent=row.user,
            student=child.user if isinstance(child, Row) else child,
            relationship=row.relationship,
        )
        for row in rows
        for child in row.children
    )
    return issue_codes(users, admin)


def report(rows, ignored, committed, codes=None):
    codes = codes or {}
    counts = {role: sum(1 for r in rows if r.role == role) for role in ROLES}
    people = []
    for row in rows:
        user_id = row.user.pk if row.user else None
        code, expires_at = codes.get(user_id, (None, None))
        people.append(
            {
                "row": row.number,
                "id": user_id,
                "role": row.role,
                "username": row.username,
                "admission_number": row.admission_number,
                "name": row.name,
                "classroom": row.classroom.name if row.classroom else None,
                "children": [child.username for child in row.children],
                "activation_code": code,
                "expires_at": expires_at,
            }
        )
    return {
        "committed": committed,
        "valid": not any(r.errors for r in rows),
        "summary": {
            "rows": len(rows),
            "students": counts[User.Role.STUDENT],
            "teachers": counts[User.Role.TEACHER],
            "parents": counts[User.Role.PARENT],
            "enrollments": sum(1 for r in rows if r.classroom is not None),
            "parent_links": sum(len(r.children) for r in rows),
        },
        "ignored_columns": ignored,
        "errors": [{"row": r.number, "messages": r.errors} for r in rows if r.errors],
        "people": people,
    }
