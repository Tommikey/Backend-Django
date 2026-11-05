from django.urls import path

from .views import (
    ClassReportCardsPdfView,
    ClassResultsView,
    CommentsView,
    PublishView,
    ReportCardPdfView,
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
    path("results/report-card/pdf/", ReportCardPdfView.as_view(), name="report-card-pdf"),
    path(
        "results/report-cards/pdf/",
        ClassReportCardsPdfView.as_view(),
        name="class-report-cards-pdf",
    ),
    path("results/class-results/", ClassResultsView.as_view(), name="class-results"),
]
