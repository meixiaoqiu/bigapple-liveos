"""Community feedback forms."""

from django import forms

from core.models import CommunityFeedback


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = CommunityFeedback
        fields = ["title", "category", "body"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "input input-bordered",
                    "placeholder": "一句话描述你的反馈",
                    "maxlength": "120",
                }
            ),
            "category": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "body": forms.Textarea(
                attrs={
                    "class": "textarea textarea-bordered",
                    "rows": 6,
                    "placeholder": "详细描述你的反馈内容...",
                }
            ),
        }


class FeedbackResponseForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            ("acknowledged", "已看到"),
            ("answered", "已回应"),
            ("closed", "已关闭"),
        ],
        initial="answered",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    official_response = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "textarea textarea-bordered w-full",
            "rows": 3,
            "placeholder": "公开回应内容...",
        }),
        required=False,
    )
