"""Zero-start simulation strategy / scenario configuration.

Dataclasses, virtual-applicant specs, screening windows, startup-gate
requirement constants, and the screening decision function.  This module
does NOT import ``zero_start.py`` so the engine can import it freely.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capability_matching import skills_match_requirement


# virtual-subject dataclasses


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


# fixed virtual-applicant pools


MEMBER_APPLICANTS: tuple[ApplicantSpec, ...] = (
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
        "review_status": "standby",
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
        "review_status": "qualified",
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
        "review_status": "qualified",
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
        "review_status": "qualified",
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
        "review_status": "qualified",
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
        "review_status": "qualified",
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
        "review_status": "standby",
    },
)


# screening-window generators


def applicant_specs_for_hours(hours: int) -> tuple[ApplicantSpec, ...]:
    specs = list(MEMBER_APPLICANTS)
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


def partner_specs_for_hours(hours: int) -> tuple[PartnerSpec, ...]:
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


# screening-status constants (shared with zero_start.py)


APPLICATION_STATUS_REGISTERED = "registered"
APPLICATION_STATUS_CANDIDATE = "candidate"
APPLICATION_STATUS_STANDBY = "standby"
APPLICATION_STATUS_REJECTED = "rejected"
APPLICATION_STATUS_WITHDREW = "withdrew"


# startup-gate requirement constants


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


# screening decision


def screening_decision(*, spec: ApplicantSpec, screened_hour: int) -> str:
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
