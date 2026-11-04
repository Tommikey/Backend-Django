"""Login is required everywhere (role and teaching rules are tested per app)."""

import pytest

pytestmark = pytest.mark.django_db

PROTECTED_LIST_URLS = [
    "/api/v1/auth/me/",
    "/api/v1/users/",
    "/api/v1/guardianships/",
    "/api/v1/schools/me/",
    "/api/v1/schools/levels/",
    "/api/v1/schools/components/",
    "/api/v1/schools/grade-bands/",
    "/api/v1/academics/academic-sessions/",
    "/api/v1/academics/terms/",
    "/api/v1/academics/subjects/",
    "/api/v1/academics/classrooms/",
    "/api/v1/academics/teaching-assignments/",
    "/api/v1/academics/enrollments/",
    "/api/v1/academics/lessons/",
    "/api/v1/academics/progress/",
    "/api/v1/assessments/",
    "/api/v1/submissions/",
    "/api/v1/sessions/",
    "/api/v1/stats/",
]


@pytest.mark.parametrize("url", PROTECTED_LIST_URLS)
def test_anonymous_gets_401_not_500(api, url):
    r = api.get(url)
    assert r.status_code == 401, (url, r.status_code)
