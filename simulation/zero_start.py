"""Hour-level zero-start application and startup-gate simulation."""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from core.application_services import review_partner_application
from core.db import atomic_for_model
from core.exceptions import DomainError
from core.models import (
    Event,
    Member,
    MemberApplication,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    PartnerApplication,
    SimulationFailure,
    SimulationRun,
    SimulationRunDisposition,
    SimulationSnapshot,
)
from live_os.demo_seed.zero_start import (
    ZERO_START_FOUNDER_MEMBER_NO,
    ZERO_START_PLAN_ID,
    ZERO_START_REVISION_ID,
    seed_zero_start,
)
from worlds.state import get_current_world

from .ids import (
    generate_plan_change_operation_id,
    generate_plan_change_set_id,
    generate_plan_revision_proposal_id,
    generate_simulation_failure_id,
    generate_simulation_run_id,
)
from .disposition import CONTROL_DATABASE_ALIAS, is_continuable_zero_start_observation_run
from .form_drivers import FormSubmissionResult, HttpFormDriver
from .projections import (
    candidate_summary_for_run,
    partner_snapshot,
    skills_match_requirement,
    startup_gate_summary_for_run,
)
from .run_state import create_simulation_turn_and_event


@dataclass(frozen=True)
class ApplicantSpec:
    index: int
    apply_hour: int
    screen_hour: int
    display_name: str
    motivation: str
    capability_scores: dict[str, int]
    availability_hours_per_week: int
    document_authority_domains: tuple[str, ...] = ()
    withdraw_hour: int | None = None


@dataclass(frozen=True)
class PartnerSpec:
    index: int
    apply_hour: int
    screen_hour: int
    organization_name: str
    contact_name: str
    service_domains: tuple[str, ...]
    can_issue_responsibility_documents: bool
    responsibility_document_domains: tuple[str, ...]
    qualification_summary: str
    quote_summary: str
    service_area: str
    delivery_cycle_days: int | None = None
    constraints: str = ""
    review_status: str = "standby"


APPLICANTS: tuple[ApplicantSpec, ...] = (
    ApplicantSpec(
        index=1,
        apply_hour=7,
        screen_hour=14,
        display_name="报名者 001",
        motivation="想参与真实社区建设，能做线上资料整理。",
        capability_scores={"文档": 72, "社群沟通": 66},
        availability_hours_per_week=10,
    ),
    ApplicantSpec(
        index=2,
        apply_hour=18,
        screen_hour=25,
        display_name="报名者 002",
        motivation="有工地经验，愿意短期到场。",
        capability_scores={"搬运": 76, "现场协助": 64, "安全意识": 58},
        availability_hours_per_week=30,
    ),
    ApplicantSpec(
        index=3,
        apply_hour=31,
        screen_hour=40,
        display_name="报名者 003",
        motivation="自称懂光伏，希望远程帮忙看方案。",
        capability_scores={"光伏经验线索": 61, "电气常识": 48},
        availability_hours_per_week=6,
    ),
    ApplicantSpec(
        index=4,
        apply_hour=46,
        screen_hour=58,
        display_name="报名者 004",
        motivation="可以负责采购询价和记录。",
        capability_scores={"采购": 70, "表格": 68, "沟通": 62},
        availability_hours_per_week=12,
    ),
    ApplicantSpec(
        index=5,
        apply_hour=68,
        screen_hour=82,
        display_name="报名者 005",
        motivation="结构专业学生，愿意学习，但不能签字或盖章。",
        capability_scores={"结构知识线索": 55, "学习能力": 74},
        availability_hours_per_week=8,
        withdraw_hour=80,
    ),
    ApplicantSpec(
        index=6,
        apply_hour=72,
        screen_hour=90,
        display_name="报名者 006",
        motivation="被自媒体内容吸引，但目前只能偶尔线上围观。",
        capability_scores={"兴趣": 60},
        availability_hours_per_week=2,
    ),
)

PARTNER_APPLICANTS: tuple[PartnerSpec, ...] = (
    PartnerSpec(
        index=1,
        apply_hour=36,
        screen_hour=52,
        organization_name="本地综合施工队线索 001",
        contact_name="合作方联系人 001",
        service_domains=("搬运", "低风险辅助施工", "现场协调"),
        can_issue_responsibility_documents=False,
        responsibility_document_domains=(),
        qualification_summary="可组织人工和常规施工协助，但不能对结构、电气或并网文件签字盖章。",
        quote_summary="按天报价，需明确工作边界。",
        service_area="本地及周边",
        delivery_cycle_days=7,
        constraints="只能承担低风险辅助，不承担专业工程责任文件。",
        review_status="standby",
    ),
    PartnerSpec(
        index=2,
        apply_hour=84,
        screen_hour=110,
        organization_name="光伏设备渠道商线索 002",
        contact_name="合作方联系人 002",
        service_domains=("组件报价", "逆变器报价", "设备清单建议"),
        can_issue_responsibility_documents=False,
        responsibility_document_domains=(),
        qualification_summary="可以提供设备报价和清单建议，但不承担系统设计和并网责任。",
        quote_summary="设备报价有效期 7 天，需另行确认运输和安装。",
        service_area="省内",
        delivery_cycle_days=14,
        constraints="只卖设备，不出设计文件。",
        review_status="standby",
    ),
)

PARTNER_GROWTH_PROFILES: tuple[dict[str, object], ...] = (
    {
        "name": "材料运输与仓储合作方",
        "service_domains": ("运输", "仓储", "装卸协调"),
        "can_issue_responsibility_documents": False,
        "responsibility_document_domains": (),
        "qualification_summary": "可提供运输、短期仓储和装卸组织，不能承担工程责任文件。",
        "quote_summary": "按车次、仓储天数和装卸人次报价。",
        "service_area": "省内",
        "delivery_cycle_days": 10,
        "constraints": "仅覆盖物流协作，不覆盖设计、施工和验收责任。",
        "review_status": PartnerApplication.Status.STANDBY,
    },
    {
        "name": "结构安全评估机构",
        "service_domains": ("结构复核", "屋顶荷载评估", "房屋安全鉴定"),
        "can_issue_responsibility_documents": True,
        "responsibility_document_domains": ("structural_safety_document",),
        "qualification_summary": "具备结构复核或房屋安全鉴定能力，可对具体场地出具书面结论。",
        "quote_summary": "按场地踏勘、资料审查和报告深度报价。",
        "service_area": "本地及周边",
        "delivery_cycle_days": 21,
        "constraints": "需要产权资料、原始图纸或现场踏勘条件。",
        "review_status": PartnerApplication.Status.QUALIFIED,
    },
    {
        "name": "光伏系统设计顾问",
        "service_domains": ("光伏方案设计", "组件布置", "设备清单", "发电量测算"),
        "can_issue_responsibility_documents": True,
        "responsibility_document_domains": ("pv_system_design_document",),
        "qualification_summary": "可承担光伏系统方案设计文件责任，能输出组件布置和设备清单。",
        "quote_summary": "按装机规模和设计深度报价。",
        "service_area": "全国远程加本地踏勘",
        "delivery_cycle_days": 14,
        "constraints": "正式施工图需要在结构和并网预筛后锁定。",
        "review_status": PartnerApplication.Status.QUALIFIED,
    },
    {
        "name": "电气并网设计单位",
        "service_domains": ("电气接入", "一次系统图", "保护配置", "防雷接地", "并网材料"),
        "can_issue_responsibility_documents": True,
        "responsibility_document_domains": ("electrical_grid_document",),
        "qualification_summary": "可承担电气接入和并网材料责任，熟悉低压/高压接入流程。",
        "quote_summary": "按接入电压等级、资料深度和现场次数报价。",
        "service_area": "省内",
        "delivery_cycle_days": 28,
        "constraints": "需要电网接入点、容量和业主资料配合。",
        "review_status": PartnerApplication.Status.QUALIFIED,
    },
    {
        "name": "施工安全与质量承包方",
        "service_domains": ("施工组织", "安全施工方案", "高处作业", "隐蔽工程记录"),
        "can_issue_responsibility_documents": True,
        "responsibility_document_domains": ("construction_safety_quality_document",),
        "qualification_summary": "可承担施工组织、安全质量和现场记录责任。",
        "quote_summary": "按工期、人员、保险、安全措施和验收资料报价。",
        "service_area": "本地及周边",
        "delivery_cycle_days": 30,
        "constraints": "社区成员只能做低风险辅助，不能替代施工责任主体。",
        "review_status": PartnerApplication.Status.QUALIFIED,
    },
    {
        "name": "验收调试与运维交接顾问",
        "service_domains": ("调试记录", "并网验收资料", "竣工资料", "运维交接"),
        "can_issue_responsibility_documents": True,
        "responsibility_document_domains": ("acceptance_archive_document",),
        "qualification_summary": "可协助形成调试、验收、竣工和运维交接资料闭环。",
        "quote_summary": "按资料清单、现场配合和交接范围报价。",
        "service_area": "省内",
        "delivery_cycle_days": 14,
        "constraints": "需要设计、施工和并网流程资料完整。",
        "review_status": PartnerApplication.Status.QUALIFIED,
    },
    {
        "name": "设备材料报价合作方",
        "service_domains": ("组件报价", "逆变器报价", "支架报价", "辅材报价"),
        "can_issue_responsibility_documents": False,
        "responsibility_document_domains": (),
        "qualification_summary": "可提供多轮设备和材料报价，但不承担设计、施工和验收责任。",
        "quote_summary": "按清单报价，价格有效期 7 至 14 天。",
        "service_area": "全国",
        "delivery_cycle_days": 12,
        "constraints": "报价只能作为采购参考，不能替代专业设计文件。",
        "review_status": PartnerApplication.Status.STANDBY,
    },
)


