# BusinessAgent：招投标文件智能生成系统

BusinessAgent 是一个面向招投标文档场景的 Web 应用。系统从 DOCX、DOC 或 PDF 招标文件中解析结构，定位资格、评分、时间和投标文件组成等关键要求，生成可人工确认的投标目录，再结合企业知识库完成素材匹配、章节初稿生成、质量检查和 Word 导出。

> 本仓库是脱敏后的公开版本。截图和示例名称均为虚构数据，不包含真实客户文档、企业证照、生产数据库、服务器地址或 API 密钥。

## 系统能力

- 解析 DOCX、DOC、文本型 PDF，并支持可选的扫描 PDF OCR 兜底。
- 构建章节树、完整文本、扁平章节列表和段落/表格锚点索引。
- 规则优先定位投标文件组成、目录表格、资格审查、评分办法和格式章节，结构不明确时再调用 LLM。
- 按资格、评分、时间、合同、废标、格式等维度并发抽取结构化要求。
- 从原文目录、索引表、响应文件组成或附件格式生成父子级目录。
- 在目录确认后，按公司隔离检索证照、业绩和技术母版章节。
- 对未命中固定素材的动态章节生成有依据的内容初稿。
- 通过规则执行合规性检查和跨章节事实一致性检查。
- 在编辑工作台预览、编辑、增删目录、调整素材并导出 DOCX。
- 支持可选的外部统一登录，并按 `creator_user_id` 隔离项目。

## 界面预览

### 新建项目

上传招标文件并选择本次项目使用的企业知识库。

![新建项目](docs/images/01-new-project.png)

### 企业知识库

管理证照、业绩、审计报告等图片/PDF 素材，以及可以无损复制到投标文件中的技术母版章节。

![企业知识库](docs/images/02-knowledge-base.png)

### 项目列表

查看当前用户创建的项目、处理状态、目录数量、风险统计和导出结果。

![项目列表](docs/images/03-projects.png)

### 目录确认与素材分配

在正式生成前调整目录层级，并检查每个章节匹配到的证照、技术章节或招标原文范本。

![目录确认](docs/images/04-outline-review.png)

### 编辑工作台

左侧保留目录层级，右侧展示固定素材或生成内容，并支持人工编辑和重新导出。

![编辑工作台](docs/images/05-workbench.png)

### 插入知识库资料

在章节编辑器中打开“插入资料”，可按当前公司知识库搜索和选择素材。“证书/图片”页签展示素材缩略图和资质信息，“技术方案”页签展示技术母版章节的层级路径、图片数、表格数和字数。

![插入证书和图片](docs/images/06-material-picker-certificates.png)

![插入技术方案](docs/images/07-material-picker-tech.png)

## 技术架构

| 层级 | 技术 | 主要职责 |
|---|---|---|
| 前端 | React 18、TypeScript、Vite、Tailwind CSS | 上传、进度、目录编辑、知识库和编辑工作台 |
| API | FastAPI、Pydantic | 项目、知识库、预览、渲染和用户隔离接口 |
| 工作流 | LangGraph + Python 异步编排 | 标题、要求抽取、目录生成及后续处理节点 |
| LLM | OpenAI-compatible API / Anthropic | 结构化抽取、弱结构定位、素材辅助匹配和内容生成 |
| 文档解析 | python-docx、PyMuPDF、可选 PaddleOCR | 解析段落、表格、标题、页码、书签和扫描页 |
| 数据库 | PostgreSQL、SQLAlchemy | 公司、证照和技术章节元数据 |
| 检索 | BM25 + 词法重叠 + 稳定哈希向量 | 对知识库候选章节进行轻量混合排序 |
| Word 输出 | python-docx + OOXML 块复制 | 保留表格、图片和技术母版结构并生成 DOCX |

当前实现不是自主多 Agent 系统，而是一条可追踪的固定工作流。LangGraph 直接运行上传阶段的 `title -> requirement_extractor -> composer`；目录人工确认后的素材匹配、RAG、内容生成和检查由后端任务顺序编排。

## 处理流程

```mermaid
flowchart LR
    A["上传招标文件"] --> B["文档解析"]
    B --> C["关键章节定位"]
    C --> D["标题与要求抽取"]
    D --> E["目录编排"]
    E --> F["人工确认目录"]
    F --> G["公司知识库素材匹配"]
    G --> H["构建 RAG 上下文"]
    H --> I["生成动态章节"]
    I --> J["合规与一致性检查"]
    J --> K["编辑工作台"]
    K --> L["DOCX 渲染"]
```

### 1. 上传与项目初始化

