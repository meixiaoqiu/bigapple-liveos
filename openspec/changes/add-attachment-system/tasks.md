## 1. 依赖、配置与存储探针

- [x] 1.1 在 `pyproject.toml` 增加并锁定 Pillow、Magika、`django-storages` 和 boto3，记录各依赖理由，并验证本地 Windows、Docker Linux、WebP 编解码及 Magika 模型加载。
- [x] 1.2 增加头像上传限制、图片像素、WebP 输出和 24 小时临时保留期配置，验证无效环境变量会失败关闭且默认值符合规格。
- [x] 1.3 配置命名 Django Storage alias `avatars` 与 `avatar_temporary`；开发和测试使用隔离目录，生产使用 OCI Object Storage S3 兼容 endpoint、私有 bucket、SigV4 和最小权限凭据。
- [x] 1.4 实现不输出密钥的 OCI 存储探针，验证 Put/Get/Head/Delete 基础操作、私有访问和错误配置提示，不在仓库、数据库或日志中写入真实凭据。
- [x] 1.5 更新 `.gitignore` 和测试清理，使本地 `var` 头像、临时对象和测试产物均不进入 Git。

## 2. 可复用文件处理与存储边界

- [x] 2.1 创建 `core.file_processing` 包，实现 10 MiB 流式限制和临时内容管理，测试超限、中断、空文件及读写异常均失败关闭。
- [x] 2.2 实现可复用的 Magika 高置信内容识别和 JPEG/PNG/WebP/GIF/BMP/TIFF 允许列表，测试伪装扩展名、声明冲突、低置信度、未知格式以及 SVG/HEIC/RAW/PSD/ICO 拒绝。
- [x] 2.3 实现 Pillow 完整解码、EXIF 方向校正、8,192 边长和 25,000,000 总像素限制、解压炸弹保护、动画首帧、居中裁剪与高质量缩放。
- [x] 2.4 实现 `512 × 512`、quality 85 的静态 WebP 输出，保留透明通道并剥离 EXIF、ICC、GPS、注释等来源元数据；测试输出可重新完整解码且不含原图隐私元数据。
- [x] 2.5 实现处理后 SHA-256、字节数和随机 key 生成，验证 key、日志、响应和持久化字段均不包含原始文件名、客户端路径或内容哈希 URL。
- [x] 2.6 创建 `core.file_storage` gateway，分离临时、当前头像和未来永久附件前缀；删除接口只接受当前 world 的头像/临时 key，并用测试证明拒绝路径穿越、其它 world 和 `permanent-attachments/`。

## 3. 头像权威模型与迁移

- [x] 3.1 修改 `MemberPublicProfile`，以带 `help_text` 的 `avatar_key`、`avatar_sha256`、`avatar_size` 和 `avatar_updated_at` 表达当前头像状态，空 key 表示默认头像。
- [x] 3.2 编写分阶段迁移：先添加头像字段并切换代码，再删除 `avatar_url`；既有外部 URL 不远程抓取，迁移后安全回退默认头像。
- [x] 3.3 更新模型、workspace context、observer 公开资料和 Admin 展示，确保 `avatar_key` 为只读内部字段且不存在继续编辑外部头像 URL 的入口。
- [x] 3.4 添加模型和迁移测试，验证空头像、字段一致性、既有 URL 回退以及真实/仿真 world 中公开资料各自保存在所属数据库。

## 4. 头像领域服务与失败补偿

- [x] 4.1 在 `core.avatar_services` 实现带 docstring 的本人上传服务，身份由调用方已解析的当前 Member 提供，服务内部不接受任意目标 member id 或 object key。
- [x] 4.2 实现“临时处理、新正式对象写入、锁定资料行、切换引用、`transaction.on_commit` 清理旧对象”的替换流程，覆盖首次上传、重复替换和并发替换。
- [x] 4.3 实现恢复默认头像服务，数据库提交成功后才清理旧当前资产，并确保重复移除幂等。
- [x] 4.4 用故障注入测试处理失败、Storage 写入失败、数据库回滚、新对象补偿删除失败和旧对象删除失败；所有失败均保持原头像可用或让新头像成为唯一当前引用。
- [x] 4.5 实现维护人员移除违规头像服务，通过 `AuthorizationService` 检查 `governance.manage_people`、记录具体 actor 和时间，并拒绝维护人员代替成员上传头像。

## 5. Workspace 页面与头像读取