def _applicant_specs_for_hours(hours: int) -> tuple[ApplicantSpec, ...]:
    specs = list(APPLICANTS)
    capability_profiles = (
        ("会做饭和基础后勤，愿意长期参与。", {"做饭": 78, "后勤": 68, "餐食": 70}, 18),
        ("能做现场协助和搬运，接受低风险辅助工作。", {"现场协助": 70, "搬运": 72, "安全意识": 61}, 24),
        ("擅长资料整理和表格归档。", {"文档": 74, "表格": 72, "资料整理": 70}, 10),
        ("愿意负责社群沟通和报名答疑。", {"社群沟通": 75, "沟通": 70, "自媒体": 64}, 12),
        ("可以做采购询价和记录。", {"采购": 72, "记录": 68, "表格": 66}, 8),
        ("只是被内容吸引，暂时不能稳定参与。", {"兴趣": 55}, 2),
    )
    next_index = 7
    for wave_index, wave_hour in enumerate(range(96, hours, 12)):
        wave_size = 1 + min(wave_index // 2, 4)
        for offset in range(wave_size):
            apply_hour = wave_hour + offset
            if apply_hour >= hours:
                break
            motivation, capabilities, availability = capability_profiles[(wave_index + offset) % len(capability_profiles)]
            specs.append(
                ApplicantSpec(
                    index=next_index,
                    apply_hour=apply_hour,
                    screen_hour=min(apply_hour + 10 + (offset % 4), max(hours - 1, apply_hour)),
                    display_name=f"报名者 {next_index:03d}",
                    motivation=motivation,
                    capability_scores=capabilities,
                    availability_hours_per_week=availability,
                )
            )
            next_index += 1
    return tuple(specs)


def _partner_specs_for_hours(hours: int) -> tuple[PartnerSpec, ...]:
    specs = list(PARTNER_APPLICANTS)
    next_index = 3
    for wave_index, wave_hour in enumerate(range(132, hours, 48)):
        wave_size = 1 + min(wave_index // 3, 3)
        for offset in range(wave_size):
            apply_hour = wave_hour + offset * 3
            if apply_hour >= hours:
                break
            profile = PARTNER_GROWTH_PROFILES[(wave_index + offset) % len(PARTNER_GROWTH_PROFILES)]
            screen_delay = 18 + (offset % 4) * 4 + min(wave_index, 5)
            specs.append(
                PartnerSpec(
                    index=next_index,
                    apply_hour=apply_hour,
                    screen_hour=min(apply_hour + screen_delay, max(hours - 1, apply_hour)),
                    organization_name=f"{profile['name']}线索 {next_index:03d}",
                    contact_name=f"合作方联系人 {next_index:03d}",
                    service_domains=tuple(profile["service_domains"]),
                    can_issue_responsibility_documents=bool(profile["can_issue_responsibility_documents"]),
                    responsibility_document_domains=tuple(profile["responsibility_document_domains"]),
                    qualification_summary=str(profile["qualification_summary"]),
                    quote_summary=str(profile["quote_summary"]),
                    service_area=str(profile["service_area"]),
                    delivery_cycle_days=int(profile["delivery_cycle_days"]),
                    constraints=str(profile["constraints"]),
                    review_status=str(profile["review_status"]),
                )
            )
            next_index += 1
    return tuple(specs)

APPLICATION_STATUS_REGISTERED = "registered"
APPLICATION_STATUS_CANDIDATE = "candidate"
APPLICATION_STATUS_STANDBY = "standby"
APPLICATION_STATUS_REJECTED = "rejected"
APPLICATION_STATUS_WITHDREW = "withdrew"

STARTUP_CAPABILITY_REQUIREMENTS: tuple[dict[str, object], ...] = (
    {
        "code": "project_coordination",
        "name": "项目发起与协调",
        "min_count": 1,
        "skill_aliases": ["发起", "组织", "沟通"],
        "need_written_document": False,
    },
    {
        "code": "documentation_archive",
        "name": "资料整理与归档",
        "min_count": 1,
        "skill_aliases": ["文档", "表格", "资料整理"],
        "need_written_document": False,
    },
    {
        "code": "community_operations",
        "name": "社群沟通与报名运营",
        "min_count": 1,
        "skill_aliases": ["社群沟通", "沟通", "自媒体"],
        "need_written_document": False,
    },
    {
        "code": "onsite_logistics",
        "name": "现场后勤与低风险协助",
        "min_count": 2,
        "skill_aliases": ["搬运", "现场协助", "安全意识"],
        "need_written_document": False,
    },
    {
        "code": "procurement_records",
        "name": "采购询价与记录",
        "min_count": 1,
        "skill_aliases": ["采购", "表格", "记录"],
        "need_written_document": False,
    },
    {
        "code": "meal_support",
        "name": "做饭与基础生活支持",
        "min_count": 1,
        "skill_aliases": ["做饭", "后勤", "餐食"],
        "need_written_document": False,
    },
)

STARTUP_DOCUMENT_SIGNER_REQUIREMENTS: tuple[dict[str, object], ...] = (
    {
        "code": "structural_safety_document",
        "name": "结构/建筑安全责任文件签署方",
        "document_examples": ["屋顶荷载复核报告", "结构安全评估报告", "房屋安全鉴定报告"],
        "acceptable_signers": ["结构工程师", "建筑设计院", "房屋安全鉴定机构", "结构检测机构"],
    },
    {
        "code": "pv_system_design_document",
        "name": "光伏系统设计责任文件签署方",
        "document_examples": ["光伏系统设计方案", "组件布置方案", "施工图或专业设计文件"],
        "acceptable_signers": ["光伏设计单位", "EPC", "设计顾问"],
    },
    {
        "code": "electrical_grid_document",
        "name": "电气接入与并网责任文件签署方",
        "document_examples": ["电气接入方案", "一次系统图", "并网申请材料", "电网企业并网意见"],
        "acceptable_signers": ["电气设计单位", "电网流程责任主体", "具备电气专业能力的机构"],
    },
    {
        "code": "construction_safety_quality_document",
        "name": "施工安全与质量文件责任主体",
        "document_examples": ["施工合同", "施工组织方案", "安全施工方案", "验收记录"],
        "acceptable_signers": ["施工单位", "安全质量责任主体"],
    },
    {
        "code": "acceptance_archive_document",
        "name": "验收与归档资料责任主体",
        "document_examples": ["并网验收资料", "调试记录", "竣工资料", "运维交接资料"],
        "acceptable_signers": ["验收责任主体", "运维交接责任主体"],
    },
)

PRE_ENGINEERING_SITE_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "code": "site-roof-a",
        "name": "C3-A 候选屋顶",
        "site_type": "roof",
        "area_sqm": 5200,
        "property_status": "产权资料可核验，业主接受附条件合作",
        "nearby_grid_condition": "低压接入点近，但需确认容量和消纳",
        "estimated_capacity_kw": 520,
        "estimated_monthly_rent": "18000.00",
        "risk_points": ["屋顶荷载必须复核", "租赁协议必须绑定并网和结构条件"],
        "grid_prescreen": "conditional_pass",
        "legal_review": "conditional_pass",
    },
    {
        "code": "site-roof-b",
        "name": "C3-B 老厂房屋顶",
        "site_type": "roof",
        "area_sqm": 4300,
        "property_status": "产权链条较长，需要补充授权文件",
        "nearby_grid_condition": "接入点距离适中，但增容成本不确定",
        "estimated_capacity_kw": 390,
        "estimated_monthly_rent": "12000.00",
        "risk_points": ["产权授权不清", "屋面年限较长"],
        "grid_prescreen": "needs_follow_up",
        "legal_review": "blocked",
    },
    {
        "code": "site-ground-c",
        "name": "C3-C 空置地块",
        "site_type": "ground",
        "area_sqm": 8600,
        "property_status": "用途与建设边界不清",
        "nearby_grid_condition": "接入点远，线缆和增容成本高",
        "estimated_capacity_kw": 600,
        "estimated_monthly_rent": "9000.00",
        "risk_points": ["用地合规风险", "接入距离过远"],
        "grid_prescreen": "rejected",
        "legal_review": "blocked",
    },
)

