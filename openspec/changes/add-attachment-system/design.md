## Context

参见 `proposal.md` 的动机和 `specs/attachment-management/spec.md` 的行为要求。当前 `MemberPublicProfile.avatar_url` 是可由成员填写的外部 URL，workspace 的资料更新 view 直接接收该字符串，系统没有文件处理、对象存储或一致性维护能力。

项目的权威模型必须归属 `core` app，业务数据按 world 数据库隔离，页面入口位于 `workspace`，运行时授权统一经过 `AuthorizationService` / OpenFGA。头像是可删除的当前展示资产；未来报销、提案和任务材料是正式提交后不可删除的审计附件。二者应复用安全处理与存储能力，但不得共用生命周期模型。

## Goals / Non-Goals

**Goals:**

- 用个人头像完成上传、识别、解码、WebP 重编码、私有存储、读取、替换与清理闭环。
- 让旧头像 URL 输入退出产品路径，不下载或信任用户提供的外部资源。
- 建立与具体业务 owner 无关的文件处理和 Storage gateway，供未来永久附件复用。
- 在目录、接口和存储前缀层面隔离“可删除当前资产”与“永久审计附件”。
- 保持现有 world 路由和本人身份推导规则，不增加新的 Django app 或授权体系。

**Non-Goals:**

- 第一阶段不创建 `AttachmentCollection`、`Attachment` 或任何永久版本表。
- 不保存头像原图、历史头像、动画、用户裁剪参数或原始文件名。
- 不提供通用文件上传 API、公开 `/api/v0.1/` 契约、分块上传、在线附件预览或病毒扫描。
- 不以头像服务的删除逻辑作为未来永久附件的默认实现。

## Decisions

### 1. 不创建独立 Django app，按领域包组织 `core`

第一阶段使用以下边界：

```text
core.file_processing
  detection.py       # Magika 识别和允许列表
  images.py          # Pillow 解码、规范化和 WebP 输出
  limits.py          # 流式字节与像素限制
  hashing.py         # 处理后内容哈希

core.file_storage
  keys.py            # 随机 key 和 world 命名空间
  gateway.py         # 命名 Django Storage 访问
  temporary.py       # 临时对象与补偿清理

core.avatar_services # 头像状态变化
workspace            # 表单、view、URL 和模板
```

权威 `MemberPublicProfile` 已属于 `core`，现有 world router 也已覆盖 `core`。新增 Django app 只会增加迁移、路由和配置边界，并不会自动提高模块化程度。因此当前使用 Python package 隔离职责。

未来永久附件仍在 `core.models.attachments` 和 `core.attachments.*` 中实现。如果文件能力将来需要独立数据库、独立部署、服务多个项目或单独扩缩容，再评估拆分 Django app 或独立服务。

未采用把所有逻辑放入 `core.avatar_services` 的方案，因为格式识别与存储操作需要被未来附件复用。也不创建 `core.services` 门面。

### 2. 用系统管理的对象引用替代 `avatar_url`

`MemberPublicProfile` 删除可编辑的外部 `avatar_url`，增加：

- `avatar_key`：当前私有对象 key，空值表示默认头像；不存 URL。
- `avatar_sha256`：处理后 WebP 的完整性摘要，空头像时为空。
- `avatar_size`：处理后字节数，用于一致性与响应检查。
- `avatar_updated_at`：头像最后成功切换或移除时间，区别于公开姓名、简介等资料更新时间。

这些字段属于当前状态，不形成版本历史。字段使用 `help_text` 说明语义；`avatar_key` 不允许由表单直接写入。

迁移不抓取既有外部 URL，避免 SSRF、隐私泄漏和不可验证内容进入权威存储。现有 `avatar_url` 值统一回退为默认头像，删除字段后由成员自行上传新头像。当前项目仍是原型，此清晰迁移优于长期保留双路径。

未采用 Django `ImageField`，因为它会把模型字段与单个 storage alias、文件命名和删除习惯绑得过紧；显式 key 加 gateway 更容易区分当前资产与未来永久对象。

### 3. 内容识别和图片规范化采用分层验证

上传处理顺序固定为：

