from django.urls import path

from .views import (
    ClassResultsView,
    CommentsView,
    PublishView,
    ReportCardView,
    ScoreSheetView,
    UnpublishView,
)

app_name = "results"

urlpatterns = [
    path("results/score-sheet/", ScoreSheetView.as_view(), name="score-sheet"),
    path("results/comments/", CommentsView.as_view(), name="comments"),
    path("results/publish/", PublishView.as_view(), name="publish"),
    path("results/unpublish/", UnpublishView.as_view(), name="unpublish"),
    path("results/report-card/", ReportCardView.as_view(), name="report-card"),
    path("results/class-results/", ClassResultsView.as_view(), name="class-results"),
]