PRE_ENGINEERING_MILESTONES: tuple[dict[str, object], ...] = (
    {
        "code": "candidate_site_pool",
        "name": "候选场地池",
        "complete_after_hours": 0,
        "description": "先形成多个候选场地，不立即租赁。",
    },
    {
        "code": "grid_prescreen",
        "name": "并网预筛与接入风险判断",
        "complete_after_hours": 24,
        "description": "租赁前判断接入点、容量、消纳和增容风险。",
    },
    {
        "code": "legal_conditional_lease_review",
        "name": "场地合法性与附条件租赁审查",
        "complete_after_hours": 48,
        "description": "确认产权、用途、租期和失败退出条件。",
    },
    {
        "code": "structural_safety_document",
        "name": "结构/建筑安全责任文件取得",
        "complete_after_hours": 72,
        "document_code": "structural_safety_document",
        "description": "取得适用于当前场地和规模的结构安全书面结论。",
    },
    {
        "code": "pv_system_design_document",
        "name": "光伏系统设计责任文件取得",
        "complete_after_hours": 96,
        "document_code": "pv_system_design_document",
        "description": "取得组件布置、逆变器配置、设备清单和发电测算等设计文件。",
    },
    {
        "code": "electrical_grid_document",
        "name": "电气接入与并网责任文件取得",
        "complete_after_hours": 120,
        "document_code": "electrical_grid_document",
        "description": "取得电气接入、保护配置、防雷接地和并网材料责任文件。",
    },
    {
        "code": "construction_safety_quality_document",
        "name": "施工安全与质量责任主体确认",
        "complete_after_hours": 144,
        "document_code": "construction_safety_quality_document",
        "description": "确认施工组织、安全质量和隐蔽工程记录责任主体。",
    },
    {
        "code": "acceptance_archive_document",
        "name": "验收、调试、归档责任安排",
        "complete_after_hours": 168,
        "document_code": "acceptance_archive_document",
        "description": "形成并网验收、调试、竣工和运维交接资料责任安排。",
    },
)


def run_zero_start_recruitment_simulation(*, hours: int = 168, ensure_seed: bool = True) -> dict[str, object]:
    """Run the first zero-start slice from one founder through application screening.

    The slice starts from project self-media exposure and explicit applications.
    It separates two startup gates: members with practical capabilities, and
    document signers who can issue written, accountable project documents.
    """

    if hours <= 0:
        raise ValueError("hours must be greater than 0.")
    if ensure_seed:
        seed_zero_start()
    revision = _zero_start_revision()
    existing_run = _continuable_zero_start_run()
    return _run_zero_start(revision=revision, hours=hours, run=existing_run)


def _zero_start_revision() -> PlanRevision:
    plan = ProjectPlan.objects.get(plan_id=ZERO_START_PLAN_ID)
    revision = (
        plan.revisions.filter(status=PlanRevision.Status.PUBLISHED)
        .order_by("-published_at", "-created_at", "revision_code")
        .first()
    )
    if revision is not None:
        return revision
    return PlanRevision.objects.get(revision_id=ZERO_START_REVISION_ID)


def _continuable_zero_start_run() -> SimulationRun | None:
    resolved_run_ids = _resolved_zero_start_run_ids()
    running_run = (
        SimulationRun.objects.filter(status=SimulationRun.Status.RUNNING, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")
        .first()
    )
    if running_run is not None:
        return running_run
    candidate_runs = (
        SimulationRun.objects.filter(status=SimulationRun.Status.FAILED, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")[:20]
    )
    for run in candidate_runs:
        if run.run_id not in resolved_run_ids and is_continuable_zero_start_observation_run(run):
            return run
    return None


def _resolved_zero_start_run_ids() -> set[str]:
    world_id = _current_world_id()
    if not world_id:
        return set()
    disposed_run_ids = set(
        SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world_id)
        .values_list("source_run_id", flat=True)
    )
    archived_run_ids = set(
        SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world_id)
        .values_list("source_run_id", flat=True)
    )
    return disposed_run_ids | archived_run_ids


