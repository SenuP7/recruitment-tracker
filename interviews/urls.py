from django.urls import path

from .views import (
    InterviewListView,
    MyInterviewsListView,
    InterviewDetailView,
    InterviewCreateView,
    InterviewUpdateView,
    InterviewDeleteView,
    InterviewFeedbackDetailView,
    InterviewFeedbackCreateView,
    InterviewFeedbackReplyCreateView,
    InterviewFeedbackUpdateView,
    InterviewFeedbackDeleteView,
    FeedbackThreadView,
    StaffNotificationListView,
)


urlpatterns = [
    path("", InterviewListView.as_view(), name="interview-list"),
    path("mine/", MyInterviewsListView.as_view(), name="my-interviews"),
    path("notifications/", StaffNotificationListView.as_view(), name="staff-notifications"),
    path("<int:pk>/", InterviewDetailView.as_view(), name="interview-detail"),
    path("create/", InterviewCreateView.as_view(), name="interview-create"),
    path("<int:pk>/edit/", InterviewUpdateView.as_view(), name="interview-update"),
    path("<int:pk>/delete/", InterviewDeleteView.as_view(), name="interview-delete"),

    path(
        "feedback/<int:pk>/",
        InterviewFeedbackDetailView.as_view(),
        name="feedback-detail",
    ),
    path(
        "feedback/create/",
        InterviewFeedbackCreateView.as_view(),
        name="feedback-create",
    ),
    path(
        "feedback/<int:pk>/reply/",
        InterviewFeedbackReplyCreateView.as_view(),
        name="feedback-reply-create",
    ),
    path(
        "feedback/<int:pk>/edit/",
        InterviewFeedbackUpdateView.as_view(),
        name="feedback-update",
    ),
    path(
        "feedback/<int:pk>/delete/",
        InterviewFeedbackDeleteView.as_view(),
        name="feedback-delete",
    ),
    path(
        "<int:interview_pk>/feedback/",
        FeedbackThreadView.as_view(),
        name="feedback-thread",
    ),
]