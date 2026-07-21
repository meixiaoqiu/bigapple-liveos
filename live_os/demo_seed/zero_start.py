"""Zero-start simulation seed data.

This template intentionally starts before a mature operation exists: one
founder, no candidate pool, no tasks, no resources, no candidate venues, no
SimulationRun/Turn — but it seeds a full-lifecycle ``PlanNode`` skeleton
(Z/A/B/C/D stages) so that ``/dashboard/mainline/`` shows the complete
roadmap after reset.  Only Z0 is ``IN_PROGRESS``; every other node is
``PLANNED``.
"""

from __future__ import annotations

from django.utils import timezone

from core.member_roles import (
    ROLE_BIG_APPLE_MEMBER,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    ensure_member_role,
    ensure_role_assignment,
)
from core.models import Member, PlanNode, PlanRevision, ProjectPlan

from .helpers import actor, upsert


ZERO_START_PLAN_ID = "plan-zero-start"
ZERO_START_REVISION_ID = "plan-zero-start-rev-v0_0_1"
ZERO_START_FOUNDER_MEMBER_NO = "founder-0001"


def seed_zero_start(*, founder_member_no: str = "", founder_display_name: str = "", now=None) -> dict[str, object]:
    """Seed the zero-start baseline with a full-lifecycle PlanNode skeleton.

    The world still has only one founder — no candidate pool, tasks,
    resources, venues, SimulationRuns, or Turns.  But it now includes
    25+ PlanNodes across Z / A / B / C / D stages so the mainline
    detail page renders the complete roadmap immediately after reset.
    Only Z0 is IN_PROGRESS; all other nodes are PLANNED.
    """

    now = now or timezone.now()
    founder_no = str(founder_member_no or "").strip() or ZERO_START_FOUNDER_MEMBER_NO
    founder_name = str(founder_display_name or "").strip() or (
        "大苹果发起人" if founder_no == ZERO_START_FOUNDER_MEMBER_NO else founder_no
    )
    founder, _ = upsert(
        Member,
        {"member_no": founder_no},
        {
            "display_name": founder_name,
            "status": Member.Status.ACTIVE,
            "batch_id": "zero-start",
            "joined_simulation_day": 0,
            "credit_floor": -500,
            "profile": {
                "public_spirit": 95,
                "rule_compliance": 90,
                "availability_hours_per_week": 50,
                "skills": {"发起": 90, "沟通": 82, "文档": 76, "组织": 70},
            },
            "created_at": now,
            "metadata": {
                "seed": True,
                "template": "zero_start",
                "note": "零起点仿真只预置一个发起人。",
            },
        },
    )
    ensure_role_assignment(founder, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
    ensure_role_assignment(founder, ensure_member_role(ROLE_FORMAL_MEMBER))
    ensure_role_assignment(founder, ensure_member_role(ROLE_GOVERNANCE_MEMBER))
    founder_actor_type = "human_member" if founder.user_id else "virtual_member"
    founder_actor = actor(founder.member_no, founder.display_name or founder.member_no, founder_actor_type)

    plan, _ = upsert(
        ProjectPlan,
        {"plan_id": ZERO_START_PLAN_ID},
        {
            "name": "大苹果零起点倡议",
            "status": ProjectPlan.Status.ACTIVE,
            "description": "从只有一个发起人开始，验证自媒体报名筛选、候选池、能力矩阵和文件签署方矩阵。",
            "target_location": "未确定",
            "owner": founder_actor,
            "created_at": now,
            "updated_at": now,
            "metadata": {"seed": True, "template": "zero_start"},
        },
    )
    revision_defaults = {
            "plan": plan,
            "revision_code": "v0.0.1-zero-start",
            "status": PlanRevision.Status.PUBLISHED,
            "title": "零起点仿真基线",
            "change_summary": "零起点基线：只有一个发起人，没有成员池/任务/资源/场地/SimulationRun。预置 Z/A/B/C/D 完整生命周期 PlanNode 骨架，当前仅激活 Z0。",
            "created_at": now,
            "created_by": founder_actor,
            "published_at": now,
            "metadata": {"seed": True, "template": "zero_start"},
    }
    revision, created = PlanRevision.objects.get_or_create(
        revision_id=ZERO_START_REVISION_ID,
        defaults=revision_defaults,
    )
    if not created:
        update_fields = []
        static_updates = {
            "plan": plan,
            "revision_code": "v0.0.1-zero-start",
            "title": "零起点仿真基线",
            "change_summary": "零起点基线：只有一个发起人，没有成员池/任务/资源/场地/SimulationRun。预置 Z/A/B/C/D 完整生命周期 PlanNode 骨架，当前仅激活 Z0。",
            "created_by": founder_actor,
            "metadata": {"seed": True, "template": "zero_start"},
        }
        for field, value in static_updates.items():
            if getattr(revision, field) != value:
                setattr(revision, field, value)
                update_fields.append(field)
        if not PlanRevision.objects.filter(plan=plan, status=PlanRevision.Status.PUBLISHED).exists():
            revision.status = PlanRevision.Status.PUBLISHED
            revision.published_at = revision.published_at or now
            update_fields.extend(["status", "published_at"])
        if update_fields:
            revision.save(update_fields=sorted(set(update_fields)))

    # ── Full-lifecycle plan nodes for the zero-start baseline ──
    #  Key: only Z0 is IN_PROGRESS; all other nodes are PLANNED.
    #  Parents MUST appear before children in this list.
    ZERO_START_NODES = [
        # ── Z 阶段：零起点筹备 ──
        {
            "node_id": "node-zero-start-z0",
            "parent": None,
            "sequence": 10,
            "code": "Z0",
            "title": "启动门槛筹备",
            "node_type": PlanNode.NodeType.MILESTONE,
            "status": PlanNode.Status.IN_PROGRESS,
            "is_required": True,
            "description": "确认自媒体渠道启动、报名入口开放、初筛标准和候选人沟通流程已预备。",
            "planned_duration_days": 14,
            "required_people_min": 1,
            "required_people_max": 3,
            "completion_criteria": ["报名漏斗已建立", "初筛标准已文档化"],
            "risk_notes": "若自媒体曝光不足或报名标准未文档化，启动将延迟。",
        },
        {
            "node_id": "node-zero-start-z1",
            "parent_id": "node-zero-start-z0",
            "sequence": 20,
            "code": "Z1",
            "title": "自媒体报名与初筛",
            "node_type": PlanNode.NodeType.RECRUITMENT,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "通过自媒体渠道发布招募信息，对报名者进行首轮初筛并形成候选池。",
            "planned_duration_days": 7,
            "required_people_min": 2,
            "required_people_max": 4,
            "completion_criteria": ["候选池 ≥ N 人"],
            "risk_notes": "报名质量过低时初筛效率会大幅下降。",
        },
        {
            "node_id": "node-zero-start-z2",
            "parent_id": "node-zero-start-z0",
            "sequence": 30,
            "code": "Z2",
            "title": "候选成员能力矩阵",
            "node_type": PlanNode.NodeType.GOVERNANCE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "对候选池成员建立能力矩阵，覆盖关键技能和可承担角色。",
            "planned_duration_days": 5,
            "required_people_min": 2,
            "required_people_max": 3,
            "completion_criteria": ["能力矩阵覆盖前 N 名候选人"],
            "risk_notes": "若关键技能门类空缺，需要定向补招或合作方承接。",
        },
        {
            "node_id": "node-zero-start-z3",
            "parent_id": "node-zero-start-z0",
            "sequence": 40,
            "code": "Z3",
            "title": "合作方与责任文件签署方矩阵",
            "node_type": PlanNode.NodeType.GOVERNANCE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "梳理必须由外部合作方或责任主体签署的文件清单，建立签署方矩阵。",
            "planned_duration_days": 10,
            "required_people_min": 2,
            "required_people_max": 5,
            "completion_criteria": ["责任文件清单已编制", "签署方矩阵已建立"],
            "risk_notes": "缺少可签署主体时后续工程节点无法通过责任闭环校验。",
        },

        # ── A 阶段：成员抵达与临时集结 ──
        {
            "node_id": "node-zero-start-a0",
            "parent": None,
            "sequence": 100,
            "code": "A0",
            "title": "分批抵达与临时集结",
            "node_type": PlanNode.NodeType.STAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "先遣队抵达后建立临时指挥点，后续批次按计划抵达并完成登记和临时安置。",
            "planned_duration_days": 14,
            "required_people_min": 3,
            "required_people_max": 10,
            "completion_criteria": ["临时指挥点就绪", "首批抵达登记完成", "临时安置完成"],
            "risk_notes": "交通和天气可能导致分批抵达延迟。",
        },
        {
            "node_id": "node-zero-start-a1",
            "parent_id": "node-zero-start-a0",
            "sequence": 110,
            "code": "A1",
            "title": "先遣队抵达并建立临时指挥点",
            "node_type": PlanNode.NodeType.OPERATIONS,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "先遣队率先抵达目标区域，搭建临时指挥与通信设施。",
            "planned_duration_days": 3,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["指挥点搭建完成", "通信联络测试通过"],
            "risk_notes": "无",
        },
        {
            "node_id": "node-zero-start-a2",
            "parent_id": "node-zero-start-a0",
            "sequence": 120,
            "code": "A2",
            "title": "分批抵达登记和临时安置",
            "node_type": PlanNode.NodeType.OPERATIONS,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "按批次完成抵达人员登记、健康筛查和临时住宿分配。",
            "planned_duration_days": 11,
            "required_people_min": 2,
            "required_people_max": 6,
            "completion_criteria": ["全部批次登记完成"],
            "risk_notes": "若临时住宿容量不足将导致抵达批次积压。",
        },

        # ── B 阶段：初步开荒基础设施 ──
        {
            "node_id": "node-zero-start-b0",
            "parent": None,
            "sequence": 200,
            "code": "B0",
            "title": "初步开荒基础设施",
            "node_type": PlanNode.NodeType.STAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "建立确保成员基本生存和协作所需的基础设施：食宿、供水、供电、卫生、仓储。",
            "planned_duration_days": 30,
            "required_people_min": 8,
            "required_people_max": 20,
            "completion_criteria": ["食住水电网卫生六大系统可运维"],
            "risk_notes": "物资采购周期长，机电设备进场可能需要外部承包商。",
        },
        {
            "node_id": "node-zero-start-b1",
            "parent_id": "node-zero-start-b0",
            "sequence": 210,
            "code": "B1",
            "title": "建立临时公共食堂",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "搭建临时厨房和就餐区，建立食材采购与餐食供应制度。",
            "planned_duration_days": 7,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["厨房和就餐区搭建完成", "首批食材到位", "出餐流程测试通过"],
            "risk_notes": "食材供应链不完整时需提前储备干粮。",
        },
        {
            "node_id": "node-zero-start-b2",
            "parent_id": "node-zero-start-b0",
            "sequence": 220,
            "code": "B2",
            "title": "搭建临时住宿和洗浴区",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "搭建帐篷/集装箱宿舍和临时洗浴设施。",
            "planned_duration_days": 10,
            "required_people_min": 4,
            "required_people_max": 10,
            "completion_criteria": ["住宿容量 ≥ 首批人数", "洗浴设施可用"],
            "risk_notes": "极端天气可能延缓搭建进度。",
        },
        {
            "node_id": "node-zero-start-b3",
            "parent_id": "node-zero-start-b0",
            "sequence": 230,
            "code": "B3",
            "title": "临时供水与净水系统",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "勘探水源、铺设临时供水管线并部署净水设备。",
            "planned_duration_days": 12,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["水源确认", "净水设备出水达标"],
            "risk_notes": "地下水水质需提前检测。",
        },
        {
            "node_id": "node-zero-start-b4",
            "parent_id": "node-zero-start-b0",
            "sequence": 240,
            "code": "B4",
            "title": "临时供电和安全照明",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "部署柴油发电机、临时配电箱和道路/营地安全照明。",
            "planned_duration_days": 10,
            "required_people_min": 3,
            "required_people_max": 5,
            "completion_criteria": ["发电机就位", "主要通道照明覆盖"],
            "risk_notes": "燃油消耗高，需预估日耗量并提前储备。",
        },
        {
            "node_id": "node-zero-start-b5",
            "parent_id": "node-zero-start-b0",
            "sequence": 250,
            "code": "B5",
            "title": "公共卫生和垃圾处理制度",
            "node_type": PlanNode.NodeType.OPERATIONS,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "制定营地卫生和垃圾分类处理制度，防止疫病。",
            "planned_duration_days": 5,
            "required_people_min": 2,
            "required_people_max": 4,
            "completion_criteria": ["卫生制度已发布", "垃圾处理点就绪"],
            "risk_notes": "无",
        },
        {
            "node_id": "node-zero-start-b6",
            "parent_id": "node-zero-start-b0",
            "sequence": 260,
            "code": "B6",
            "title": "仓储一区和工具库",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "搭建首批仓储空间，存放工具、建材和关键耗材。",
            "planned_duration_days": 8,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["仓储一区投入使用"],
            "risk_notes": "缺少货架和防潮措施会导致物资损耗。",
        },

        # ── C 阶段：第一轮扩容与新成员接纳 ──
        {
            "node_id": "node-zero-start-c0",
            "parent": None,
            "sequence": 300,
            "code": "C0",
            "title": "第一轮扩容和新成员接纳",
            "node_type": PlanNode.NodeType.STAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "评估现有容量后接纳新一批成员，并启动正式住房、光伏和扩容仓储。",
            "planned_duration_days": 45,
            "required_people_min": 10,
            "required_people_max": 30,
            "completion_criteria": ["新成员审核完毕", "一期住房可入住", "光伏发电上线"],
            "risk_notes": "扩容速度受限于基建材料供应和人力投入。",
        },
        {
            "node_id": "node-zero-start-c1",
            "parent_id": "node-zero-start-c0",
            "sequence": 310,
            "code": "C1",
            "title": "公共食堂一期",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "将临时食堂升级为标准化公共食堂，支持日均 100+ 人就餐。",
            "planned_duration_days": 14,
            "required_people_min": 4,
            "required_people_max": 8,
            "completion_criteria": ["食堂硬件就绪", "配餐排班系统运行"],
            "risk_notes": "若无稳定食材供应链需延续干粮过渡。",
        },
        {
            "node_id": "node-zero-start-c2",
            "parent_id": "node-zero-start-c0",
            "sequence": 320,
            "code": "C2",
            "title": "正式住房一期",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "建设首批正式住房（木结构或预制件），解除安置上限。",
            "planned_duration_days": 30,
            "required_people_min": 6,
            "required_people_max": 15,
            "completion_criteria": ["一期住房完工并验收"],
            "risk_notes": "建材到货延迟是最大风险。",
        },
        {
            "node_id": "node-zero-start-c3",
            "parent_id": "node-zero-start-c0",
            "sequence": 330,
            "code": "C3",
            "title": "光伏一期 0.5MW",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "安装首批光伏面板与储能系统，替代柴油发电机。",
            "planned_duration_days": 20,
            "required_people_min": 4,
            "required_people_max": 8,
            "completion_criteria": ["光伏并网发电", "储能系统可用"],
            "risk_notes": "光伏板运输和安装需要专业电工。",
        },
        {
            "node_id": "node-zero-start-c4",
            "parent_id": "node-zero-start-c0",
            "sequence": 340,
            "code": "C4",
            "title": "仓储空间一期扩容",
            "node_type": PlanNode.NodeType.WORK_PACKAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "扩大仓储面积以应对扩容带来的物资增长。",
            "planned_duration_days": 10,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["扩容仓储存量翻倍"],
            "risk_notes": "无",
        },
        {
            "node_id": "node-zero-start-c5",
            "parent_id": "node-zero-start-c0",
            "sequence": 350,
            "code": "C5",
            "title": "第一轮成员接纳评审",
            "node_type": PlanNode.NodeType.GOVERNANCE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "依据能力矩阵和社区规则对新一批申请人进行评审和接纳决策。",
            "planned_duration_days": 7,
            "required_people_min": 3,
            "required_people_max": 5,
            "completion_criteria": ["评审记录已归档", "接纳名单已公示"],
            "risk_notes": "评审效率受信息完备程度影响。",
        },

        # ── D 阶段：稳定运营与治理闭环 ──
        {
            "node_id": "node-zero-start-d0",
            "parent": None,
            "sequence": 400,
            "code": "D0",
            "title": "稳定运营与治理闭环",
            "node_type": PlanNode.NodeType.STAGE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "当扩容完成后进入日常运营治理：排班常态化、财务台账闭环、安全巡检和下一轮计划修订。",
            "planned_duration_days": 30,
            "required_people_min": 8,
            "required_people_max": 20,
            "completion_criteria": ["运营排班制度化", "财务台账完成首个周期"],
            "risk_notes": "治理闭环依赖所有前置阶段已稳定。",
        },
        {
            "node_id": "node-zero-start-d1",
            "parent_id": "node-zero-start-d0",
            "sequence": 410,
            "code": "D1",
            "title": "食堂与住宿常态化排班",
            "node_type": PlanNode.NodeType.OPERATIONS,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "建立食堂轮值和住宿维护的常态化排班制度。",
            "planned_duration_days": 7,
            "required_people_min": 4,
            "required_people_max": 8,
            "completion_criteria": ["排班表发布", "运转满 1 周"],
            "risk_notes": "无",
        },
        {
            "node_id": "node-zero-start-d2",
            "parent_id": "node-zero-start-d0",
            "sequence": 420,
            "code": "D2",
            "title": "财务与物资台账闭环",
            "node_type": PlanNode.NodeType.GOVERNANCE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "建立收支记录、物资出入库台账和定期审计机制。",
            "planned_duration_days": 10,
            "required_people_min": 2,
            "required_people_max": 4,
            "completion_criteria": ["首个周期台账完成"],
            "risk_notes": "无专人负责时台账质量难以保证。",
        },
        {
            "node_id": "node-zero-start-d3",
            "parent_id": "node-zero-start-d0",
            "sequence": 430,
            "code": "D3",
            "title": "安全巡检与事故演练",
            "node_type": PlanNode.NodeType.OPERATIONS,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "制定安全巡检清单并定期开展应急演练。",
            "planned_duration_days": 7,
            "required_people_min": 2,
            "required_people_max": 4,
            "completion_criteria": ["巡检清单执行", "应急演练完成 1 次"],
            "risk_notes": "无",
        },
        {
            "node_id": "node-zero-start-d4",
            "parent_id": "node-zero-start-d0",
            "sequence": 440,
            "code": "D4",
            "title": "第二轮计划修订与容量评估",
            "node_type": PlanNode.NodeType.GOVERNANCE,
            "status": PlanNode.Status.PLANNED,
            "is_required": True,
            "description": "评估当前运营容量并启动第二轮计划修订，为下一步扩张或优化提供决策依据。",
            "planned_duration_days": 10,
            "required_people_min": 3,
            "required_people_max": 6,
            "completion_criteria": ["容量评估报告", "第二轮计划修订草案"],
            "risk_notes": "评估质量取决于前置台账数据的完整性。",
        },
    ]

    for spec in ZERO_START_NODES:
        node_id = spec["node_id"]
        parent = None
        parent_id = spec.get("parent_id")
        if parent_id:
            parent = PlanNode.objects.filter(node_id=parent_id).first()

        defaults: dict[str, object] = {
            "revision": revision,
            "parent": parent or spec.get("parent"),
            "sequence": spec["sequence"],
            "code": spec["code"],
            "title": spec["title"],
            "node_type": spec["node_type"],
            "status": spec["status"],
            "is_required": spec.get("is_required", True),
            "description": spec.get("description", ""),
            "planned_duration_days": spec.get("planned_duration_days", 1),
            "required_people_min": spec.get("required_people_min", 0),
            "required_people_max": spec.get("required_people_max", 0),
            "completion_criteria": spec.get("completion_criteria", []),
            "risk_notes": spec.get("risk_notes", ""),
            "metadata": {"seed": True, "template": "zero_start"},
            "created_at": now,
            "updated_at": now,
        }

        node, _created = PlanNode.objects.get_or_create(
            node_id=node_id,
            defaults=defaults,
        )
        if not _created:
            changed: dict[str, object] = {}
            for field, value in defaults.items():
                if field in ("node_id", "created_at"):
                    continue
                if getattr(node, field) != value:
                    changed[field] = value
            if changed:
                for field, value in changed.items():
                    setattr(node, field, value)
                node.save(update_fields=sorted(changed.keys()))

    return {"founder": founder, "plan": plan, "revision": revision}
