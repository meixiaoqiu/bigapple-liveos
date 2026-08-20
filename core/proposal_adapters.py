"""统一提案类型适配器注册表。

统一生命周期只通过本模块发现业务类型，不在核心服务中堆叠
``if proposal_type == ...`` 分支。尚未迁移的业务不得注册适配器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .exceptions import DomainError

if TYPE_CHECKING:
    from .models import ApprovalProposal, Member


ProposalExecutor = Callable[["ApprovalProposal", "Member"], object]
ProposalExcludedMemberGetter = Callable[["ApprovalProposal"], object | None]
ProposalResolutionCallback = Callable[["ApprovalProposal", "Member"], None]


@dataclass(frozen=True)
class ProposalTypeAdapter:
    """描述一个提案类型与其权威业务动作之间的固定边界。"""

    proposal_type: str
    strategy_type: str
    source_type: str
    initiation_permission: str
    resolution_permission: str
    execution_permission: str
    executor: ProposalExecutor
    excluded_member_id_getter: ProposalExcludedMemberGetter | None = None
    resolution_callback: ProposalResolutionCallback | None = None

    def excluded_member_id(self, proposal: "ApprovalProposal") -> object | None:
        if self.excluded_member_id_getter is None:
            return None
        return self.excluded_member_id_getter(proposal)


_ADAPTERS: dict[str, ProposalTypeAdapter] = {}


def register_proposal_adapter(adapter: ProposalTypeAdapter) -> None:
    """登记唯一提案类型适配器；重复登记视为配置错误。"""

    if not adapter.proposal_type:
        raise DomainError("提案类型不能为空。")
    if adapter.proposal_type in _ADAPTERS:
        raise DomainError(f"提案类型适配器重复登记：{adapter.proposal_type}")
    _ADAPTERS[adapter.proposal_type] = adapter


def proposal_adapter_for(proposal_type: str) -> ProposalTypeAdapter:
    """返回已迁移适配器；未迁移类型必须失败关闭。"""

    if proposal_type not in _ADAPTERS:
        # 内置适配器按需加载，避免模型导入阶段产生循环依赖。
        from . import member_admission_proposal_adapter  # noqa: F401

    try:
        return _ADAPTERS[proposal_type]
    except KeyError as exc:
        raise DomainError("该提案业务尚未迁移到统一提案系统。") from exc


def registered_proposal_types() -> tuple[str, ...]:
    """返回稳定排序的已迁移提案类型，供检查和诊断使用。"""

    return tuple(sorted(_ADAPTERS))
