"""Domain services for the deliberator qualification exam."""

from __future__ import annotations

import math
import secrets
from collections.abc import Callable, Sequence

from django.db import IntegrityError, transaction
from django.utils import timezone

from .authorization_services import AuthorizationService
from .db import atomic_for_model
from .deliberation_services import deliberator_term_end_at
from .exceptions import DomainError
from .event_ledger import append_event
from .event_payloads import deliberator_exam_change_payload
from .governance_setup import DELIBERATOR_EXAM_MANAGE_PERMISSION
from .member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, ensure_catalog_role, member_has_role
from .models import DeliberatorExamAttempt, DeliberatorExamPolicy, DeliberatorExamQuestion, Member, RoleAssignment, SystemEvent
from .role_assignment_services import create_role_assignment


def _assert_exam_candidate(member: Member, *, at_time=None) -> None:
    checked_at = at_time or timezone.now()
    if member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("当前成员状态不能参加执衡者考试。")
    if member.user_id and not member.user.is_active:
        raise DomainError("登录账号已停用，不能参加执衡者考试。")
    if not member_has_role(member, ROLE_COVENANTER, checked_at=checked_at):
        raise DomainError("只有当前有效的守约者可以参加执衡者考试。")
    if member_has_role(member, ROLE_DELIBERATOR, checked_at=checked_at):
        raise DomainError("当前执衡者任期尚未结束，不能重复申请。")


def _assert_exam_administrator(member: Member) -> None:
    if not AuthorizationService().member_has_permission(member, DELIBERATOR_EXAM_MANAGE_PERMISSION):
        raise DomainError("没有维护执衡者题库的权限。")


def _append_question_event(question: DeliberatorExamQuestion, *, actor: Member, action: str) -> None:
    append_event(
        event_type=SystemEvent.EventType.DELIBERATOR_EXAM_QUESTION_CHANGED,
        aggregate_type="DeliberatorExamQuestion",
        aggregate_id=f"{question.question_id}:v{question.version}",
        actor_member=actor,
        payload_json=deliberator_exam_change_payload(
            subject_type="deliberator_exam_question",
            subject_ref=f"{question.question_id}:v{question.version}",
            action=action,
            stage=question.status,
            summary="执衡者资格考试题库配置已变更。",
            public_facts={"question_version": question.version, "status": question.status, "points": question.points},
        ),
    )


def _append_policy_event(policy: DeliberatorExamPolicy, *, actor: Member, action: str) -> None:
    append_event(
        event_type=SystemEvent.EventType.DELIBERATOR_EXAM_POLICY_CHANGED,
        aggregate_type="DeliberatorExamPolicy",
        aggregate_id=policy.policy_id,
        actor_member=actor,
        payload_json=deliberator_exam_change_payload(
            subject_type="deliberator_exam_policy",
            subject_ref=policy.policy_id,
            action=action,
            stage=policy.status,
            summary="执衡者资格考试政策已变更。",
            public_facts={
                "policy_version": policy.version,
                "question_count": policy.question_count,
                "passing_percent": policy.passing_percent,
                "status": policy.status,
            },
        ),
    )


@atomic_for_model(DeliberatorExamPolicy)
def publish_exam_policy(*, actor: Member, question_count: int, passing_percent: int) -> DeliberatorExamPolicy:
    """Publish a new policy version and retire the previously active version."""
    _assert_exam_administrator(actor)
    now = timezone.now()
    active_questions = DeliberatorExamQuestion.objects.filter(status=DeliberatorExamQuestion.Status.PUBLISHED).count()
    if question_count < 1 or active_questions < question_count:
        raise DomainError("已发布有效题目不足，不能发布该考试政策。")
    if not 1 <= passing_percent <= 100:
        raise DomainError("及格百分比必须在 1 到 100 之间。")
    DeliberatorExamPolicy.objects.filter(status=DeliberatorExamPolicy.Status.ACTIVE).update(
        status=DeliberatorExamPolicy.Status.RETIRED,
        active_slot=None,
    )
    latest = DeliberatorExamPolicy.objects.order_by("-version").first()
    policy = DeliberatorExamPolicy(
        version=(latest.version + 1 if latest else 1), question_count=question_count,
        passing_percent=passing_percent, status=DeliberatorExamPolicy.Status.ACTIVE,
        published_by=actor, published_at=now,
    )
    policy.full_clean()
    try:
        with transaction.atomic():
            policy.save()
    except IntegrityError as exc:
        raise DomainError("已有另一项考试政策同时生效，请刷新后重试。") from exc
    _append_policy_event(policy, actor=actor, action="published")
    return policy


