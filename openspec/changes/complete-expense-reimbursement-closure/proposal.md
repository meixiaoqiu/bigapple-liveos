## Why

Live OS 已有报销提交、审核、付款确认、追加式财务流水和公开财务页面，但缺少发票、消费记录、付款凭证等正式业务附件，也没有把内置付款执行表达为可替换后端。现在需要把已有后端能力补成成员可真实使用的闭环，同时落实“当前全部功能由 Live OS 内置实现，未来可逐项切换到其他系统”的架构原则。

## What Changes

- 在现有头像文件处理与私有对象存储底座上增加正式业务附件能力：原件默认私有、不可静默覆盖，支持只追加更正和独立公开脱敏副本。
- 报销提交支持上传发票、收据、支付或消费记录；第一版接受 PDF、JPEG、PNG、WebP 和 CSV，并对数量、单文件大小、总大小、真实内容类型和文件名展示执行限制。
- 报销详情按申请人、`finance.review`、`finance.pay`、`finance.view_private` 的明确权限展示私有材料；公开观察页面只读取显式发布的公开副本，绝不通过同一对象的公开开关暴露原件。
- 付款确认补充付款日期、付款方式、付款凭证和可选备注，并继续生成不可修改的 `FinanceTransaction`。
- 引入窄的付款执行后端边界；默认 `LiveOSManualPaymentBackend` 是完整、可长期使用的内置实现，未来可按部署配置替换为 ERP、办公审批或银行适配器，而不改变报销制度事实、公开审计和永久档案。
- 保存执行后端结果所需的稳定引用和不可变快照，但不预先实现任何第三方适配器，也不把第三方系统术语泄漏到成员页面。
- 同步数据库结构、架构、成员工作台、观察台、Admin、开发与运行文档；若新增或修改对外 API、schema 或 payload，必须先更新技术契约。本次默认只扩展 Django 页面与内部领域模型，不新增公共 API。
- 非目标：采购、预算占用、多人会签、部分付款、发票 OCR/验真、复式会计、税务、多币种汇兑、银行自动付款、ERPNext/飞书/钉钉真实集成。
- 权限影响：继续使用 `AuthorizationService` / OpenFGA；私有附件读取使用 `finance.view_private` 或报销当事人边界，公开副本发布使用独立的 `finance.publish_public_attachments` 权限，申请人仍不得自审或自付。
- 数据影响：新增通用附件及业务关联记录，扩展付款事实；财务流水、已提交附件版本和公开副本均采用追加或显式作废语义，不覆盖审计历史。
- 公开契约影响：公开页面只增加脱敏后的报销时间线与公开附件；不公开账户、联系方式、未经脱敏的发票或支付凭证，也不暴露对象存储 key。

## Capabilities

### New Capabilities

- `audited-business-attachments`: 覆盖正式业务附件的安全接收、私有原件、只追加版本、公开脱敏副本、受控读取、world 生命周期和存储审计。
- `expense-reimbursement-closure`: 覆盖成员提交凭证、独立财务审核、带付款资料的付款确认、追加式支出流水和公开脱敏时间线。
- `replaceable-finance-execution`: 覆盖 Live OS 内置付款执行作为默认完整实现，以及未来按能力替换执行后端而不转移治理和审计权威的边界。

### Modified Capabilities

无。当前主规格目录尚未收录附件或公开财务能力，本变更以新增 delta specs 描述现有能力的增量闭环。

## Impact

- Live OS：`core.models` 财务与附件领域、文件处理和存储 gateway、`core.finance_services`、新的附件领域服务、workspace 表单/页面、observer 财务页、Admin 只读展示、仿真 world runtime 清理及测试。
- 数据库：新增附件、公开副本/更正关系、报销附件关联和付款执行记录；既有财务流水继续保持只追加。
- 对象存储：继续使用现有 Django Storage 和 `<world-id>/runtime/` 隔离，新增不可与头像删除规则混用的业务附件前缀。
- 文档：更新 sibling `bigapple-docs` 中数据库、架构、成员工作台、观察台、Admin 和开发说明；公共 API 若保持不变则不修改技术契约。
- 依赖：优先复用现有 Magika、Pillow 和 Django Storage；PDF、CSV 原件验证若现有依赖足够则不新增依赖。