@atomic_for_model(SimulationRun)
def _run_zero_start(*, revision: PlanRevision, hours: int, run: SimulationRun | None = None) -> dict[str, object]:
    now = timezone.now()
    founder = Member.objects.get(member_no=ZERO_START_FOUNDER_MEMBER_NO)
    if run is None:
        run = SimulationRun.objects.create(
            run_id=generate_simulation_run_id(),
            plan_revision=revision,
            status=SimulationRun.Status.RUNNING,
            current_day=1,
            max_turns=hours,
            started_at=now,
            ended_at=None,
            failure_summary="",
            metadata={
                "scenario": "zero_start",
                "clock_unit": "hour",
                "current_hour": -1,
                "project_phase": "preparation",
                "founder_member_no": founder.member_no,
                "initial_members": 1,
                "registered_applicants": 0,
                "candidate_members": 0,
                "screened_applicants": 0,
                "partner_applications": 0,
                "startup_gate_satisfied": False,
                "startup_capability_requirements": list(STARTUP_CAPABILITY_REQUIREMENTS),
                "startup_document_signer_requirements": list(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS),
            },
        )
    else:
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.max_turns = _metadata_int(run.metadata, "current_hour", -1) + 1 + hours
        run.save(update_fields=["status", "ended_at", "max_turns"])

    world_id = _current_world_id()
    form_driver = HttpFormDriver()
    start_hour = _metadata_int(run.metadata, "current_hour", -1) + 1
    end_hour = start_hour + hours
    applicant_specs = _applicant_specs_for_hours(end_hour)
    partner_specs = _partner_specs_for_hours(end_hour)
    applications_by_index: dict[int, MemberApplication] = {}
    partner_applications_by_index: dict[int, PartnerApplication] = {}
    for hour in range(start_hour, end_hour):
        applied = [spec for spec in applicant_specs if spec.apply_hour == hour]
        screened = [spec for spec in applicant_specs if spec.screen_hour == hour]
        partner_applied = [spec for spec in partner_specs if spec.apply_hour == hour]
        partner_screened = [spec for spec in partner_specs if spec.screen_hour == hour]
        for spec in applied:
            result = _submit_member_application_via_form(
                driver=form_driver,
                world_id=world_id,
                run=run,
                spec=spec,
                hour=hour,
            )
            if not result.success:
                return _fail_zero_start_form_interaction(run=run, hour=hour, result=result)
            applications_by_index[spec.index] = MemberApplication.objects.get(application_id=result.application_id)
        for spec in partner_applied:
            result = _submit_partner_application_via_form(
                driver=form_driver,
                world_id=world_id,
                run=run,
                spec=spec,
                hour=hour,
            )
            if not result.success:
                return _fail_zero_start_form_interaction(run=run, hour=hour, result=result)
            partner_applications_by_index[spec.index] = PartnerApplication.objects.get(application_id=result.application_id)
        screening_rows = []
        for spec in screened:
            application = applications_by_index.get(spec.index) or _member_application_for_run(run=run, spec=spec)
            try:
                screening_rows.append(_screen_member_application(application=application, spec=spec, screened_hour=hour))
            except DomainError as exc:
                return _fail_zero_start_form_interaction(
                    run=run,
                    hour=hour,
                    result=FormSubmissionResult(
                        success=False,
                        path="member_application_review",
                        status_code=0,
                        errors=[str(exc)],
                    ),
                )
        partner_screening_rows = []
        for spec in partner_screened:
            application = partner_applications_by_index.get(spec.index) or _partner_application_for_run(run=run, spec=spec)
            try:
                partner_screening_rows.append(
                    _screen_partner_application(application=application, spec=spec, screened_hour=hour)
                )
            except DomainError as exc:
                return _fail_zero_start_form_interaction(
                    run=run,
                    hour=hour,
                    result=FormSubmissionResult(
                        success=False,
                        path="partner_application_review",
                        status_code=0,
                        errors=[str(exc)],
                    ),
                )

        startup_gate = _startup_gate_summary(run)
        pre_engineering = _pre_engineering_state(run=run, hour=hour, startup_gate=startup_gate)
        candidate_summary = candidate_summary_for_run(run, startup_gate_satisfied=bool(startup_gate["startup_gate_satisfied"]))
        hour_payload = _hour_payload(
            run=run,
            hour=hour,
            applied=applied,
            partner_applied=partner_applied,
            screening_rows=screening_rows,
            partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary,
            startup_gate=startup_gate,
            pre_engineering=pre_engineering,
        )
        summary = _hour_summary(
            hour=hour,
            applied=applied,
            partner_applied=partner_applied,
            screening_rows=screening_rows,
            partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary,
            startup_gate=startup_gate,
            pre_engineering=pre_engineering,
        )
        create_simulation_turn_and_event(
            run=run,
            title=f"零起点第 {hour} 小时",
            summary=summary,
            simulation_day=_simulation_day(hour),
            severity=Event.Severity.INFO,
            event_type=Event.EventType.SIMULATION_DAY,
            payload=hour_payload,
        )
        run.current_day = _simulation_day(hour)
        run.metadata = {
            **run.metadata,
            "current_hour": hour,
            "startup_gate": startup_gate,
            "project_phase": pre_engineering.get("project_phase", startup_gate.get("project_phase", "preparation")),
            **candidate_summary,
        }
        if pre_engineering:
            run.metadata = {
                **run.metadata,
                "pre_engineering_started_hour": pre_engineering["started_hour"],
                "pre_engineering": pre_engineering,
            }
        run.save(update_fields=["current_day", "metadata"])

    gate = _startup_gate_summary(run)
    pre_engineering = _pre_engineering_state(run=run, hour=end_hour, startup_gate=gate)
    failure = None
    proposal = None
    change_set = None
    pre_engineering_complete = bool(pre_engineering.get("completed"))
    if gate["startup_gate_satisfied"] and pre_engineering_complete:
        run.status = SimulationRun.Status.COMPLETED
        run.ended_at = timezone.now()
        run.failure_summary = ""
    elif gate["startup_gate_satisfied"]:
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.failure_summary = "启动门槛已满足，工程前置流程仍在推进。"
    else:
        failure = _create_zero_start_failure(run=run, detected_hour=end_hour)
        proposal, change_set = _get_or_create_zero_start_feedback(run=run, failure=failure)
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.failure_summary = "启动门槛未满足，继续筹备和招募。"
    run.metadata = {
        **run.metadata,
        "completed_hours": end_hour,
        "observation_window_hours": hours,
        "can_continue": not (gate["startup_gate_satisfied"] and pre_engineering_complete),
        "failure_id": failure.failure_id if failure else "",
        "proposal_id": proposal.proposal_id if proposal else "",
        "change_set_id": change_set.change_set_id if change_set else "",
        "startup_gate_satisfied": gate["startup_gate_satisfied"],
        "startup_gate": gate,
        "project_phase": pre_engineering.get("project_phase", gate.get("project_phase", "preparation")),
    }
    if pre_engineering:
        run.metadata = {
            **run.metadata,
            "pre_engineering_started_hour": pre_engineering["started_hour"],
            "pre_engineering": pre_engineering,
        }
    run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title=_observation_window_title(gate=gate, pre_engineering=pre_engineering),
        summary=_observation_window_summary(gate=gate, pre_engineering=pre_engineering),
        simulation_day=_simulation_day(end_hour),
        severity=Event.Severity.INFO if (gate["startup_gate_satisfied"] and pre_engineering_complete) else Event.Severity.WARNING,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={
            "scenario": "zero_start",
            "simulation_hour": end_hour,
            "failure_id": failure.failure_id if failure else "",
            "can_continue": not (gate["startup_gate_satisfied"] and pre_engineering_complete),
            "startup_gate": gate,
            "pre_engineering": pre_engineering,
            "candidate_summary": candidate_summary_for_run(run, startup_gate_satisfied=bool(gate["startup_gate_satisfied"])),
            "blockers": _startup_gate_blockers(gate),
            "next_actions": _combined_next_actions(gate, pre_engineering),
        },
    )
    return {"run": run, "failure": failure, "proposal": proposal, "change_set": change_set}


def _current_world_id() -> str:
    world = get_current_world()
    if world is None:
        return "simulation0001"
    return world.world_id


def _metadata_int(metadata: dict[str, object], key: str, default: int) -> int:
    try:
        return int(metadata.get(key, default))
    except (TypeError, ValueError):
        return default


def _availability_slots_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["any_time"]
    if spec.availability_hours_per_week >= 8:
        return ["off_hours", "weekend"]
    return ["weekend"]