@atomic_for_model(DeliberatorExamQuestion)
def create_exam_question(
    *, actor: Member, prompt: str, options: list[dict], correct_option_id: str,
    points: int = 1, explanation: str = "", publish: bool = False,
) -> DeliberatorExamQuestion:
    """Create and optionally publish a validated first question version."""
    _assert_exam_administrator(actor)
    now = timezone.now()
    question = DeliberatorExamQuestion(
        prompt=prompt.strip(), options_json=options, correct_option_id=correct_option_id,
        points=points, explanation=explanation,
        status=(DeliberatorExamQuestion.Status.PUBLISHED if publish else DeliberatorExamQuestion.Status.DRAFT),
        created_by=actor, published_by=(actor if publish else None), published_at=(now if publish else None),
    )
    question.full_clean()
    question.save()
    _append_question_event(question, actor=actor, action="published" if publish else "draft_created")
    return question


@atomic_for_model(DeliberatorExamQuestion)
def publish_exam_question(*, actor: Member, question: DeliberatorExamQuestion) -> DeliberatorExamQuestion:
    """Publish one validated draft question without changing its content."""
    _assert_exam_administrator(actor)
    if question.status != DeliberatorExamQuestion.Status.DRAFT:
        raise DomainError("只有草稿题目可以发布。")
    question.full_clean()
    DeliberatorExamQuestion.objects.filter(
        question_id=question.question_id,
        status=DeliberatorExamQuestion.Status.PUBLISHED,
    ).exclude(pk=question.pk).update(status=DeliberatorExamQuestion.Status.RETIRED)
    question.status = DeliberatorExamQuestion.Status.PUBLISHED
    question.published_by = actor
    question.published_at = timezone.now()
    question.save(update_fields=("status", "published_by", "published_at", "updated_at"))
    _append_question_event(question, actor=actor, action="published")
    return question


@atomic_for_model(DeliberatorExamQuestion)
def copy_exam_question_to_draft(
    *, actor: Member, question: DeliberatorExamQuestion,
) -> DeliberatorExamQuestion:
    """Create the next editable version while preserving the published version."""
    _assert_exam_administrator(actor)
    latest = DeliberatorExamQuestion.objects.filter(question_id=question.question_id).order_by("-version").first()
    if latest is None or latest.pk != question.pk or question.status == DeliberatorExamQuestion.Status.DRAFT:
        raise DomainError("只能从题目的最新已发布或已停用版本创建新草稿。")
    draft = DeliberatorExamQuestion.objects.create(
        question_id=question.question_id,
        version=question.version + 1,
        prompt=question.prompt,
        options_json=question.options_json,
        correct_option_id=question.correct_option_id,
        points=question.points,
        explanation=question.explanation,
        status=DeliberatorExamQuestion.Status.DRAFT,
        created_by=actor,
    )
    _append_question_event(draft, actor=actor, action="draft_version_created")
    return draft


@atomic_for_model(DeliberatorExamQuestion)
def replace_exam_question(
    *, actor: Member, question: DeliberatorExamQuestion, prompt: str,
    options: list[dict], correct_option_id: str, points: int = 1, explanation: str = "",
) -> DeliberatorExamQuestion:
    """Publish a replacement version while retaining the previous question."""
    _assert_exam_administrator(actor)
    now = timezone.now()
    question.status = DeliberatorExamQuestion.Status.RETIRED
    question.save(update_fields=("status", "updated_at"))
    replacement = DeliberatorExamQuestion(
        question_id=question.question_id, version=question.version + 1,
        prompt=prompt.strip(), options_json=options, correct_option_id=correct_option_id,
        points=points, explanation=explanation, status=DeliberatorExamQuestion.Status.PUBLISHED,
        created_by=actor, published_by=actor, published_at=now,
    )
    replacement.full_clean()
    replacement.save()
    _append_question_event(question, actor=actor, action="retired")
    _append_question_event(replacement, actor=actor, action="replacement_published")
    return replacement


@atomic_for_model(DeliberatorExamQuestion)
def retire_exam_question(*, actor: Member, question: DeliberatorExamQuestion) -> DeliberatorExamQuestion:
    """Retire the latest published or draft question version without deleting history."""
    _assert_exam_administrator(actor)
    if question.status == DeliberatorExamQuestion.Status.RETIRED:
        return question
    question.status = DeliberatorExamQuestion.Status.RETIRED
    question.save(update_fields=("status", "updated_at"))
    _append_question_event(question, actor=actor, action="retired")
    return question


