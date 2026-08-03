## Why

Live OS 目前没有统一、安全的文件上传和图片处理能力，成员头像仍依赖手工填写外部 URL。先用个人头像建立最小上传闭环，可以验证浏览器上传、真实格式识别、图片安全重编码、私有对象存储、授权读取和旧对象清理，同时为后续报销凭证、提案材料、任务交付物等永久审计附件保留清晰的二次开发边界。

## What Changes

- 新增成员个人头像上传、替换和恢复默认头像能力；头像属于“当前展示资产”，不属于永久审计附件，不保留历史头像文件。
- 所有受支持的位图输入都必须经过内容类型识别和 Pillow 完整解码，校正方向、限制像素、去除元数据、静态化后统一生成 `512 × 512` WebP；SVG、HEIC、RAW、PSD、ICO 第一版不接收。
- 不保存客户端原始文件名；对象 key 使用随机标识和隔离的 world 前缀，数据库只保存当前头像对象 key、处理后媒体类型和必要状态信息。
- 头像替换采用“先生成并保存新对象、再原子切换数据库引用、提交成功后删除旧对象”的顺序；任一步失败时不得破坏当前有效头像。
- 头像存储使用 Django Storage 抽象，当前生产后端通过 S3 兼容方式接入 Oracle Cloud Infrastructure Object Storage，开发和测试使用隔离的本地存储。
- 对象 key 以 `<world-id>/runtime/` 为统一运行期根前缀；仿真 world 重置必须清理该 runtime 前缀后再重建 zero-start，且不得读取、移动或删除 control DB 与 `var/simulation_archives/` 中的历史归档。
- 提取可复用但不提前泛化的文件处理边界：流式大小限制、Magika 内容类型识别、图片解码重编码、随机 key、哈希计算、临时对象管理和 Storage 访问均不得写死在头像 view 中。
- 为未来永久附件预留二次开发空间：后续可在相同处理和存储基础设施上增加独立的 `AttachmentCollection` / `Attachment` 模型、真实业务外键、正式提交、冻结、版本更正、密封、归档和永久一致性审计；头像模型不得冒充或弱化该永久生命周期。
- 第一阶段不实现通用附件表、报销/提案/任务附件、永久版本链、公开文件 API、断点续传、在线预览、文件去重、ClamAV、消息队列、云镜像复制、冷热分层或自动灾难切换。
- 权限影响：成员只能修改自己的头像；拥有 `governance.manage_people` 权限的维护人员可以移除违规头像但不能冒充成员上传；公开读取只返回当前有效头像或默认头像，不新增角色或授权旁路。
- 数据影响：把 `MemberPublicProfile.avatar_url` 调整为由系统管理的当前头像引用及处理元数据；头像旧对象可在引用成功切换后删除，不属于永久档案。
- 公开契约影响：第一版只增加成员工作台页面端点，不新增或修改 `/api/v0.1/` technical contracts。

## Capabilities

### New Capabilities

- `attachment-management`: 第一阶段定义安全文件处理基础设施和个人头像当前资产的上传、替换、移除与读取行为，并约束该基础设施未来扩展为永久审计附件时必须保持生命周期隔离。

### Modified Capabilities

无。

## Impact

- Live OS：修改 `MemberPublicProfile`，增加头像领域服务、文件识别与图片处理模块、成员工作台上传入口、受控头像读取入口、配置、测试、运维一致性检查和仿真 world runtime 文件清理。
- 存储：新增命名 Django Storage alias；生产环境使用私有 OCI Object Storage bucket 的 S3 兼容 endpoint，业务代码不得依赖 Oracle namespace、bucket 名称、永久公网 URL或本地绝对路径。
- 依赖：增加 Pillow、Magika、`django-storages` 与 boto3；分别承担图片格式解析和重编码、内容类型识别、Django Storage 后端与 S3 兼容客户端职责。
- 演进边界：未来永久附件复用处理模块和 storage gateway，但使用独立权威模型及只追加服务；不得通过给头像记录堆叠状态字段来实现审计附件。
- 文档：同步 `../bigapple-docs/docs/architecture/database-schema.md`、`overview.md`、`docs/product/member-workspace.md`（若存在）和 `../bigapple-docs/docs/development/setup.md`；未增加公开 API，因此本阶段无需修改 technical contracts。
