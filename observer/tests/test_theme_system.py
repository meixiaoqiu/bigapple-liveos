from __future__ import annotations
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from observer.dashboard_theme import build_dashboard_theme_context
from observer.theme import (
    THEME_SESSION_KEY,
    get_active_theme_name,
    get_theme_asset_url,
    get_theme_component_path,
    get_theme_config,
    get_theme_partial_path,
)
def request_with_session(path: str = "/observer/"):
    request = RequestFactory().get(path)
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    return request


class ThemeSystemTests(TestCase):
    """覆盖主题 fallback、asset 和 dashboard 展示契约。"""

    def test_unknown_theme_falls_back_to_default_game(self) -> None:
        self.assertEqual(get_theme_config("missing-theme")["key"], "default_game")

    def test_theme_asset_uses_staticfiles_fallback_safely(self) -> None:
        request = request_with_session()
        request.session[THEME_SESSION_KEY] = "dark"

        self.assertEqual(get_theme_asset_url(request, "css/tokens.css"), "")
        self.assertEqual(get_theme_asset_url(request, "img/mascot/missing.webp"), "")
        self.assertEqual(get_theme_asset_url(request, "../unsafe.css"), "")

    def test_theme_partial_and_component_fall_back_to_default_game(self) -> None:
        request = request_with_session()
        request.session[THEME_SESSION_KEY] = "dark"

        self.assertEqual(
            get_theme_partial_path(request, "mission_list.html"),
            "themes/default_game/partials/mission_list.html",
        )
        self.assertEqual(
            get_theme_component_path(request, "mission_card.html"),
            "themes/default_game/components/empty_state.html",
        )

    def test_dashboard_theme_context_is_complete_without_raw_data(self) -> None:
        request = request_with_session()
        context = build_dashboard_theme_context(request)

        self.assertEqual(context["hero"]["title"], "大苹果观察台")
        self.assertEqual(context["stats"], [])
        self.assertEqual(context["missions"], [])
        self.assertEqual(context["events"], [])
        self.assertTrue(context["map_points"])
        self.assertIn("risk_summary", context)
        self.assertIn("capacity", context)
        self.assertIn("user_progress", context)
        self.assertTrue(context["navigation"])

    def test_dashboard_theme_context_includes_default_extension_fields(self) -> None:
        request = request_with_session()
        context = build_dashboard_theme_context(request)

        self.assertEqual(context["photos"], [])
        self.assertEqual(context["pending_disputes"], [])
        self.assertIn("remaining", context["capacity"])

    def test_unknown_theme_query_parameter_falls_back_without_session_mutation(self) -> None:
        request = request_with_session("/observer/?theme=missing-theme")
        from observer.theme_views import apply_theme_query_override

        apply_theme_query_override(request)

        self.assertEqual(get_active_theme_name(request), "default_game")
        self.assertNotIn(THEME_SESSION_KEY, request.session)