`POST /api/projects/upload` 接收文件、`company_id` 和投标单位名称，并生成 UUID 项目 ID。开启外部认证时，同时记录当前用户的 `creator_user_id`。

文件写入：

```text
data/upload/{project_id}_{original_filename}
```

任务摘要和最终结果写入：

```text
data/output/{project_id}.task.json
data/output/{project_id}.json
data/output/{project_id}_blank_bid.docx
```

### 2. 文档解析

入口位于 `src/tender_agent/parsing/docx_parser.py`。不同格式采用不同解析策略：

- DOCX：通过 `python-docx` 按原始顺序读取段落和表格。
- DOC：Windows 使用 Word COM，Linux 使用 LibreOffice 转换后再解析。
- PDF：通过 PyMuPDF 提取页面文本、表格、页码和书签；相邻页中表头一致的表格片段会尝试合并。
- 扫描 PDF：只有普通文本提取无有效内容时，才进入可选 OCR 兜底。

解析结果在当前任务内形成：

```python
ParsedDoc(
    file_name="tender.docx",
    full_text="提取出的完整文本",
    sections=[...],       # 树形章节
    flat_sections=[...],  # 同一批 Section 对象的前序扁平列表
    block_index=[...],    # 段落或整张表格的锚点索引
)
```

`block_index` 不是固定 Token 分块。DOCX 中通常一条记录对应一个非空段落或一张完整表格；PDF 中通常对应一行文本或一张表格。章节通过 `start_item_idx` 和 `end_item_idx` 与这些块建立位置关系。

### 3. 关键章节定位

定位器位于 `src/tender_agent/parsing/section_locator.py`，采用“确定性结构优先，LLM 兜底”的方式：

1. 检查明确的投标文件目录或响应文件组成。
2. 检查目录表格、文件索引表和附件格式表。
3. 检查权威的提交材料清单和正文组成说明。
4. 结构证据足够时直接返回章节引用，不调用 Locator LLM。
5. 结构不可靠时，仅把章节标题树交给 LLM 判断资格、评分、格式等内容位于哪些章节。

LLM 返回的是解析器内部生成的 `section_id`。随后 `assemble_section_content()` 回到内存中的 `ParsedDoc.flat_sections` 查找该 ID，恢复对应 `Section.content`、子章节内容和锚点；不是重新读取数据库，也不是让 LLM 根据标题直接生成投标目录。

### 4. 标题与招标要求抽取

标题节点先从文件名、首页和文档头部提取项目名称、项目编号、采购人等字段，仅在字段缺失时调用 LLM 补充。

要求抽取器按维度选择输入并执行小批次结构化抽取：

- `file_composition`：投标文件组成、目录和附件格式。
- `qualification_review`：资格审查和必备证明。
- `technical_scoring`：技术评分项、分值和高分要求。
- `base_timeline`：报名、答疑、投标、开标和服务期限。
- `contract_terms`：合同履约、付款和服务要求。
- `invalidation`：废标、无效投标和否决条款。
- 其他价格、格式和材料要求。

内部使用 `asyncio.gather` 进行按维度和批次的 Map-Reduce 式处理，超时批次可继续拆分；最终由 Python 完成去重、锚点补全和 Pydantic 校验。该 Map-Reduce 发生在一个 LangGraph 节点内部，不是 LangGraph 的动态 `Send` 子图。

### 5. 目录编排

Composer 从以下证据中选择最可靠的一种：

- 招标文件明确给出的目录。
- 投标文件组成或响应文件清单。
- 目录/索引表格。
- 投标文件格式章节中的表单层级。

程序将扁平条目恢复成父子节点，并保留来源章节和锚点。没有可靠来源时不会让模型自由编造一套目录，而是进入人工检查。

### 6. 人工确认目录

系统在 `outline_review` 状态暂停。用户可以重命名、排序、增加或删除节点。目录变化后，旧素材映射、RAG 上下文、生成内容和检查结果都会失效，需要重新匹配。

这是 Human-in-the-loop 边界，但当前通过 API 状态和前端交互实现，不依赖 LangGraph checkpointer 或 `interrupt()`。

### 7. 素材匹配

`material_mapper.py` 先把确认后的目录展开到叶子节点，然后加载当前公司的：

- 证书分类和证书记录。
- 技术母版章节索引。
- 招标原文中的固定格式或表单证据。

确定性的分类映射和精确 ID 映射优先锁定，只有无法可靠判断的节点才进入小批次 LLM 辅助匹配。后处理会校验数据库 ID、公司范围并去除重复素材。

### 8. RAG 上下文

当前检索不是 embedding + pgvector。候选排序为：