def _role_gap_for_spec(spec: ApplicantSpec) -> str:
    capability_names = " ".join(spec.capability_scores.keys())
    if any(keyword in capability_names for keyword in ("文档", "表格", "光伏", "结构")):
        return "developer_ai_engineer"
    if any(keyword in capability_names for keyword in ("搬运", "现场", "安全", "采购")):
        return "service_resident"
    return "community_contributor"


def _motivation_reasons_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["build_community"]
    capability_names = " ".join(spec.capability_scores.keys())
    if any(keyword in capability_names for keyword in ("文档", "表格", "光伏", "结构")):
        return ["remote_system_work", "learn_and_practice"]
    if spec.availability_hours_per_week <= 2:
        return ["safe_stable_place"]
    return ["build_community", "other"]


def _submit_member_application_via_form(
    *,
    driver: HttpFormDriver,
    world_id: str,
    run: SimulationRun,
    spec: ApplicantSpec,
    hour: int,
) -> FormSubmissionResult:
    applicant_username = f"applicant-{run.run_id[-6:]}-{spec.index:03d}"
    return driver.submit_member_application(
        world_id=world_id,
        run_id=run.run_id,
        simulation_hour=hour,
        external_ref=f"{run.run_id}:member:{spec.index}",
        data={
            "username": applicant_username,
            "password1": f"simulation-{run.run_id[-6:]}-{spec.index:03d}",
            "password2": f"simulation-{run.run_id[-6:]}-{spec.index:03d}",
            "applicant_name": spec.display_name,
            "contact": f"applicant-{spec.index:03d}@simulation.test",
            "motivation": spec.motivation,
            "availability_hours_per_week": spec.availability_hours_per_week,
            "role_gap": _role_gap_for_spec(spec),
            "availability_slots": _availability_slots_for_spec(spec),
            "motivation_reasons": _motivation_reasons_for_spec(spec),
            "motivation_other_text": spec.motivation,
            "capabilities_text": "\n".join(f"{name}:{score}" for name, score in spec.capability_scores.items()),
            "requested_member_no": applicant_username,
            "confirm_submit": "on",
        },
    )


def _submit_partner_application_via_form(
    *,
    driver: HttpFormDriver,
    world_id: str,
    run: SimulationRun,
    spec: PartnerSpec,
    hour: int,
) -> FormSubmissionResult:
    return driver.submit_partner_application(
        world_id=world_id,
        run_id=run.run_id,
        simulation_hour=hour,
        external_ref=f"{run.run_id}:partner:{spec.index}",
        data={
            "organization_name": spec.organization_name,
            "contact_name": spec.contact_name,
            "contact": f"partner-{spec.index:03d}@simulation.test",
            "service_domains_text": "\n".join(spec.service_domains),
            "can_issue_responsibility_documents": "on" if spec.can_issue_responsibility_documents else "",
            "responsibility_document_domains_text": "\n".join(spec.responsibility_document_domains),
            "qualification_summary": spec.qualification_summary,
            "quote_summary": spec.quote_summary,
            "service_area": spec.service_area,
            "delivery_cycle_days": spec.delivery_cycle_days if spec.delivery_cycle_days is not None else "",
            "constraints": spec.constraints,
        },
    )


def _member_application_for_run(*, run: SimulationRun, spec: ApplicantSpec) -> MemberApplication:
    return MemberApplication.objects.get(metadata__external_ref=f"{run.run_id}:member:{spec.index}")


def _partner_application_for_run(*, run: SimulationRun, spec: PartnerSpec) -> PartnerApplication:
    return PartnerApplication.objects.get(metadata__external_ref=f"{run.run_id}:partner:{spec.index}")


def _screen_member_application(
    *,
    application: MemberApplication,
    spec: ApplicantSpec,
    screened_hour: int,
) -> dict[str, object]:
    decision = _screening_decision(spec=spec, screened_hour=screened_hour)
    if decision == APPLICATION_STATUS_CANDIDATE:
        note = "进入候选池：具备可用能力或较高到场时间，但不等于具备文件签署责任。"
    elif decision == APPLICATION_STATUS_STANDBY:
        note = "进入备用池：兴趣明确，但可用时间或能力匹配度不足。"
    elif decision == APPLICATION_STATUS_WITHDREW:
        note = "报名者在筛选截止前主动退出。"
    else:
        note = "项目方暂不接纳：当前能力和可用时间不足以进入候选池。"
    history = list(application.metadata.get("state_history") or [])
    history.append({"hour": screened_hour, "status": decision, "reason": note})
    # Simulation screening decisions are recorded in metadata only --
    # they do NOT mutate MemberApplication.status. The authoritative
    # application status is driven by the member_admission proposal
    # lifecycle (admission_voting → admitted / rejected).
    application.metadata = {
        **application.metadata,
        "batch_id": f"zero-start-{str(application.metadata.get('simulation_run_id', ''))[-6:]}",
        "application_status": decision,
        "screening_status": decision,
        "screened_hour": screened_hour,
        "screening_notes": note,
        "state_history": history,
        "review_note": note,
    }
    application.save(update_fields=["metadata"])
    if application.linked_member_id:
        member = application.linked_member
        member.metadata = {
            **member.metadata,
            "scenario": "zero_start",
            "simulation_run_id": application.metadata.get("simulation_run_id"),
            "applicant_index": spec.index,
            "applied_hour": spec.apply_hour,
            "application_source": "self_media",
            "application_status": decision,
            "screening_status": decision,
            "screened_hour": screened_hour,
            "screening_notes": note,
            "state_history": history,
        }
        member.save(update_fields=["metadata"])
    return {
        "application_id": application.application_id,
        "member_no": application.linked_member.member_no if application.linked_member_id else "",
        "display_name": application.applicant_name,
        "decision": decision,
        "availability_hours_per_week": spec.availability_hours_per_week,
        "capability_scores": spec.capability_scores,
        "document_authority_domains": list(spec.document_authority_domains),
    }


def _screen_partner_application(
    *,
    application: PartnerApplication,
    spec: PartnerSpec,
    screened_hour: int,
) -> dict[str, object]:
    if spec.review_status == PartnerApplication.Status.QUALIFIED and spec.can_issue_responsibility_documents:
        note = "合作方已初筛为可合作：具备责任文件签署能力；后续仍需以具体合同和正式文件固化责任。"
    elif spec.review_status == PartnerApplication.Status.QUALIFIED:
        note = "合作方已初筛为可合作：可提供服务能力，但不承担责任文件签署。"
    else:
        note = "合作方已初筛进入线索池：可作为辅助能力或报价来源，不能直接视为关键责任文件到位。"
    review_partner_application(application=application, status=spec.review_status, review_note=note)
    application.refresh_from_db()
    history = list(application.metadata.get("state_history") or [])
    history.append({"hour": screened_hour, "status": spec.review_status, "reason": note})
    application.metadata = {
        **application.metadata,
        "application_status": spec.review_status,
        "screening_status": spec.review_status,
        "screened_hour": screened_hour,
        "screening_notes": note,
        "state_history": history,
    }
    application.save(update_fields=["metadata"])
    return {
        "application_id": application.application_id,
        "organization_name": application.organization_name,
        "decision": spec.review_status,
        "service_domains": list(spec.service_domains),
        "responsibility_document_domains": list(spec.responsibility_document_domains),
        "can_issue_responsibility_documents": spec.can_issue_responsibility_documents,
    }