1. 流式接收并拒绝超过 10 MiB 的输入；临时对象不得使用客户端文件名。
2. Magika 使用高置信模式识别内容；只接受 JPEG、PNG、WebP、GIF、BMP、TIFF 标签。
3. Pillow 只读取 header 获得尺寸，先拒绝任一边超过 8,192 或总量超过 25,000,000 像素的输入，并启用解压炸弹保护；尺寸通过后才允许完整解码，避免超限图片先分配完整像素缓冲区。
4. 完整解码后应用 EXIF orientation，动画只取第一帧，转换到 RGB 或 RGBA。
5. 以中心为基准裁剪正方形并使用高质量缩放到 `512 × 512`。
6. 不传递 EXIF、ICC、GPS、comment 等来源元数据，以 WebP quality 85 重新编码；保留 alpha 通道。
7. 对最终 WebP 计算 SHA-256 和字节数，再进入正式对象写入。

Magika 是第一层内容分类，不替代 Pillow 格式解析。Pillow 解码结论和允许列表才决定图片是否可处理。任一检测器异常均失败关闭。

未接受“Pillow 能打开的所有格式”，因为 SVG、PSD、ICO、RAW、HEIC 等格式的安全边界、依赖和用户价值不同；以后按真实需求逐项扩展允许列表。

### 4. Storage gateway 同时支持本地与 OCI S3 兼容后端

通过命名 Django Storage alias `avatars` 和 `avatar_temporary` 访问对象。生产环境的 `avatars` 使用 `django-storages` S3 backend 与 boto3，配置 OCI Object Storage 的：

- S3 compatibility endpoint；
- region；
- Object Storage namespace；
- 私有 bucket；
- Customer Secret Key access/secret；
- SigV4 与 path-style addressing（除非实际 bucket 明确启用并验证 virtual-hosted style）。

所有凭据来自环境变量，不进入仓库、数据库、日志或页面。开发与测试使用 `FileSystemStorage` 指向被 Git 忽略的独立目录或每个测试的临时目录。

业务代码只能调用 gateway 的 `save_processed`、`open_current`、`exists` 和“当前资产安全删除”等窄接口，不能直接拼 OCI URL。未来园区内网存储只需替换 Storage 配置或 gateway 后端。

头像读取由 Live OS 的固定 world 路由查找资料后流式返回 WebP，并设置明确的内容类型、`nosniff`、公开缓存和 ETag。页面地址携带由 `avatar_updated_at` 生成的非敏感版本参数；成功替换或移除后 URL 立即变化，有效头像响应可长期 immutable 缓存，默认头像和 Storage 异常回退只允许短期缓存。第一版不把私有 bucket 的 object key、内容哈希 URL 或永久存储 URL 暴露给浏览器。以后如流量需要短期签名 URL，必须重新评估 object key 暴露和缓存策略。

### 5. object key 同时编码生命周期分区与 world 隔离

正式头像 key 形如：

```text
worlds/<world-id>/current-assets/avatars/<random-uuid>.webp
```

临时 key 形如：

```text
worlds/<world-id>/temporary/avatar-uploads/<random-uuid>
```

未来永久附件必须使用独立前缀，例如：

```text
worlds/<world-id>/permanent-attachments/<random-uuid>
```

删除接口只接受解析并验证为 `current-assets/avatars/` 或头像临时区的 key，拒绝任何永久附件前缀、其它 world、路径穿越或调用者提供的任意 key。永久附件 gateway 将来不提供通用 delete。

world id 由可信 request/world context 推导，不能来自上传表单。若部署选择每个 world 独立 bucket，key 中仍保留 world 前缀以便迁移与审计。

### 6. 头像替换采用先写后切换和提交后补偿

服务流程：

```text
接收临时内容
→ 安全处理为 WebP
→ 写入新随机正式 key
→ 数据库事务中锁定 MemberPublicProfile
→ 切换 avatar_key / sha256 / size / avatar_updated_at
→ transaction.on_commit 删除旧头像和临时对象
```

若新对象写入失败，不改数据库。若数据库事务失败，立即尝试删除新对象；删除失败则由一致性命令识别为无引用当前资产。若旧对象删除失败，新头像仍然有效，失败进入日志和一致性报告。

并发替换通过数据库行锁串行化。事务内再次读取旧 key；提交后删除时必须确认待删除 key 与新 key 不同且属于同一可信 world 的头像前缀。服务函数改变权威状态，必须写 docstring。

对象存储不参与数据库事务，因此设计承认短暂无引用对象，并通过严格前缀、不可预测 key 和一致性清理补偿，而不是宣称跨系统原子性。

### 7. 头像权限不扩张现有授权体系

