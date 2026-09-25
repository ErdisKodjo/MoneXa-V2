"""Context processors WebUI — cloche de notifications in-app."""
from __future__ import annotations


def notifications(request):
    """Injecte les notifications non lues + compteur pour la cloche."""
    if not request.user.is_authenticated:
        return {"nav_notifications": [], "nav_unread_count": 0}
    unread = NotificationProxy(request)
    return {"nav_notifications": unread.list(), "nav_unread_count": unread.count()}


class NotificationProxy:
    """Petit helper pour éviter deux requêtes identiques par page."""

    def __init__(self, request):
        self._qs = request.user.notifications.filter(is_read=False)

    def list(self):
        return self._qs[:5]

    def count(self):
        return self._qs.count()