def _hour_payload(
    *,
    run: SimulationRun,
    hour: int,
    applied: list[ApplicantSpec],
    partner_applied: list[PartnerSpec],
    screening_rows: list[dict[str, object]],
    partner_screening_rows: list[dict[str, object]],
    candidate_summary: dict[str, int | bool],
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
) -> dict[str, object]:
    payload = {
        "scenario": "zero_start",
        "simulation_hour": hour,
        "virtual_time": {
            "hour": hour,
            "day": _simulation_day(hour),
            "hour_of_day": hour % 24,
        },
        "project_phase": pre_engineering.get("project_phase", startup_gate.get("project_phase", "preparation")),
        "state_machine": "zero_start_recruitment_screening"
        if not pre_engineering
        else "zero_start_recruitment_and_pre_engineering",
        "driver_mode": HttpFormDriver.mode,
        "applicants_applied": [spec.index for spec in applied],
        "partners_applied": [spec.index for spec in partner_applied],
        "screening_results": screening_rows,
        "partner_screening_results": partner_screening_rows,
        "funnel_delta": {
            "new_member_applications": len(applied),
            "new_partner_applications": len(partner_applied),
            "member_screened": len(screening_rows),
            "partner_screened": len(partner_screening_rows),
            "member_candidates": len([row for row in screening_rows if row.get("decision") == APPLICATION_STATUS_CANDIDATE]),
            "partner_qualified": len(
                [row for row in partner_screening_rows if row.get("decision") == PartnerApplication.Status.QUALIFIED]
            ),
        },
        "candidate_summary": candidate_summary,
        "startup_gate": startup_gate,
        "blockers": _startup_gate_blockers(startup_gate),
        "next_actions": _combined_next_actions(startup_gate, pre_engineering),
    }
    if pre_engineering:
        payload["pre_engineering"] = pre_engineering
    return payload


def _hour_summary(
    *,
    hour: int,
    applied: list[ApplicantSpec],
    partner_applied: list[PartnerSpec],
    screening_rows: list[dict[str, object]],
    partner_screening_rows: list[dict[str, object]],
    candidate_summary: dict[str, int | bool],
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
) -> str:
    phrases = [
        (
            f"第 {hour} 小时：发起人继续通过自媒体说明大苹果计划，"
            f"累计主动报名 {candidate_summary['registered_applicants']} 人，"
            f"进入候选池 {candidate_summary['candidate_members']} 人，"
            f"合作方报名 {candidate_summary['partner_applications']} 个，"
            f"合格责任合作方 {candidate_summary['qualified_partners']} 个。"
        ),
    ]
    if hour == 0:
        phrases.append("项目仍处于真正的零起点：只有一个发起人，没有成熟成员池、资源和工程计划。")
    for spec in applied:
        phrases.append(f"{spec.display_name} 提交报名：{spec.motivation}")
    for spec in partner_applied:
        phrases.append(f"{spec.organization_name} 提交合作方报名：{spec.qualification_summary}")
    for row in screening_rows:
        phrases.append(f"{row['display_name']} 完成初筛，结论：{row['decision']}。")
    for row in partner_screening_rows:
        phrases.append(f"{row['organization_name']} 完成合作方初筛，结论：{row['decision']}。")
    if hour % 24 == 0 and hour > 0:
        phrases.append(
            "阶段复盘：报名数量不是启动条件，必须同时满足成员能力矩阵和文件签署方矩阵。"
        )
    if startup_gate["missing_capabilities"]:
        phrases.append(f"能力缺口：{startup_gate['missing_capabilities'][0]['name']}。")
    if startup_gate["missing_document_signers"]:
        phrases.append(f"文件责任缺口：{startup_gate['missing_document_signers'][0]['name']}。")
    if startup_gate["startup_gate_satisfied"]:
        phrases.append("启动门槛已经满足：成员能力矩阵和责任文件签署方矩阵均已覆盖。")
    if pre_engineering:
        phrases.append(_pre_engineering_hour_summary(pre_engineering))
    return " ".join(phrases)


def _startup_gate_blockers(startup_gate: dict[str, object]) -> list[dict[str, str]]:
    blockers = [
        {
            "kind": "capability",
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
        }
        for row in startup_gate.get("missing_capabilities", [])
    ]
    blockers.extend(
        {
            "kind": "document_signer",
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
        }
        for row in startup_gate.get("missing_document_signers", [])
    )
    return blockers


def _startup_gate_next_actions(startup_gate: dict[str, object]) -> list[str]:
    if startup_gate.get("startup_gate_satisfied"):
        return ["启动门槛满足，进入候选场地、并网预筛和工程责任文件前置审查。"]
    actions = []
    if startup_gate.get("missing_capabilities"):
        actions.append("继续通过自媒体报名和筛选补齐成员能力矩阵。")
    if startup_gate.get("missing_document_signers"):
        actions.append("继续开放合作方报名，重点寻找可出具书面责任文件的主体。")
    return actions or ["继续观察报名质量和合作方资质变化。"]


def _pre_engineering_state(
    *,
    run: SimulationRun,
    hour: int,
    startup_gate: dict[str, object],
) -> dict[str, object]:
    if not startup_gate.get("startup_gate_satisfied"):
        return {}
    started_hour = _metadata_int(run.metadata, "pre_engineering_started_hour", hour)
    elapsed_hours = max(hour - started_hour, 0)
    milestones = [
        _pre_engineering_milestone_row(run=run, milestone=milestone, elapsed_hours=elapsed_hours)
        for milestone in PRE_ENGINEERING_MILESTONES
    ]
    completed = all(bool(row["completed"]) for row in milestones)
    selected_site = _selected_site_candidate(elapsed_hours)
    return {
        "project_phase": "pre_engineering_completed" if completed else "pre_engineering",
        "status": "completed" if completed else "running",
        "completed": completed,
        "started_hour": started_hour,
        "elapsed_hours": elapsed_hours,
        "selected_site_code": selected_site["code"] if selected_site else "",
        "candidate_sites": _candidate_site_rows(elapsed_hours),
        "milestones": milestones,
        "completed_milestone_count": len([row for row in milestones if row["completed"]]),
        "pending_milestone_count": len([row for row in milestones if not row["completed"]]),
        "blockers": _pre_engineering_blockers(milestones),
        "next_actions": _pre_engineering_next_actions(milestones),
    }


def _pre_engineering_milestone_row(
    *,
    run: SimulationRun,
    milestone: dict[str, object],
    elapsed_hours: int,
) -> dict[str, object]:
    completed = elapsed_hours >= int(milestone["complete_after_hours"])
    document_code = str(milestone.get("document_code") or "")
    signer = _document_signer_for_code(run=run, document_code=document_code) if document_code else {}
    return {
        "code": milestone["code"],
        "name": milestone["name"],
        "description": milestone["description"],
        "complete_after_hours": milestone["complete_after_hours"],
        "completed": completed,
        "status": "completed" if completed else "pending",
        "document_code": document_code,
        "covered_by": signer if completed and signer else {},
    }


def _document_signer_for_code(*, run: SimulationRun, document_code: str) -> dict[str, object]:
    if not document_code:
        return {}
    partners = (
        PartnerApplication.objects.filter(
            metadata__simulation_run_id=run.run_id,
            status=PartnerApplication.Status.QUALIFIED,
            can_issue_responsibility_documents=True,
        ).order_by("application_id")
    )
    for partner in partners:
        if document_code in (partner.responsibility_document_domains or []):
            return partner_snapshot(partner)
    return {}


def _candidate_site_rows(elapsed_hours: int) -> list[dict[str, object]]:
    rows = []
    grid_visible = elapsed_hours >= 24
    legal_visible = elapsed_hours >= 48
    for site in PRE_ENGINEERING_SITE_CANDIDATES:
        grid_status = str(site["grid_prescreen"]) if grid_visible else "pending"
        legal_status = str(site["legal_review"]) if legal_visible else "pending"
        shortlisted = grid_status in {"conditional_pass", "needs_follow_up"} and legal_status == "conditional_pass"
        rows.append(
            {
                "code": site["code"],
                "name": site["name"],
                "site_type": site["site_type"],
                "area_sqm": site["area_sqm"],
                "property_status": site["property_status"],
                "nearby_grid_condition": site["nearby_grid_condition"],
                "estimated_capacity_kw": site["estimated_capacity_kw"],
                "estimated_monthly_rent": site["estimated_monthly_rent"],
                "risk_points": site["risk_points"],
                "grid_prescreen_status": grid_status,
                "legal_review_status": legal_status,
                "shortlisted": shortlisted,
            }
        )
    return rows


