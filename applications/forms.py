"""Forms for public member and partner applications."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import UsernameField

from core.models import Member


def _text_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


def _capability_scores(value: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for item in _text_list(value):
        if ":" in item:
            name, raw_score = item.split(":", 1)
        elif "：" in item:
            name, raw_score = item.split("：", 1)
        else:
            name, raw_score = item, "60"
        name = name.strip()
        if not name:
            continue
        try:
            score = int(raw_score.strip())
        except ValueError:
            score = 60
        scores[name] = max(0, min(score, 100))
    return scores


class MemberApplicationForm(forms.Form):
    username = UsernameField(label="登录账号", max_length=150)
    password1 = forms.CharField(label="登录密码", widget=forms.PasswordInput)
    password2 = forms.CharField(label="确认密码", widget=forms.PasswordInput)
    applicant_name = forms.CharField(label="姓名或称呼", max_length=255)
    contact = forms.CharField(label="联系方式", max_length=255)
    motivation = forms.CharField(label="为什么想参加", widget=forms.Textarea)
    availability_hours_per_week = forms.IntegerField(label="每周可投入小时", min_value=0, max_value=168)
    capabilities_text = forms.CharField(
        label="能力自述",
        help_text="用逗号或换行分隔；可写成 做饭:80、视频剪辑:70。",
        widget=forms.Textarea,
    )
    can_issue_responsibility_documents = forms.BooleanField(label="我能出具责任文件", required=False)
    document_authority_domains_text = forms.CharField(
        label="可承担责任文件领域",
        required=False,
        help_text="例如结构安全、电气并网；不能签字盖章可留空。",
        widget=forms.Textarea,
    )
    requested_member_no = forms.CharField(max_length=64, required=False, widget=forms.HiddenInput)

    def clean_username(self) -> str:
        username = str(self.cleaned_data["username"] or "").strip()
        user_model = get_user_model()
        if user_model.objects.filter(username=username).exists():
            raise forms.ValidationError("登录账号已存在。")
        if Member.objects.filter(member_no=username).exists():
            raise forms.ValidationError("该账号已被成员编号使用。")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "两次输入的密码不一致。")
        if password1:
            try:
                validate_password(password1)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        requested_member_no = str(cleaned_data.get("requested_member_no") or "").strip()
        username = str(cleaned_data.get("username") or "").strip()
        if not requested_member_no and username:
            cleaned_data["requested_member_no"] = username
        elif requested_member_no and Member.objects.filter(member_no=requested_member_no).exists():
            self.add_error("requested_member_no", "该成员编号已存在。")
        return cleaned_data

    def capability_scores(self) -> dict[str, int]:
        return _capability_scores(self.cleaned_data["capabilities_text"])

    def document_authority_domains(self) -> list[str]:
        return _text_list(self.cleaned_data.get("document_authority_domains_text", ""))


class PartnerApplicationForm(forms.Form):
    organization_name = forms.CharField(label="合作方名称", max_length=255)
    contact_name = forms.CharField(label="联系人", max_length=255)
    contact = forms.CharField(label="联系方式", max_length=255)
    service_domains_text = forms.CharField(
        label="服务能力",
        help_text="用逗号或换行分隔，例如结构检测、光伏设计、电气并网。",
        widget=forms.Textarea,
    )
    can_issue_responsibility_documents = forms.BooleanField(label="可以出具责任文件", required=False)
    responsibility_document_domains_text = forms.CharField(
        label="可出具责任文件领域",
        required=False,
        widget=forms.Textarea,
    )
    qualification_summary = forms.CharField(label="资质说明", required=False, widget=forms.Textarea)
    quote_summary = forms.CharField(label="报价说明", required=False, widget=forms.Textarea)
    service_area = forms.CharField(label="服务地区", max_length=255, required=False)
    delivery_cycle_days = forms.IntegerField(label="交付周期天数", min_value=0, required=False)
    constraints = forms.CharField(label="限制条件", required=False, widget=forms.Textarea)

    def service_domains(self) -> list[str]:
        return _text_list(self.cleaned_data["service_domains_text"])

    def responsibility_document_domains(self) -> list[str]:
        return _text_list(self.cleaned_data.get("responsibility_document_domains_text", ""))


def apply_daisyui_widgets(form: forms.Form) -> forms.Form:
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", "textarea textarea-bordered min-h-28 w-full")
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "checkbox checkbox-primary")
        else:
            widget.attrs.setdefault("class", "input input-bordered w-full")
    return form