```text
BM25 70% + 词法重叠 20% + 稳定哈希向量余弦 10%
```

已明确分配的证书 ID 或技术章节 ID 会直接查询 PostgreSQL；检索排序主要用于给章节补充候选事实。知识库规模较小时该方案部署简单、结果可复现；同义表达较多或数据规模增大时，建议升级为真实 embedding 检索。

### 9. 内容生成

内容生成并不重写所有章节：

- 营业执照、证书图片等章节交给证书渲染器。
- 技术母版章节按 `section_id` 复制原 DOCX OOXML 块。
- 招标文件自带表单或固定格式直接复制原文块。
- 只有没有完整固定素材的动态章节才由 LLM 生成初稿。

生成提示会注入项目锁定事实、对应招标要求和 RAG 事实，降低项目名、编号、采购人、服务期等字段在不同章节中漂移的风险。

### 10. 合规与一致性检查

当前检查器是确定性规则引擎，不依赖 LLM：

- 合规检查：必填章节、资格要求、材料覆盖、P0 废标条款、占位符和空正文。
- 一致性检查：公司名、项目编号、金额、期限、人员数量、日期顺序和关键岗位冲突。

检查结果用于工作台提示，不会自动改写章节。

### 11. 编辑与 Word 渲染

编辑工作台允许人工修改章节、插入资料、增删目录和重新匹配素材。渲染器根据每个节点的 `render_plan` 选择：

- 复制招标原文模板块。
- 插入证书图片或 PDF 页面。
- 复制技术母版的原始 OOXML 段落、表格和图片。
- 渲染人工编辑或 LLM 生成的 HTML/文本。
- 对确实无内容的节点保留显式人工补充提示。

## 项目结构