def _selected_site_candidate(elapsed_hours: int) -> dict[str, object] | None:
    if elapsed_hours < 48:
        return None
    for row in _candidate_site_rows(elapsed_hours):
        if row["shortlisted"]:
            return row
    return None


def _pre_engineering_blockers(milestones: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "kind": "pre_engineering",
            "code": str(row["code"]),
            "name": str(row["name"]),
        }
        for row in milestones
        if not row["completed"]
    ]


def _pre_engineering_next_actions(milestones: list[dict[str, object]]) -> list[str]:
    for row in milestones:
        if not row["completed"]:
            return [f"继续推进：{row['name']}。"]
    return ["工程前置责任闭环已形成，可以进入采购、施工、调试和验收计划细化。"]


def _combined_next_actions(startup_gate: dict[str, object], pre_engineering: dict[str, object]) -> list[str]:
    if not startup_gate.get("startup_gate_satisfied"):
        return _startup_gate_next_actions(startup_gate)
    if pre_engineering:
        return list(pre_engineering.get("next_actions") or [])
    return _startup_gate_next_actions(startup_gate)


def _pre_engineering_hour_summary(pre_engineering: dict[str, object]) -> str:
    if pre_engineering.get("status") == "completed":
        selected_site = pre_engineering.get("selected_site_code") or "候选场地"
        return f"工程前置阶段完成：{selected_site} 已通过预筛、附条件租赁审查和责任文件闭环。"
    blockers = pre_engineering.get("blockers") or []
    if blockers:
        return f"工程前置阶段推进中，下一项未完成：{blockers[0]['name']}。"
    return "工程前置阶段推进中。"


def _observation_window_title(*, gate: dict[str, object], pre_engineering: dict[str, object]) -> str:
    if not gate.get("startup_gate_satisfied"):
        return "零起点报名筛选观察窗口结束"
    if pre_engineering.get("completed"):
        return "工程前置责任闭环观察窗口结束"
    return "工程前置流程观察窗口结束"


def _observation_window_summary(*, gate: dict[str, object], pre_engineering: dict[str, object]) -> str:
    if not gate.get("startup_gate_satisfied"):
        return (
            "本观察窗口已结束。若成员能力矩阵和文件签署方矩阵仍未满足，"
            "项目继续停留在筹备阶段，可以继续向后推进招募和合作方报名。"
        )
    if pre_engineering.get("completed"):
        return (
            "启动门槛和工程前置责任闭环均已满足。仿真已形成从报名筛选到候选场地、"
            "并网预筛、附条件租赁和责任文件取得的完整链条。"
        )
    return (
        "启动门槛已满足，但候选场地、并网预筛、附条件租赁或工程责任文件仍在推进，"
        "本轮可以继续向后模拟。"
    )


def _screening_decision(*, spec: ApplicantSpec, screened_hour: int) -> str:
    if spec.withdraw_hour is not None and screened_hour >= spec.withdraw_hour:
        return APPLICATION_STATUS_WITHDREW
    matches_startup_capability = any(
        skills_match_requirement(spec.capability_scores, requirement)
        for requirement in STARTUP_CAPABILITY_REQUIREMENTS
    )
    if spec.availability_hours_per_week >= 8 and matches_startup_capability:
        return APPLICATION_STATUS_CANDIDATE
    if spec.availability_hours_per_week >= 4 or matches_startup_capability:
        return APPLICATION_STATUS_STANDBY
    return APPLICATION_STATUS_REJECTED


def _startup_gate_summary(run: SimulationRun) -> dict[str, object]:
    return startup_gate_summary_for_run(
        run,
        founder_member_no=ZERO_START_FOUNDER_MEMBER_NO,
        capability_requirements=STARTUP_CAPABILITY_REQUIREMENTS,
        responsibility_document_requirements=STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
    )


def _fail_zero_start_form_interaction(
    *,
    run: SimulationRun,
    hour: int,
    result: FormSubmissionResult,
) -> dict[str, object]:
    now = timezone.now()
    failure = SimulationFailure.objects.create(
        failure_id=generate_simulation_failure_id(),
        run=run,
        plan_node=None,
        failure_type=SimulationFailure.FailureType.EXECUTION_ISSUE,
        severity=SimulationFailure.Severity.CRITICAL,
        title="零起点仿真表单交互失败",
        description=(
            "虚拟主体通过真实报名入口提交数据时失败。"
            "这说明当前系统入口、表单字段、校验或保存链路无法支撑本轮仿真。"
        ),
        simulation_day=_simulation_day(hour),
        detected_at=now,
        metadata={
            "scenario": "zero_start",
            "simulation_hour": hour,
            "path": result.path,
            "status_code": result.status_code,
            "errors": result.errors,
            "failure_kind": "system_form_interaction_failed",
        },
    )
    run.status = SimulationRun.Status.FAILED
    run.ended_at = now
    run.failure_summary = failure.title
    run.metadata = {
        **run.metadata,
        "completed_hours": hour,
        "failure_id": failure.failure_id,
        "system_interaction_failed": True,
        "system_interaction_errors": result.errors,
    }
    run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title="真实报名表单交互失败",
        summary="虚拟主体访问或提交真实报名页面失败，本轮仿真停止。",
        simulation_day=_simulation_day(hour),
        severity=Event.Severity.CRITICAL,
        event_type=Event.EventType.RANDOM_INCIDENT,
        payload={
            "scenario": "zero_start",
            "simulation_hour": hour,
            "failure_id": failure.failure_id,
            "path": result.path,
            "status_code": result.status_code,
            "errors": result.errors,
        },
    )
    return {"run": run, "failure": failure, "proposal": None, "change_set": None}


def _create_zero_start_failure(*, run: SimulationRun, detected_hour: int) -> SimulationFailure:
    gate = _startup_gate_summary(run)
    return SimulationFailure.objects.create(
        failure_id=generate_simulation_failure_id(),
        run=run,
        plan_node=None,
        failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
        severity=SimulationFailure.Severity.CRITICAL,
        title="Z0 自媒体报名筛选后仍未达到启动门槛",
        description=(
            "本轮从一个发起人开始，自媒体曝光带来了一批明确想参加的报名者，"
            "但初始成员能力矩阵尚未补齐，结构、光伏、电气、施工和验收等文件签署方也未到位。"
            "项目仍处于筹备阶段，不能进入真实启动。"
        ),
        simulation_day=_simulation_day(detected_hour),
        detected_at=timezone.now(),
        metadata={
            "scenario": "zero_start",
            "simulation_hour": detected_hour,
            "project_phase": "preparation",
            "startup_gate_satisfied": gate["startup_gate_satisfied"],
            "required_initial_capabilities": list(STARTUP_CAPABILITY_REQUIREMENTS),
            "required_document_signers": list(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS),
            "capability_coverage": gate["capability_coverage"],
            "document_signer_coverage": gate["document_signer_coverage"],
            "missing_capabilities": gate["missing_capabilities"],
            "missing_document_signers": gate["missing_document_signers"],
            "cannot_continue_reasons": [
                "报名者想参加不等于项目已具备启动所需的稳定能力结构。",
                "做饭、文档、采购、后勤等能力可以由成员承担，但需要签字或出具文件的事项必须有对应签署方。",
                "结构、光伏、电气、施工安全、验收归档等文件责任尚未形成可追溯主体。",
            ],
            "recommended_actions": [
                "把自媒体报名、初筛、候选池和退出记录继续细化为小时级状态机。",
                "建立前 N 名成员能力矩阵，明确每种能力需要多少人到位。",
                "建立合作伙伴和文件签署方矩阵，明确哪些事项必须获得书面文件。",
                "所有启动前置门槛满足前，项目只能停留在筹备阶段。",
            ],
        },
    )