- 本人上传、替换或移除头像：身份只从 session 绑定的 `Member` 推导，view 不接收 member id。
- 公开读取：只读取目标成员当前资料，缺失或存储异常回退默认头像。
- 违规移除：使用 `AuthorizationService.member_has_permission(actor, "governance.manage_people")`，记录具体 actor 和时间；维护人员不能代成员上传。
- staff/superuser 只属于技术 Admin 边界，不自动获得业务头像维护权。

现有公开资料更新继续处理公开名等文本字段；头像使用独立 multipart POST endpoint，避免文本验证失败与文件状态变化处于难以补偿的同一表单事务。

### 8. 当前资产一致性与未来永久审计职责分离

头像维护命令支持显式 world 和 `--dry-run`，报告：

- 数据库当前 key 对应对象缺失；
- 头像正式前缀中没有任何当前引用的对象；
- 超过 24 小时的头像临时对象；
- 可选的 size 或 SHA-256 不匹配。

显式清理模式只能删除已证明无当前引用且属于头像/临时前缀的对象。数据库引用缺失时只报告并让读取回退默认头像，不自动清空字段。

未来永久附件使用另一套只读审计命令；即使发现没有数据库记录的永久对象，也只能报告，不能自动删除。命令、gateway、配置和测试都必须阻止头像清理越过生命周期前缀。

### 9. 为永久附件保留明确的二次开发接口

未来阶段在不改变上述处理模块的情况下增加：

```text
BusinessObject --真实保护性外键--> AttachmentCollection
AttachmentCollection --保护性外键--> Attachment
Attachment --supersedes--> Attachment
```

永久附件在审计提交前可使用临时区；进入审计记录后只允许新增更正版本、冻结、密封或归档，原记录与对象永久保留。它可以复用 Magika、图片规范化、流式限制、哈希、随机 key 和 Storage gateway 的只读/写入原语，但必须使用独立模型、policy 和不提供删除的永久 gateway。

不提前创建空泛 `Attachment` 表或通用 owner registry。等第一个真实审计场景确定后，再根据该领域的提交边界和权限建立真实外键。

## Risks / Trade-offs

- [现有外部头像 URL 在迁移后不再显示] → 不主动抓取不可信远程资源；统一回退默认头像并提示成员重新上传。
- [中心裁剪可能截掉主体] → 第一版保持简单和确定；后续按使用反馈增加客户端裁剪区域，不改变存储边界。
- [同步 Magika/Pillow 处理增加请求耗时] → 头像输入限制较小，进程内复用 Magika 实例；达到真实负载瓶颈后再迁移到隔离 worker。
- [ONNX Runtime 增加镜像体积] → 这是内容识别成熟度的成本；在目标 Windows/Linux 和 Docker 环境验证 wheel 后再锁定版本。
- [应用流式返回头像增加 Web 负载] → 使用 ETag、公共缓存和 512 像素固定输出；流量超过单体能力后再引入受控 CDN 或短签名 URL。
- [数据库和对象存储无法原子提交] → 采用先写后切换、行锁、提交后删除和前缀受限一致性补偿。
- [头像自动清理误伤永久附件] → 生命周期使用不同前缀和 gateway；删除函数拒绝永久前缀并由测试验证。
- [OCI S3 兼容行为与 AWS 不完全一致] → 只依赖 Put/Get/Head/Delete 基础操作，在真实 OCI bucket 上做部署探针；不依赖 ACL 或未经验证的 S3 扩展。

## Migration Plan

1. 增加并锁定 Pillow、Magika、`django-storages` 和 boto3，在宿主机与 Docker 中验证导入、WebP 编解码和 Magika 模型加载。
2. 增加本地/测试 Storage 配置和 OCI 环境配置校验；先用独立私有 bucket 或专用 prefix 运行存储探针。
3. 为 `MemberPublicProfile` 增加新头像字段，切换读写代码并使既有外部 URL 回退默认头像；确认无代码依赖后删除 `avatar_url`。
4. 上线文件处理、Storage gateway、头像服务、独立 multipart 页面动作和受控读取 endpoint。
5. 上线 dry-run 一致性检查，确认只扫描当前 world 的头像和临时前缀后再启用清理模式。
6. 更新数据库、架构、成员工作台和部署文档，并运行 workspace、observer、core、world 隔离及完整回归测试。

回滚时先关闭上传和清理入口，保留新头像字段与对象；可以让读取临时回退默认头像，但不得执行无法证明归属的批量对象删除。已移除的外部 URL 不自动恢复。