- [x] 5.1 把公开资料文本更新与头像 multipart 上传拆成独立 POST endpoint，表单使用 CSRF 防护，view 保持轻量并只从 session 推导当前 Member。
- [x] 5.2 更新成员资料模板，增加头像预览、文件选择、限制提示、上传、替换和恢复默认头像操作，并移除外部 URL 输入框。
- [x] 5.3 实现固定 world 下的头像读取 endpoint，流式返回 WebP，设置正确 `Content-Type`、`X-Content-Type-Options: nosniff`、ETag 和缓存头，不暴露 bucket、object key 或存储凭据。
- [x] 5.4 为无头像、对象缺失、Storage 暂时异常和维护移除提供稳定默认头像回退，验证 observer、workspace 和公开成员页不会因此失败。
- [x] 5.5 添加 workspace/observer 集成测试，覆盖本人上传、不能修改他人、pending 成员可管理本人头像、staff 无 Member 不可操作、维护移除、公开读取和默认回退。

## 6. 当前资产一致性与永久附件隔离

- [x] 6.1 实现要求显式 world 且默认 `--dry-run` 的头像一致性命令，报告数据库引用对象缺失、头像前缀无引用对象、超过 24 小时临时对象以及可选 size/SHA-256 不符。
- [x] 6.2 增加显式清理模式，只删除已证明无当前引用且属于当前 world 头像/临时前缀的对象；测试无法通过参数、恶意 key 或配置访问未来永久附件前缀。
- [x] 6.3 添加结构边界测试，确保 `core.file_processing` 和通用 Storage 写入原语不导入 `MemberPublicProfile`，头像删除 gateway 不被未来 `core.attachments` 默认复用。
- [x] 6.4 记录未来二次开发接口：永久附件复用识别、处理、哈希、随机 key 和 Storage 原语，但新增真实业务外键、只追加版本、冻结/密封/归档及只读永久一致性审计。

## 7. 文档同步与验证

- [x] 7.1 更新 `../bigapple-docs/docs/architecture/database-schema.md`，记录 `MemberPublicProfile` 头像字段、当前资产语义及 `avatar_url` 移除。
- [x] 7.2 更新 `../bigapple-docs/docs/architecture/overview.md`，说明文件处理、Storage gateway、头像服务、world 隔离和未来永久附件边界。
- [x] 7.3 更新成员工作台相关产品文档以及 `../bigapple-docs/docs/development/setup.md`，说明头像格式/限制、OCI S3 兼容配置、私有 bucket、存储探针和一致性命令。
- [x] 7.4 确认没有新增 `/api/v0.1/` 路径或 payload，因而无需修改 technical contracts；若实施中出现公开 API 需求，先停止实现并更新 contracts。
- [x] 7.5 运行 core、workspace、observer、world 隔离的最小相关测试以及完整本地回归，并执行 `scripts/check_project.py`、`manage.py check`、migration dry-run 和 `git diff --check`。
- [x] 7.6 按规格逐项验收格式识别、WebP 重编码、元数据剥离、替换失败回退、并发替换、默认头像、未授权修改、OCI 存储和永久前缀防删除，并记录结果。

### 7.6 验收记录

- 通过：Docker Linux 最终镜像包含 Pillow、Magika、django-storages 和 boto3。
- 通过：真实 Magika 识别与 Pillow WebP 重编码链路输出 `512 × 512` 静态 WebP。
- 通过：在完整解码前执行边长和总像素限制，超限输入不会调用 `load()`。
- 通过：WebP 输出元数据剥离、透明通道、替换失败回退、默认头像、未授权修改和永久前缀防删除测试。
- 通过：头像 URL 随 `avatar_updated_at` 变化，有效头像使用 immutable 缓存，默认或故障回退仅短期缓存。
- 通过：最终镜像相关测试 58/58、完整回归 1126/1126、存储命令测试 3/3。
- 通过：使用真实 OCI 私有 bucket 和部署凭据执行 `probe_avatar_storage`，Put、Head/exists、size、Get 内容校验和 Delete 清理全部成功。初次 Put 因新版 botocore 尾随 checksum 使用 `aws-chunked` 而返回 HTTP 501；按 OCI 官方兼容要求把请求和响应 checksum 策略设为 `when_required` 后通过。

## 8. World runtime 布局与重置清理

- [x] 8.1 移除 Storage alias 的 `current/temporary` location，把本地与 OCI alias 统一到同一根目录，并把 key 改为 `<world-id>/runtime/current-assets/avatars/` 与 `<world-id>/runtime/temporary/avatar-uploads/`；更新边界测试和运维文档。
- [x] 8.2 实现显式 world 的旧布局迁移命令：复制并校验现有头像、事务切换数据库 key、提交后删除旧对象；对失败补偿、幂等重跑、其它 world 和永久前缀增加测试。
- [x] 8.3 实现只接受安全 world runtime 前缀的清理服务并接入仿真重置：Storage 清理失败时不得 flush 数据库，成功后才继续 zero-start；测试证明真实 world、其它 world、control DB 和仿真归档均不受影响。
- [x] 8.4 在 `simulation0001` 真实 OCI 中迁移当前头像，验证新地址可读、旧对象已清理、runtime 清理 dry-run/执行边界正确，并运行相关测试、完整回归与 OpenSpec strict validation。