def _get_or_create_zero_start_feedback(
    *,
    run: SimulationRun,
    failure: SimulationFailure,
) -> tuple[PlanRevisionProposal | None, PlanChangeSet | None]:
    existing_change_set = (
        PlanChangeSet.objects.select_related("proposal")
        .filter(
            run=run,
            status=PlanChangeSet.Status.DRAFT,
            metadata__scenario="zero_start",
            title__contains="启动门槛",
        )
        .order_by("-created_at", "-change_set_id")
        .first()
    )
    if existing_change_set is not None:
        return existing_change_set.proposal, existing_change_set
    if _plan_revision_has_zero_start_gate(run.plan_revision):
        return None, None
    return _create_zero_start_feedback(run=run, failure=failure)


def _plan_revision_has_zero_start_gate(revision: PlanRevision) -> bool:
    return PlanNode.objects.filter(revision=revision, code="Z0").exists()


def _create_zero_start_feedback(
    *,
    run: SimulationRun,
    failure: SimulationFailure,
) -> tuple[PlanRevisionProposal, PlanChangeSet]:
    now = timezone.now()
    revision = run.plan_revision
    proposal = PlanRevisionProposal.objects.create(
        proposal_id=generate_plan_revision_proposal_id(),
        run=run,
        source_failure=failure,
        plan_revision=revision,
        plan_node=None,
        proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
        status=PlanRevisionProposal.Status.DRAFT,
        title="增加自媒体报名筛选与启动门槛矩阵",
        rationale=(
            "从零起点推演发现：主动报名不等于项目可以启动。"
            "后续计划必须先确认前 N 名成员能力矩阵，以及需要书面文件的合作伙伴和签署方矩阵。"
        ),
        suggested_changes={
            "add_stage": "Z0 自媒体报名筛选与启动门槛确认",
            "application_state_machine": [
                APPLICATION_STATUS_REGISTERED,
                APPLICATION_STATUS_CANDIDATE,
                APPLICATION_STATUS_STANDBY,
                APPLICATION_STATUS_REJECTED,
                APPLICATION_STATUS_WITHDREW,
            ],
            "required_screening_dimensions": [
                "参与动机",
                "可用时间",
                "到场可能性",
                "自述技能",
                "可验证经历",
                "项目是否接纳为候选人",
                "是否主动退出",
            ],
            "startup_capability_requirements": list(STARTUP_CAPABILITY_REQUIREMENTS),
            "startup_document_signer_requirements": list(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS),
            "requirement_semantics": {
                "capability": "需要人或合作方具备实际能力，不要求签字盖章文件。",
                "document": "需要可归档、可追责、可作为决策依据的书面文件和签署方。",
            },
        },
        created_at=now,
        metadata={"scenario": "zero_start"},
    )
    change_set = PlanChangeSet.objects.create(
        change_set_id=generate_plan_change_set_id(),
        run=run,
        proposal=proposal,
        plan_revision=revision,
        status=PlanChangeSet.Status.DRAFT,
        title="零起点启动门槛结构化变更",
        summary="新增 Z0 前置阶段，先形成报名状态机、成员能力矩阵和文件签署方矩阵，再进入成员抵达、食宿或工程计划。",
        created_at=now,
        metadata={"scenario": "zero_start"},
    )
    operations = [
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_NODE,
            "target_model": "PlanNode",
            "target_id": "",
            "rationale": "新增 Z0 自媒体报名筛选与启动门槛确认阶段。",
            "new_value": {
                "code": "Z0",
                "title": "自媒体报名筛选与启动门槛确认",
                "node_type": PlanNode.NodeType.RECRUITMENT,
                "description": (
                    "从发起人自媒体曝光开始，记录主动报名、初筛、候选、拒绝和退出，"
                    "并确认成员能力矩阵和文件签署方矩阵。"
                ),
                "planned_duration_days": 7,
                "estimated_cost_expected": "0.00",
                "required_people_min": 1,
                "required_people_max": 3,
                "required_person_days": "14.00",
                "required_skills": ["发起", "沟通", "文档", "报名筛选", "启动门槛识别"],
                "completion_criteria": [
                    "形成报名者状态机记录。",
                    "输出前 N 名成员能力矩阵。",
                    "输出合作伙伴和文件签署方矩阵。",
                    "明确项目仍处于筹备阶段或满足启动门槛。",
                ],
                "metadata": {
                    "scenario": "zero_start",
                    "project_phase": "preparation",
                    "application_source": "self_media",
                },
            },
        },
    ]
    for requirement in STARTUP_CAPABILITY_REQUIREMENTS:
        operations.append(
            {
                "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
                "target_model": "PlanRequirement",
                "target_id": "",
                "rationale": f"启动前必须确认具备能力：{requirement['name']}。",
                "metadata": {"scenario": "zero_start", "requirement_kind": "capability"},
                "new_value": {
                    "node_code": "Z0",
                    "requirement_type": PlanRequirement.RequirementType.SKILL,
                    "name": f"能力需求：{requirement['name']}",
                    "quantity": requirement["min_count"],
                    "unit": "人",
                    "unit_cost": "0.00",
                    "total_cost_estimate": "0.00",
                    "is_must": True,
                    "notes": "这是实际能力需求，不要求提供签字盖章文件。",
                    "metadata": {
                        "scenario": "zero_start",
                        "requirement_kind": "capability",
                        "capability_code": requirement["code"],
                        "skill_aliases": requirement["skill_aliases"],
                        "need_written_document": False,
                    },
                },
            }
        )
    for requirement in STARTUP_DOCUMENT_SIGNER_REQUIREMENTS:
        operations.append(
            {
                "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
                "target_model": "PlanRequirement",
                "target_id": "",
                "rationale": f"启动前必须确认文件签署方：{requirement['name']}。",
                "metadata": {"scenario": "zero_start", "requirement_kind": "document"},
                "new_value": {
                    "node_code": "Z0",
                    "requirement_type": PlanRequirement.RequirementType.PERMIT,
                    "name": f"文件责任：{requirement['name']}",
                    "quantity": 1,
                    "unit": "项",
                    "unit_cost": "0.00",
                    "total_cost_estimate": "0.00",
                    "is_must": True,
                    "notes": "这是文件责任需求，必须有可归档、可追责的书面文件和签署方。",
                    "metadata": {
                        "scenario": "zero_start",
                        "requirement_kind": "document",
                        "document_code": requirement["code"],
                        "document_examples": requirement["document_examples"],
                        "acceptable_signers": requirement["acceptable_signers"],
                        "need_written_document": True,
                    },
                },
            }
        )
    for index, operation in enumerate(operations, start=1):
        PlanChangeOperation.objects.create(
            operation_id=generate_plan_change_operation_id(),
            change_set=change_set,
            sequence=index,
            operation_type=operation["operation_type"],
            target_model=operation["target_model"],
            target_id=operation["target_id"],
            target_field="",
            old_value={},
            new_value=operation["new_value"],
            rationale=operation["rationale"],
            is_required=True,
            metadata=operation.get("metadata", {"scenario": "zero_start"}),
        )
    return proposal, change_set


def _simulation_day(hour: int) -> int:
    return hour // 24 + 1
