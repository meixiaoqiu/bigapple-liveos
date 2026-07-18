"""Forms for public member and partner applications."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import UsernameField
from django.core.exceptions import ValidationError as DjangoValidationError

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


# --- Member application role/availability metadata -------------------------------------
# These constants back the role_gap ChoiceField and let the template render cards
# (label / description / remote_mode / open) without duplicating the data.

ROLE_GAP_CHOICES = (
    ("settled_resident", "安居成员"),
    ("service_resident", "生活服务成员"),
    ("developer_ai_engineer", "系统开发与 AI 工程"),
    ("community_contributor", "社区贡献者"),
)

ROLE_GAP_METADATA = {
    "settled_resident": {
        "label": "安居成员",
        "description": "常驻现场，参与日常起居与社区运转，需要线下稳定在场。",
        "remote_mode": "onsite_required",
        "open": True,
    },
    "service_resident": {
        "label": "生活服务成员",
        "description": "承担餐饮、维护、清洁等生活服务，需要线下在场。",
        "remote_mode": "onsite_required",
        "open": True,
    },
    "developer_ai_engineer": {
        "label": "系统开发与 AI 工程",
        "description": "负责 Live OS 系统开发与 AI 工程任务，可远程协作。",
        "remote_mode": "remote_possible",
        "open": True,
    },
    "community_contributor": {
        "label": "社区贡献者",
        "description": "以混合方式贡献内容、活动或外部协作，线上线下均可。",
        "remote_mode": "hybrid",
        "open": True,
    },
}

REMOTE_MODE_LABELS = {
    "onsite_required": "需到场",
    "remote_possible": "可远程",
    "hybrid": "混合",
}

AVAILABILITY_SLOT_CHOICES = (
    ("any_time", "全天可用"),
    ("off_hours", "工作之余"),
    ("weekend", "周末"),
)

MOTIVATION_REASON_CHOICES = (
    ("safe_stable_place", "想找一个安全、稳定、安静的生活环境"),
    ("better_community", "愿意付费获得更好的社区生存环境"),
    ("build_community", "愿意参与建设一个长期社区"),
    ("remote_system_work", "想远程参与系统、AI 或内容建设"),
    ("learn_and_practice", "想在真实项目中学习和实践"),
    ("other", "其他理由"),
)


class ParticipantRegistrationForm(forms.Form):
    """Create a user account and basic Member identity.

    This form does NOT create a MemberApplication or enter the governance
    pipeline — it only creates ``User`` + ``Member`` + ``ROLE_BIG_APPLE_MEMBER``.
    """

    username = UsernameField(label="登录账号", max_length=150)
    password1 = forms.CharField(label="登录密码", widget=forms.PasswordInput)
    password2 = forms.CharField(label="确认密码", widget=forms.PasswordInput)
    display_name = forms.CharField(label="姓名或称呼", max_length=255)
    contact = forms.CharField(label="联系方式（建议留微信或电话）", max_length=255)

    def clean_username(self) -> str:
        username = str(self.cleaned_data["username"] or "").strip()
        if not username:
            raise forms.ValidationError("登录账号不能为空。")
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
            except DjangoValidationError as exc:
                self.add_error("password1", exc)
        return cleaned_data


class MemberApplicationForm(forms.Form):
    username = UsernameField(label="登录账号", max_length=150)
    password1 = forms.CharField(label="登录密码", widget=forms.PasswordInput)
    password2 = forms.CharField(label="确认密码", widget=forms.PasswordInput)
    applicant_name = forms.CharField(label="姓名或称呼", max_length=255)
    contact = forms.CharField(label="联系方式（建议留微信或电话）", max_length=255)
    role_gap = forms.ChoiceField(
        label="意向角色",
        choices=ROLE_GAP_CHOICES,
        widget=forms.RadioSelect,
    )
    availability_slots = forms.MultipleChoiceField(
        label="可投入时段",
        choices=AVAILABILITY_SLOT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    availability_hours_per_week = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=168,
        widget=forms.HiddenInput,
    )
    motivation = forms.CharField(required=False, widget=forms.HiddenInput)
    motivation_reasons = forms.MultipleChoiceField(
        label="为什么想参加",
        choices=MOTIVATION_REASON_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    motivation_other_text = forms.CharField(
        label="其他理由",
        required=False,
        widget=forms.Textarea,
    )
    capabilities_text = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    confirm_submit = forms.BooleanField(
        label="我已确认所填信息真实有效，并理解提交后由组织方审核",
        required=True,
    )
    requested_member_no = forms.CharField(max_length=64, required=False, widget=forms.HiddenInput)

    def __init__(self, *args, existing_user=None, existing_member: Member | None = None, **kwargs):
        self.existing_user = existing_user
        self.existing_member = existing_member
        super().__init__(*args, **kwargs)
        if existing_user is not None:
            # Authenticated users already have an account — hide account fields completely.
            self.fields.pop("username", None)
            self.fields.pop("password1", None)
            self.fields.pop("password2", None)
            self.fields["requested_member_no"].initial = existing_member.member_no if existing_member else str(existing_user.get_username() or "").strip()
        if existing_member is not None:
            self.fields["applicant_name"].initial = existing_member.display_name or ""

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
        elif requested_member_no:
            existing_member = Member.objects.filter(member_no=requested_member_no).first()
            if existing_member is not None and existing_member != self.existing_member:
                self.add_error("requested_member_no", "该成员编号已存在。")
        slots = list(cleaned_data.get("availability_slots") or [])
        if "any_time" in slots and ("off_hours" in slots or "weekend" in slots):
            self.add_error(
                "availability_slots",
                "选择「全天可用」时不能再叠加「工作之余」或「周末」。",
            )
        reasons = list(cleaned_data.get("motivation_reasons") or [])
        legacy_motivation = str(cleaned_data.get("motivation") or "").strip()
        other_reason = str(cleaned_data.get("motivation_other_text") or "").strip()
        if not reasons and not legacy_motivation:
            self.add_error("motivation_reasons", "请至少选择一个报名理由。")
        if "other" in reasons and not other_reason:
            self.add_error("motivation_other_text", "选择其他理由时，请填写具体理由。")
        if cleaned_data.get("availability_hours_per_week") is None:
            cleaned_data["availability_hours_per_week"] = 0
        return cleaned_data

    def role_gap_cards(self) -> list[dict]:
        """Return renderable card metadata for each role_gap choice."""
        cards: list[dict] = []
        for value, _label in ROLE_GAP_CHOICES:
            meta = ROLE_GAP_METADATA.get(value, {})
            remote_mode = meta.get("remote_mode", "")
            cards.append(
                {
                    "value": value,
                    "label": meta.get("label", _label),
                    "description": meta.get("description", ""),
                    "remote_mode": remote_mode,
                    "remote_mode_label": REMOTE_MODE_LABELS.get(remote_mode, remote_mode),
                    "open": bool(meta.get("open", True)),
                }
            )
        return cards

    def capability_scores(self) -> dict[str, int]:
        return _capability_scores(self.cleaned_data.get("capabilities_text", ""))

    def document_authority_domains(self) -> list[str]:
        return []

    def motivation_text(self) -> str:
        legacy_motivation = str(self.cleaned_data.get("motivation") or "").strip()
        reasons = list(self.cleaned_data.get("motivation_reasons") or [])
        if not reasons and legacy_motivation:
            return legacy_motivation
        labels = dict(MOTIVATION_REASON_CHOICES)
        parts = [labels[value] for value in reasons if value != "other" and value in labels]
        other_reason = str(self.cleaned_data.get("motivation_other_text") or "").strip()
        if other_reason:
            parts.append(other_reason)
        return "；".join(parts)

    def dynamic_answers(self) -> list[dict]:
        """Return motivation answers as a JSON-serializable array.

        Each entry has ``key``, ``label``, ``type`` and ``answer`` fields so the
        view/service layer can persist them verbatim.
        """
        labels = dict(MOTIVATION_REASON_CHOICES)
        reasons = list(self.cleaned_data.get("motivation_reasons") or [])
        return [
            {
                "key": "motivation_reasons",
                "label": self.fields["motivation_reasons"].label,
                "type": "checkbox",
                "answer": [labels[value] for value in reasons if value in labels],
            },
            {
                "key": "motivation_other",
                "label": self.fields["motivation_other_text"].label,
                "type": "textarea",
                "answer": str(self.cleaned_data.get("motivation_other_text", "") or ""),
            },
        ]


def apply_daisyui_widgets(form: forms.Form) -> forms.Form:
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.HiddenInput):
            continue
        if isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", "textarea textarea-bordered validator min-h-28 w-full")
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "checkbox checkbox-primary")
        else:
            widget.attrs.setdefault("class", "input input-bordered validator w-full")
    return form
