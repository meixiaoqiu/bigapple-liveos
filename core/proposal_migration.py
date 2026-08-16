"""统一提案系统迁移期间的失败关闭状态。"""

from __future__ import annotations

from core.exceptions import DomainError


PROPOSAL_FLOW_UNAVAILABLE_MESSAGE = "统一提案流程正在迁移，当前决策操作暂不可用。报名资料已保留，请稍后再试。"


class ProposalFlowUnavailable(DomainError):
    """表示某项必须经提案决定的流程尚未迁移，禁止直接改变权威状态。"""


def raise_proposal_flow_unavailable() -> None:
    """以统一领域错误关闭尚未迁移的提案写操作。"""

    raise ProposalFlowUnavailable(PROPOSAL_FLOW_UNAVAILABLE_MESSAGE)