@atomic_for_model(DeliberatorExamAttempt)
def start_deliberator_exam(
    *, member: Member,
    sampler: Callable[[Sequence[DeliberatorExamQuestion], int], Sequence[DeliberatorExamQuestion]] | None = None,
) -> DeliberatorExamAttempt:
    """Create a private server-selected exam snapshot for an eligible member."""
    _assert_exam_candidate(member)
    policy = DeliberatorExamPolicy.objects.select_for_update().filter(status=DeliberatorExamPolicy.Status.ACTIVE).order_by("-version").first()
    if policy is None:
        raise DomainError("执衡者考试政策尚未发布。")
    questions = list(DeliberatorExamQuestion.objects.filter(status=DeliberatorExamQuestion.Status.PUBLISHED).order_by("question_id", "-version"))
    if len(questions) < policy.question_count:
        raise DomainError("执衡者考试题库暂不可用，请联系管理员维护。")
    selected = list((sampler or secrets.SystemRandom().sample)(questions, policy.question_count))
    snapshot = [{
        "snapshot_id": f"q{index + 1}", "question_id": item.question_id,
        "version": item.version, "prompt": item.prompt, "options": item.options_json,
        "correct_option_id": item.correct_option_id, "points": item.points,
    } for index, item in enumerate(selected)]
    total = sum(item["points"] for item in snapshot)
    return DeliberatorExamAttempt.objects.create(
        member=member, policy=policy, policy_version=policy.version,
        question_snapshot_json=snapshot, total_points=total,
        passing_score=math.ceil(total * policy.passing_percent / 100),
    )


@atomic_for_model(DeliberatorExamAttempt)
def submit_deliberator_exam(
    *, member: Member, attempt: DeliberatorExamAttempt, answers: dict[str, str], at_time=None,
) -> DeliberatorExamAttempt:
    """Grade one attempt once and atomically grant a one-year deliberator term."""
    checked_at = at_time or timezone.now()
    locked = DeliberatorExamAttempt.objects.select_for_update().select_related("member").get(pk=attempt.pk)
    if locked.member_id != member.pk:
        raise DomainError("该考试尝试不属于当前成员。")
    if locked.status != DeliberatorExamAttempt.Status.IN_PROGRESS:
        raise DomainError("该考试已经提交，不能重复评分。")
    try:
        _assert_exam_candidate(member, at_time=checked_at)
    except DomainError:
        locked.status = DeliberatorExamAttempt.Status.INVALIDATED
        locked.submitted_at = checked_at
        locked.answers_json = {}
        locked.score = 0
        locked.save(update_fields=("status", "submitted_at", "answers_json", "score"))
        return locked
    expected_ids = {item["snapshot_id"] for item in locked.question_snapshot_json}
    if set(answers) != expected_ids:
        raise DomainError("请完整回答本次考试的全部题目。")
    score = 0
    for item in locked.question_snapshot_json:
        option_ids = {str(option.get("id", "")) for option in item["options"]}
        selected = str(answers[item["snapshot_id"]])
        if selected not in option_ids:
            raise DomainError("提交的选项不属于本次考试。")
        if selected == item["correct_option_id"]:
            score += int(item["points"])
    locked.answers_json = answers
    locked.score = score
    locked.submitted_at = checked_at
    if score >= locked.passing_score:
        assignment = create_role_assignment(
            member=member, role=ensure_catalog_role(ROLE_DELIBERATOR), start_at=checked_at,
            end_at=deliberator_term_end_at(checked_at),
            source_type=RoleAssignment.SourceType.SELF_APPLICATION,
        )
        existing_attempt = DeliberatorExamAttempt.objects.filter(role_assignment=assignment).exclude(pk=locked.pk).exists()
        if existing_attempt:
            locked.status = DeliberatorExamAttempt.Status.INVALIDATED
            locked.role_assignment = None
            locked.full_clean()
            locked.save(update_fields=("answers_json", "score", "submitted_at", "status", "role_assignment"))
            return locked
        locked.status = DeliberatorExamAttempt.Status.PASSED
        locked.role_assignment = assignment
        from .application_services import reopen_zero_electorate_member_admissions

        reopen_zero_electorate_member_admissions(proposer_member=member)
    else:
        locked.status = DeliberatorExamAttempt.Status.FAILED
    locked.full_clean()
    locked.save(update_fields=("answers_json", "score", "submitted_at", "status", "role_assignment"))
    return locked


def member_exam_view(attempt: DeliberatorExamAttempt) -> dict:
    """Return the member-safe projection without answers or grading secrets."""
    return {
        "attempt_id": attempt.attempt_id,
        "questions": [{
            "snapshot_id": item["snapshot_id"], "prompt": item["prompt"], "options": item["options"],
        } for item in attempt.question_snapshot_json],
        "score": attempt.score, "total_points": attempt.total_points,
        "passing_score": attempt.passing_score, "status": attempt.status,
    }