```text
BusinessAgent/
├─ assets/templates/
│  └─ master_template.docx           # 最终投标文件封面与样式母版
├─ data/
│  ├─ knowledge/
│  │  └─ models.py                   # PostgreSQL ORM 模型
│  ├─ upload/                        # 运行时上传文件，Git 忽略
│  ├─ output/                        # 项目 JSON 和 DOCX，Git 忽略
│  └─ storage/                       # 预览/临时存储，Git 忽略
├─ docs/images/                      # README 脱敏截图
├─ frontend/                         # React + TypeScript + Vite
├─ scripts/                          # 知识库导入与迁移脚本
├─ src/
│  ├─ db/create_tables.py            # PostgreSQL 建表入口
│  └─ tender_agent/
│     ├─ api/                        # FastAPI 与可选外部认证
│     ├─ parsing/                    # 文档解析、章节定位
│     ├─ understanding/              # 要求、目录、素材、RAG、生成、检查
│     ├─ knowledge/                  # 证书导入和 DOCX 章节复制
│     ├─ rendering/                  # DOCX 渲染
│     └─ llm/                        # 模型网关和 Provider
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 数据存储

### PostgreSQL 表

模型定义在 `data/knowledge/models.py`。

| 表 | 用途 | 关键字段 |
|---|---|---|
| `companies` | 公司/租户边界 | `id`、`name`、`is_default`、`is_active` |
| `certificates` | 证照、业绩、审计报告等素材元数据 | `company_id`、`scope`、`category`、`file_path`、`expire_date` |
| `template_sections` | 技术母版章节索引 | `chapter_id`、`full_path`、`start_block_idx`、`end_block_idx` |
| `master_documents` | 母版版本兼容/预留表 | `doc_type`、`file_path`、`version`、`is_current` |

`master_documents` 目前不是渲染主链路的必需表。最终封面母版直接读取 `assets/templates/master_template.docx`，技术母版主要通过 `template_sections` 和磁盘 DOCX 定位。

项目任务当前不写入 PostgreSQL，而是保存为 `data/output/*.task.json` 和 `data/output/*.json`。服务重启后可以恢复项目列表和已完成结果，但不会从处理中间节点自动续跑。

### 文件与数据库的关系

数据库保存元数据和相对路径，图片、PDF、技术母版 DOCX 仍保存在磁盘：

```text
data/knowledge/companies/{company_id}/certs/
data/knowledge/companies/{company_id}/master/技术文件.docx
data/knowledge/companies/{company_id}/imports/
data/knowledge/shared/
```

建议始终保存 `data/knowledge/...` 相对路径，并从项目根目录启动服务。迁移服务器时必须同时迁移 PostgreSQL 数据和知识库实体文件。

## Word 母版

公开仓库提供一份通用母版：

```text
assets/templates/master_template.docx
```

支持以下占位符：

| 占位符 | 渲染值 |
|---|---|
| `{{ project_name }}` | 项目名称 |
| `{{ purchaser_name }}` | 采购人/招标人 |
| `{{ doc_type }}` | 投标文件或报价文件类型 |
| `{{ company_name }}` | 投标单位名称 |
| `{{ submission_date }}` | 生成日期 |

替换母版时请注意：

1. 保留占位符的完整文本，不要拆成多个不同格式的 Word Run。
2. 可以调整页边距、页眉页脚、字体和封面版式。
3. 不要把真实公司证照或客户项目写入公开母版。
4. 替换后至少执行一次完整导出，检查目录、分页、表格宽度和图片。

技术母版不是这个封面文件。技术母版通过知识库页面上传，系统扫描标题层级和块索引后写入 `template_sections`，渲染时再复制对应 OOXML 块。

## 环境要求

- Python 3.10
- Node.js 18+
- PostgreSQL 14+
- npm
- Linux 解析 `.doc` 或生成 DOCX 预览时建议安装 LibreOffice
- 可用的 OpenAI-compatible 或 Anthropic 模型接口

## 快速开始

### 1. 安装后端依赖

```bash
conda create -n business-agent python=3.10 -y
conda activate business-agent
pip install -r requirements.txt
```

### 2. 创建 PostgreSQL 数据库

先进入 PostgreSQL：

```bash
sudo -u postgres psql
```

创建用户和数据库，密码请自行替换：

```sql
CREATE USER business_agent WITH PASSWORD 'replace-with-a-strong-password';
CREATE DATABASE business_agent OWNER business_agent;
\q
```

Windows 已有 PostgreSQL 时，也可以通过 pgAdmin 执行相同 SQL。

### 3. 配置环境变量

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少填写：

```dotenv
DEFAULT_LLM_PROVIDER=token_plan
TOKEN_PLAN_API_KEY=your-api-key
TOKEN_PLAN_BASE_URL=https://your-openai-compatible-endpoint/v1
TOKEN_PLAN_MODEL_NAME=your-model-name

DATABASE_URL=postgresql://business_agent:your-password@127.0.0.1:5432/business_agent

EXTERNAL_AUTH_ENABLED=false
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

不要提交 `.env`。如果凭据曾经进入 Git 历史，仅删除当前文件不够，还需要立即轮换凭据并清理历史。

### 4. 创建数据库表

在项目根目录执行：

```bash
export PYTHONPATH=src:.
python src/db/create_tables.py
```

Windows PowerShell：

```powershell
$env:PYTHONPATH="src;."
python src/db/create_tables.py
```

成功时输出：

```text
Database tables created successfully.
```

检查表：

```bash
psql "postgresql://business_agent:your-password@127.0.0.1:5432/business_agent" -c "\dt"
```

`Base.metadata.create_all()` 适合首次建表，不会自动修改已有字段类型。生产环境发生模型变更时应使用 Alembic 或人工迁移 SQL，不要依赖 `create_all()` 覆盖旧表结构。

### 5. 启动后端

```bash
python -m uvicorn tender_agent.api.main:app \
  --host 127.0.0.1 \
  --port 8001 \
  --app-dir src \
  --reload
```

健康检查：

```bash
curl http://127.0.0.1:8001/api/health
```

后端启动时还会执行 `Base.metadata.create_all()` 并创建一个脱敏的默认公司 `demo-company`。正式使用时可以在“公司管理”页面新建公司并设置默认公司。

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://localhost:5173/business-agent/
```

开发服务器会把 `/business-agent/api` 代理到 `http://127.0.0.1:8001/api`。

## 初始化知识库

### 证照和商务素材

在“知识库”页面可以：

- 上传单张图片或 PDF，并填写分类、名称、子分类和有效期。
- 上传带标题层级的证书合集 DOCX，批量提取标题下图片。
- 按公司专属或全公司共享范围保存素材。

### 技术母版

上传 DOCX 后，系统会：

1. 读取 Word 标题层级。
2. 记录每个章节的 `chapter_id`、`full_path` 和父子关系。
3. 统计文本、图片和表格数量。
4. 保存原 DOCX 块的 `start_block_idx` 和 `end_block_idx`。
5. 将索引写入 `template_sections`。

后续匹配到该章节时，渲染器从原技术母版复制对应 OOXML 块，而不是只复制纯文本。

### 历史投标文件

`POST /api/knowledge/history/import` 可以导入历史文档章节作为检索候选。公开仓库不提供任何真实历史文档，请使用自有且有权处理的材料。

## 外部统一登录与项目隔离

独立部署默认关闭外部认证：

```dotenv
EXTERNAL_AUTH_ENABLED=false
EXTERNAL_AUTH_DEV_USER_ID=local-dev
```

接入已有统一登录系统时配置：

```dotenv
EXTERNAL_AUTH_ENABLED=true
EXTERNAL_AUTH_COOKIE_NAME=External-Auth-Token
EXTERNAL_AUTH_GETINFO_URL=https://sso.example.com/api/getInfo
EXTERNAL_AUTH_TIMEOUT_SECONDS=8
EXTERNAL_AUTH_CACHE_TTL_SECONDS=120
```

后端从当前请求的 Cookie 读取 Token，调用用户信息接口并提取 `userId`。用户信息按 Token 哈希短时缓存，不执行后台轮询。项目创建、列表、详情、编辑、下载和删除都会校验 `creator_user_id`。

如果主系统和 BusinessAgent 不同域，浏览器通常不会自动携带主系统 Cookie。推荐部署到同一主域名下的路径，或改为由可信网关注入经过签名的用户身份。

## 生产部署示例

### 构建前端

```bash
cd frontend
npm ci
npm run build
```

默认生产基础路径为：

```text
/business-agent/
```

如果需要其他路径，请同步修改 `frontend/vite.config.ts` 的 `base` 和开发代理前缀，然后重新构建。

### Nginx

假设项目部署在 `/opt/business-agent`，后端监听 `127.0.0.1:8001`：

```nginx
location = /business-agent {
    return 301 /business-agent/;
}

location ^~ /business-agent/api/ {
    proxy_pass http://127.0.0.1:8001/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 1800s;
    proxy_send_timeout 1800s;
    client_max_body_size 200M;
}

location ^~ /business-agent/ {
    alias /opt/business-agent/frontend/dist/;
    try_files $uri $uri/ /business-agent/index.html;
}
```

修改后检查并重新加载 Nginx：

```bash
sudo nginx -t
sudo nginx -s reload
```

只有 Nginx 配置变化时才需要 reload；修改 React 代码只需重新执行 `npm run build`，修改 Python 或 `.env` 需要重启后端。

## 常用 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/projects/upload` | 上传招标文件并创建任务 |
| `GET` | `/api/projects/{id}/status` | 查询处理进度 |
| `GET/PUT` | `/api/projects/{id}/outline` | 获取或保存目录 |
| `POST` | `/api/projects/{id}/remap-materials` | 重新匹配素材并生成内容 |
| `PUT` | `/api/projects/{id}/sections/{node_id}` | 保存章节正文 |
| `POST` | `/api/projects/{id}/render` | 渲染 DOCX |
| `GET` | `/api/projects/{id}/download` | 下载 DOCX |
| `GET/POST` | `/api/companies` | 查询或创建公司 |
| `GET` | `/api/knowledge/summary` | 知识库统计 |
| `POST` | `/api/knowledge/certificates/upload` | 上传证照素材 |
| `POST` | `/api/knowledge/tech-master/upload` | 上传并扫描技术母版 |

完整接口可在后端启动后访问：

```text
http://127.0.0.1:8001/docs
```

## 验证

后端静态检查：

```bash
python -m compileall -q src data scripts
```

前端构建：

```bash
cd frontend
npm ci
npm run build
```

最小验收流程：

1. 创建 PostgreSQL 表并启动前后端。
2. 新建一个测试公司。
3. 上传测试证照和技术母版，确认知识库可以预览。
4. 上传一份无敏感信息的招标文件。
5. 确认目录，检查素材匹配和生成章节。
6. 在工作台修改正文并导出 DOCX。
7. 检查封面占位符、目录层级、表格、图片和分页。

## 当前边界

- 当前 RAG 不是 embedding/pgvector 语义检索。
- 没有 LangGraph checkpointer，服务重启后不会从处理中间节点续跑。
- PDF 复杂双栏、跨页断句和扫描表格仍可能需要人工校对。
- 合规和一致性检查只生成报告，不会自动修复章节。
- 项目状态保存在本地 JSON，适合单机或受控内部部署；多实例部署需要持久任务队列和共享状态存储。

## 公开仓库安全清单

提交前请确认：

- 没有 `.env`、数据库导出、日志、Token 或私钥。
- 没有 `data/knowledge` 下的真实证照、母版或历史文档。
- 没有 `data/upload` 和 `data/output` 运行结果。
- 没有 `frontend/node_modules`、`frontend/dist` 和 Python 缓存。
- README 截图只使用虚构项目和示例公司。
- 仓库是无敏感历史的新仓库，而不是直接把内部仓库改为公开。

本项目处理的招投标文件通常包含商业秘密、个人信息和证照材料。部署者应自行完成访问控制、备份、加密、审计和数据留存策略。
