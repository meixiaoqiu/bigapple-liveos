from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import RequestFactory, TestCase, override_settings

from core.tests.helpers import create_member, login_as_member
from live_os.error_handlers import server_error


@override_settings(DEBUG=False)
class RuntimeErrorPageTests(TestCase):
    def test_get_logout_renders_friendly_405_without_logging_out(self) -> None:
        user = get_user_model().objects.create_user(username="logout-405", password="test-password")
        self.client.force_login(user)

        response = self.client.get("/logout/")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertContains(response, "请求方式不正确", status_code=405)
        self.assertContains(response, "退出登录需要从页面上的「退出」按钮提交", status_code=405)
        self.assertContains(response, "返回首页", status_code=405)
        self.assertContains(response, "进入 Workspace", status_code=405)
        self.assertContains(response, "允许: POST", status_code=405)

    def test_post_logout_works_normally(self) -> None:
        user = get_user_model().objects.create_user(username="logout-ok", password="test-password")
        self.client.force_login(user)
        self.assertIn(SESSION_KEY, self.client.session)

        response = self.client.post("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_unknown_page_renders_friendly_404(self) -> None:
        response = self.client.get("/definitely-not-a-live-os-page/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "页面不存在", status_code=404)
        self.assertContains(response, "返回首页", status_code=404)

    def test_page_forbidden_response_renders_friendly_403(self) -> None:
        user = get_user_model().objects.create_user(username="staff-without-member", password="test-password")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        self.client.force_login(user)

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "无权访问", status_code=403)
        self.assertContains(response, "当前账号没有访问这个页面", status_code=403)

    def test_server_error_handler_uses_runtime_error_template(self) -> None:
        request = RequestFactory().get("/boom/")

        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "系统暂时无法完成请求", status_code=500)

    def test_error_page_includes_runtime_header(self) -> None:
        response = self.client.get("/definitely-not-a-real-page-2/")
        self.assertNotContains(response, 'href="/logout/"', status_code=404)

    def test_unauth_error_page_shows_login_register(self) -> None:
        """未登录错误页显示登录和注册按钮。"""
        response = self.client.get("/definitely-not-a-real-page-3/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "登录", status_code=404)
        self.assertContains(response, "注册", status_code=404)

    def test_auth_error_page_does_not_show_login_register(self) -> None:
        """已登录错误页不显示登录和注册按钮。"""
        member = create_member("err-member-01", display_name="错误页成员")
        login_as_member(self.client, member)
        response = self.client.get("/definitely-not-a-real-page-4/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "/register/", status_code=404)
        self.assertNotContains(response, "/login/", status_code=404)
