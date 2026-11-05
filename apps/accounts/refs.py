"""How a student is referred to in responses: everywhere a student appears, with their
school's admission number alongside the name (blank if the school doesn't use them)."""


def student_ref(student):
    return {
        "id": student.pk,
        "name": student.display_name,
        "admission_number": student.admission_number,
    }
