from django.urls import path

from . import views

urlpatterns = [
    path('gallery/', views.GalleryListView.as_view(), name='gallery-list'),
    path('gallery/<uuid:pk>/', views.GalleryDetailView.as_view(), name='gallery-detail'),
    path('gallery/<uuid:pk>/like/', views.LikeView.as_view(), name='gallery-like'),
    path('gallery/<uuid:pk>/remix/', views.RemixView.as_view(), name='gallery-remix'),
    path('gallery/<uuid:pk>/comments/', views.CommentListCreateView.as_view(), name='gallery-comments'),
    path(
        'gallery/<uuid:pk>/comments/<uuid:comment_id>/',
        views.CommentDeleteView.as_view(),
        name='gallery-comment-delete',
    ),
    path('following/', views.FollowingView.as_view(), name='following'),
    path('following/<str:handle>/', views.FollowView.as_view(), name='follow'),
]
