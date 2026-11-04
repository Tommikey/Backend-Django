"""The results maths: totals, grades per system, missing scores, tie ranking, GPA."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.academics.models import Subject
from apps.results.models import Score
from apps.results.services import competition_rank, compute_class_results
from conftest import assign, enroll, make_classroom, make_school

pytestmark = pytest.mark.django_db


def build(school, make_user, n_students=4, subjects=("Mathematics", "English")):
    """One class in `school` with `n_students` enrolled and `subjects` taught."""
    classroom = make_classroom(school, "A")
    teacher = make_user("teacher", school=school)
    students = []
    for i in range(n_students):
        student = make_user("student", school=school)
        student.last_name = f"S{i}"  # class lists are ordered by name
        student.save()
        enroll(student, classroom)
        students.append(student)
    subject_objs = {}
    for name in subjects:
        subject_objs[name] = Subject.objects.create(school=school, name=name)
        assign(teacher, classroom, subject_objs[name])
    term = school.academic_sessions.get(is_current=True).terms.get(is_current=True)
    components = {c.name: c for c in school.components.all()}
    return SimpleNamespace(
        school=school,
        classroom=classroom,
        students=students,
        subjects=subject_objs,
        term=term,
        components=components,
    )


def give(ctx, student, subject, **marks):
    for component, value in marks.items():
        Score.objects.create(
            student=student,
            subject=ctx.subjects[subject],
            term=ctx.term,
            component=ctx.components[component],
            value=Decimal(str(value)),
        )


def rows_by_student(ctx):
    computed = compute_class_results(ctx.classroom, ctx.term)
    return {row["student"].pk: row for row in computed["students"]}, computed


def test_competition_rank_shares_places_on_ties():
    assert competition_rank({"a": 90, "b": 80, "c": 80, "d": 70}) == {
        "a": 1,
        "b": 2,
        "c": 2,
        "d": 4,
    }
    assert competition_rank({}) == {}


def test_nigerian_totals_grades_and_positions(school, make_user):
    ctx = build(school, make_user)
    s0, s1, s2, s3 = ctx.students
    give(ctx, s0, "Mathematics", CA1=18, CA2=17, Exam=50)  # 85 -> A1
    give(ctx, s1, "Mathematics", CA1=15, CA2=15, Exam=44.5)  # 74.5 -> B2 (A1 starts at 75)
    give(ctx, s2, "Mathematics", CA1=10, Exam=29)  # missing CA2 counts 0 -> 39 -> F9
    give(ctx, s3, "Mathematics", CA1=15, CA2=15, Exam=44.5)  # 74.5, ties with s1
    rows, computed = rows_by_student(ctx)

    maths = {pk: row["subjects"][0] for pk, row in rows.items()}
    assert (maths[s0.pk]["total"], maths[s0.pk]["grade"]) == (Decimal("85.00"), "A1")
    assert (maths[s1.pk]["total"], maths[s1.pk]["grade"]) == (Decimal("74.50"), "B2")
    assert (maths[s2.pk]["total"], maths[s2.pk]["grade"], maths[s2.pk]["remark"]) == (
        Decimal("39.00"),
        "F9",
        "Fail",
    )
    # missing component is shown as missing, not as 0
    ca2 = next(s for s in maths[s2.pk]["scores"] if s["component"] == "CA2")
    assert ca2 == {"component": "CA2", "max_score": 20, "value": None}
    # subject statistics and positions with a tie: 1, 2, 2, 4
    assert maths[s0.pk]["class_average"] == Decimal("68.25")  # (85+74.5+39+74.5)/4
    assert (maths[s0.pk]["class_highest"], maths[s0.pk]["class_lowest"]) == (
        Decimal("85.00"),
        Decimal("39.00"),
    )
    assert [maths[s.pk]["position"] for s in ctx.students] == [1, 2, 4, 2]
    assert [rows[s.pk]["summary"]["position"] for s in ctx.students] == [1, 2, 4, 2]
    assert rows[s0.pk]["summary"]["out_of"] == 4
    assert rows[s0.pk]["summary"]["gpa"] is None  # NG doesn't use GPA


def test_average_is_over_subjects_taken_only(school, make_user):
    ctx = build(school, make_user, n_students=2)
    s0, s1 = ctx.students
    give(ctx, s0, "Mathematics", CA1=20, CA2=20, Exam=60)  # 100
    give(ctx, s0, "English", CA1=10, CA2=10, Exam=30)  # 50
    give(ctx, s1, "Mathematics", CA1=15, CA2=15, Exam=40)  # 70, no English scores at all
    rows, _ = rows_by_student(ctx)
    assert rows[s0.pk]["summary"]["total"] == Decimal("150.00")
    assert rows[s0.pk]["summary"]["average"] == Decimal("75.00")
    assert rows[s0.pk]["summary"]["subjects_count"] == 2
    assert [line["subject"].name for line in rows[s1.pk]["subjects"]] == ["Mathematics"]
    assert rows[s1.pk]["summary"]["average"] == Decimal("70.00")
    assert rows[s0.pk]["summary"]["position"] == 1 and rows[s1.pk]["summary"]["position"] == 2


def test_student_without_any_scores_is_not_ranked(school, make_user):
    ctx = build(school, make_user, n_students=2)
    s0, s1 = ctx.students
    give(ctx, s0, "Mathematics", Exam=50)
    rows, _ = rows_by_student(ctx)
    assert rows[s1.pk]["subjects"] == []
    assert rows[s1.pk]["summary"]["average"] is None
    assert rows[s1.pk]["summary"]["position"] is None
    assert rows[s0.pk]["summary"]["out_of"] == 1


def test_averages_round_half_up(school, make_user):
    ctx = build(school, make_user, n_students=1, subjects=("Mathematics", "English", "Science"))
    [s0] = ctx.students
    give(ctx, s0, "Mathematics", Exam=60, CA1=10)  # 70
    give(ctx, s0, "English", Exam=60, CA1=10)  # 70
    give(ctx, s0, "Science", Exam=60, CA1=11)  # 71 -> 211 / 3 = 70.333...
    rows, _ = rows_by_student(ctx)
    assert rows[s0.pk]["summary"]["average"] == Decimal("70.33")


def test_british_school_grades_without_positions(make_user, db):
    uk = make_school("UK School", "uk")
    ctx = build(uk, make_user, n_students=2)
    s0, s1 = ctx.students
    give(ctx, s0, "Mathematics", Coursework=36, Exam=55)  # 91 -> A*
    give(ctx, s1, "Mathematics", Coursework=20, Exam=19)  # 39 -> U
    rows, _ = rows_by_student(ctx)
    assert rows[s0.pk]["subjects"][0]["grade"] == "A*"
    assert rows[s1.pk]["subjects"][0]["grade"] == "U"
    assert rows[s0.pk]["subjects"][0]["position"] is None
    assert rows[s0.pk]["summary"]["position"] is None
    assert rows[s0.pk]["summary"]["gpa"] is None


def test_us_school_gets_gpa(make_user, db):
    us = make_school("US School", "us")
    ctx = build(us, make_user, n_students=1)
    [s0] = ctx.students
    give(ctx, s0, "Mathematics", Homework=20, Classwork=20, Tests=25, **{"Final Exam": 27})  # 92 A
    give(ctx, s0, "English", Homework=15, Classwork=15, Tests=25, **{"Final Exam": 20})  # 75 C
    rows, _ = rows_by_student(ctx)
    grades = [(line["subject"].name, line["grade"]) for line in rows[s0.pk]["subjects"]]
    assert grades == [("English", "C"), ("Mathematics", "A")]
    assert rows[s0.pk]["summary"]["gpa"] == Decimal("3.00")  # (4.0 + 2.0) / 2
    assert rows[s0.pk]["summary"]["position"] is None


def test_only_this_terms_scores_count(school, make_user):
    ctx = build(school, make_user, n_students=1)
    [s0] = ctx.students
    give(ctx, s0, "Mathematics", Exam=50)
    second = ctx.term.session.terms.get(order=2)
    Score.objects.create(
        student=s0,
        subject=ctx.subjects["Mathematics"],
        term=second,
        component=ctx.components["CA1"],
        value=20,
    )
    rows, _ = rows_by_student(ctx)
    assert rows[s0.pk]["subjects"][0]["total"] == Decimal("50.00")
