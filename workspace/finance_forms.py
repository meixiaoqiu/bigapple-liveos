"""Workspace forms for finance claim workflows."""

from __future__ import annotations

from django import forms

from core.models import ExpenseClaim, FinanceReview


class ExpenseClaimForm(forms.Form):
    title = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input-bordered", "placeholder": "报销事由"}),
        label="标题",
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={"class": "input input-bordered", "step": "0.01"}),
        label="金额",
    )
    currency = forms.CharField(
        max_length=8,
        initial="CNY",
        widget=forms.TextInput(attrs={"class": "input input-bordered"}),
        label="货币",
    )
    expense_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "input input-bordered", "type": "date"}),
        label="支出日期",
    )
    vendor = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input input-bordered", "placeholder": "供应商/收款方名称"}),
        label="收款方",
    )
    category = forms.ChoiceField(
        choices=ExpenseClaim.Category.choices,
        widget=forms.Select(attrs={"class": "select select-bordered"}),
        label="类别",
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "textarea textarea-bordered", "rows": 4}),
        label="支出说明",
    )


class FinanceReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=FinanceReview.Decision.choices,
        widget=forms.Select(attrs={"class": "select select-bordered"}),
        label="决定",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "textarea textarea-bordered", "rows": 2}),
        label="理由",
    )
