# BidGenie Flow

**版本号**：1.8.2
**发布日期**：2026-08-31

***

## 1. 项目定位

BidGenie Flow 是基于 TraeCode 的投标文件技术方案自动化撰写工作流，依托 TraeCode 的 Agent 能力，配合自定义 Subagents、Hooks、Skills、MCP 等配置，实现从招标文件上传到技术方案导出的全流程自动化。

**核心目标**：

- 提高投标文件技术方案的撰写效率
- 确保技术方案对招标文件评分标准的完整响应
- 规范技术方案的结构和内容质量
- 降低人工撰写的重复性工作和人为失误

***

## 2. 工作流程

### 2.1 总体流程

文件上传 → 文件分析 → 信息补充 → 大纲编写 → 正文撰写 → 内容审查 → 内容优化 → 合并导出

### 2.2 阶段说明

| 阶段 | 流程名称 | 责任人 | 主要产出 |
| --- | ---- | --------------------- | ------------------------------------ |
| 阶段一 | 文件上传 | 用户 + Agent | 项目工作空间、转换并重命名后的 .md 文件、metadata.json |
| 阶段二 | 文件分析 | Agent（编排）+ extract-info-agent（执行） | 关键信息提取文件（9类）、验证报告 |
| 阶段三 | 信息补充 | Agent + 用户 | metadata.json、Supplementary_info.md |
| 阶段四 | 大纲编写 | outline-agent + 用户 | outline.json、outline.md、目录结构 |
| 阶段五 | 正文撰写 | writer-agent | 各章节正文 .md 文件、summary_report.md |
| 阶段六 | 内容审查 | Agent（编排）+ reviewer-agent（AI审查执行） | optimization_suggestions.md、ai_review_*.json |
| 阶段七 | 内容优化 | optimizer-agent + 用户 | 优化后的正文、optimization_report.md |
| 阶段八 | 合并导出 | Agent（主控直接执行） | merged_proposal.md、技术方案.docx |

***

## 3. 交互节点

流程中需要在以下节点由您进行确认或输入，其余步骤由智能体自动完成：

| 节点 | 触发条件 | 您需要做的 | 后续流程 |
| ------- | -------- | ------------- | ------------------ |
| 确认标段 | 项目分标段时 | 选择需撰写的标段编号/名称 | 继续确认字数 |
| 确认字数 | 信息补充阶段 | 输入方案预期总字数 | 继续补充投标人信息 |
| 补充投标人信息 | 信息补充阶段 | 按模板依次补充6类信息 | 大纲编写 |
| 确认大纲 | 大纲编写完成 | 确认大纲/提出修改意见 | 正文撰写（确认）/修改大纲（不确认） |
| 人工审查 | 自动审查优化完成 | 确认通过/提出修改意见 | 合并导出（通过）/优化调整（不通过） |

***

## 4. 项目结构与产出

```
BidGenie_flow/
  ├── .trae/                   # TraeCode 配置目录
  ├── .agents/                 # Skills 目录
  ├── README.md                # 项目说明文档
  ├── AGENTS.md                # 项目智能体配置文档
  └── bid_project/             # 招标项目工作空间根目录
      └── <时间戳>_<随机字符>/ # 动态命名的项目工作空间（格式：YYYYMMDD HHMMSS_abc123）
          ├── source_file/           # 转换后的招标文件
          ├── extraction_file/       # 提取的关键信息
          ├── proposal_file/         # 技术方案章节和正文
          ├── review_file/           # 审查结果和优化报告
          ├── final_document_file/   # 最终文档（技术方案.docx 等）
          ├── metadata.json          # 项目元数据
          └── Supplementary_info.md  # 投标人补充信息
```

**主要产出文件**：

| 文件 | 说明 |
| ---------------------------- | ------------------------------- |
| metadata.json | 项目元数据（项目名称、编号、标段、预期总字数、状态等） |
| Supplementary_info.md | 您补充的投标人信息（基本信息、资质、人员、设备、荣誉、其他） |
| outline.md | 人类可读的大纲审查文件 |
| summary_report.md | 正文撰写完成报告 |
| optimization_suggestions.md | 审查报告及优化建议 |
| optimization_report.md | 优化完成报告 |
| merged_proposal.md | 合并后的完整 Markdown 文档 |
| merge_report.md | 合并导出报告 |
| 技术方案.docx | 最终交付的 Word 文档（位于 final_document_file/） |

***

## 5. 环境要求

- 操作系统：Windows 11 或更高版本（Linux未测试）
- TraeCode（需启用 Agent、Subagents、Hooks、MCP 能力）
- Python 3.x（运行辅助脚本）
- Node.js / mermaid-cli（合并导出阶段渲染 Mermaid 图表，安装说明见 `merge_export` Skill）
- 系统已安装 Chrome 或 Edge（Mermaid 渲染自动检测使用）

## 6. 使用方法

### 6.1 准备工作

1. 确认已安装所有依赖项（TraeCode、Python 3.x、Node.js 等）。
2. 打开 TraeCode 并加载 BidGenie Flow 项目目录。

### 6.2 发起撰写任务

3. 将招标文件及所有附件上传到项目目录。
4. 在输入框中 `#` 引用招标文件及附件，输入撰写指令，例如：
   > 请根据招标文件和附件，撰写技术方案。
5. 根据提示选择/确认标段（如项目分标段）。

### 6.3 配合交互节点

智能体执行过程中会在以下节点暂停，请及时处理：

| 节点 | 操作内容 |
|------|----------|
| 标段确认 | 选择要撰写的标段编号/名称 |
| 字数确认 | 输入方案预期总字数 |
| 补充投标人信息 | 按模板依次填写 6 类信息 |
| 确认大纲 | 审核大纲，确认通过或提出修改意见 |
| 人工审查 | 确认最终方案，通过后进入导出阶段 |

### 6.4 等待完成

交互节点处理完毕后，智能体将自动完成剩余工作，直至技术方案导出。

***

## 7. 配置变更记录

| 变更日期 | 变更类型 | 变更内容 | 影响范围 | 变更人 | 版本号 |
| ---------- | ---- | ----------- | ---- | ---- | ----- |
| 2026-07-17 | 新增 | 初始版本，搭建基础框架 | 全部 | 开发人员 | 1.0.0 |
| 2026-07-20 | 新增 | 创建 extract-info-agent 子智能体 | 文件分析阶段 | 开发人员 | 1.0.0 |
| 2026-07-21 | 优化 | metadata.json 字段重构：项目标段→项目标段数，方案总字数→预期总字数，新增是否分标段/当前需撰写标段字段；check_extraction_files 增加轻量级内容检查；两个 Skill 脚本同步更新 | 文件上传/文件分析阶段 | 开发人员 | 1.0.0 |
| 2026-07-21 | 优化 | metadata.json 初始字段优化：阶段一生成时是否分标段/项目标段数/当前需撰写标段设为空值；阶段二仅回填是否分标段/项目标段数；当前需撰写标段和预期总字数留待阶段三确认 | 文件上传/文件分析阶段 | 开发人员 | 1.0.0 |
| 2026-07-22 | 优化 | 阶段一增加关键信息回填步骤：Agent从招标文件提取项目编号/项目名称/项目类型/是否分标段/项目标段数并回填metadata.json；阶段二update_metadata_from_extraction改为一致性校验，不再覆盖阶段一已回填的字段 | 文件上传/文件分析阶段 | 开发人员 | 1.0.0 |
| 2026-07-22 | 新增 | 创建 information_supplement Skill（SKILL.md + SKILL.py），实现阶段三信息补充全流程：标段/字数确认回填、Supplementary_info.md 模板生成、5 组 AskUserQuestion 交互、章节更新与完整性校验；SessionStart hook 注入阶段三操作规范 | 信息补充阶段 | 开发人员 | 1.1.0 |
| 2026-07-24 | 新增 | 创建 outline_writing Skill（SKILL.md + SKILL.py），实现阶段四大纲编写辅助功能：输入文件校验、outline.json 结构完整性校验、outline.md 生成、proposal_file 目录结构生成、项目状态更新；创建 outline-agent.md 子智能体定义；SessionStart hook 注入阶段四详细操作规范 | 大纲编写阶段 | 开发人员 | 1.2.0 |
| 2026-07-24 | 新增 | 创建 technical_writing Skill（SKILL.md + SKILL.py，含 8 个函数：读取大纲素材、构建任务队列、字数统计、质量自查、生成报告、更新状态、检查点管理），实现正文撰写阶段的文件操作、任务队列管理和质量检查功能；创建 writer-agent.md 子智能体定义；创建 writing_rules.md 撰写规则文档；SessionStart hook 注入阶段五详细操作规范 | 正文撰写阶段 | 开发人员 | 1.3.0 |
| 2026-07-24 | 修复 | 修复 quality_self_check 函数中 Mermaid 图题检测的误报 bug：原代码仅检查代码块结束后紧接的下一行，未跳过空行，导致标准格式（代码块后空行再接图题）被误判为缺少图题；改为跳过空行查找第一个非空行进行图题匹配 | 正文撰写阶段 | 开发人员 | 1.3.0 |
| 2026-07-27 | 优化 | **run_skill.py JSON 参数解析修复**：重构 parse_json_arg 函数，提供多层容错解析（去除外围引号、修复 PowerShell 转义双引号、单引号替换、键名引号补全）；新增 read_json_from_file 函数支持 `_file` 后缀参数从文件读取 JSON；在文档中补充 PowerShell/CMD/Bash 三种终端环境下的正确调用方式说明 | 全部阶段（命令行调用） | 开发人员 | 1.3.1 |
| 2026-07-27 | 优化 | **outline-agent depends_on 字段生成**：在 outline-agent.md 中新增步骤 6.5「依赖关系识别与 depends_on 字段生成」，定义 3 条识别规则（兄弟节点顺序依赖、跨章节显式依赖、并列内容无依赖）、字段填写规范、循环依赖检测算法和依赖关系自检规则；更新步骤 8 写入前自检，增加 depends_on 字段完整性和循环依赖检查项 | 大纲编写阶段 | 开发人员 | 1.3.1 |
| 2026-07-27 | 优化 | **字数限制策略优化**：将字数控制策略从「±15% 双向限制」调整为「只下限不限上限」——字数不足（偏差 < -15%）标记为 `insufficient` 不合格需补充；字数超标（偏差 > +15%）标记为 `over_count` 合格仅作记录；更新 SKILL.py 中 WORD_COUNT_LOWER_THRESHOLD/WORD_COUNT_UPPER_THRESHOLD 常量、word_count_statistics 函数判定逻辑和 generate_summary_report 报告字段；同步更新 writing_rules.md 第五章和 writer-agent.md 步骤 5.3 | 正文撰写阶段 | 开发人员 | 1.3.1 |
| 2026-07-27 | 优化 | **正文内容完整性检查机制优化**：降低关键词匹配阈值（CONTENT_COVERAGE_THRESHOLD 从 80% 降至 50%）；引入语义检查兜底机制（关键词覆盖率在 50%-80% 之间时建议主控 Agent 进行语义检查，SEMANTIC_CHECK_TRIGGER_THRESHOLD=80%）；优化关键词提取逻辑（去除停用词、提取核心关键词、宽松匹配兜底）；更新 _check_content_completeness 函数实现三级判定 | 正文撰写阶段 | 开发人员 | 1.3.1 |
| 2026-07-27 | 修复 | **拓扑排序功能修复**：基于 depends_on 字段修复，新增 _topological_sort 函数实现 BFS 拓扑排序（同批次入度为 0 的节点可并行）；新增 _detect_cycle 函数使用 DFS 三色标记法检测循环依赖（发现循环自动回退到 DFS）；新增 _group_parallel_tasks_dfs 函数处理无依赖时的并行分组；增加无效依赖关系过滤逻辑（被依赖节点不存在时自动过滤并记录）；build_task_queue 返回 sort_strategy/has_dependencies/cycle_detected/invalid_depends 字段便于主控 Agent 决策 | 正文撰写阶段 | 开发人员 | 1.3.1 |
| 2026-07-27 | 优化 | **SessionStart hook 更新**：更新阶段五操作规范，移除「depends_on 字段可能不存在」的过时提示；补充字数控制策略说明（只下限不限上限）；补充内容完整性检查机制说明（关键词覆盖率 < 50% 判定为问题；50%-80% 建议语义检查兜底）；补充拓扑排序和循环依赖检测说明 | 正文撰写阶段 | 开发人员 | 1.3.1 |
| 2026-07-27 | 新增 | **阶段六内容审查开发**：创建 review_optimization Skill（SKILL.md + SKILL.py，含 7 个函数：读取审查素材、脚本审查、收集审查结果、问题分级排序、生成优化报告、更新项目状态、获取审查状态），实现"脚本审查（字数、图表、章节结构）+AI审查（内容完整性、评分点响应、技术语言规范）"混合策略；创建 reviewer-agent.md 子智能体定义（指导 subagent 执行 AI 审查）；创建 review_rules.md 审查规则文档（定义审查标准和问题分级机制）；更新 session_start.py 注入阶段六详细操作规范；采用三层架构（SKILL.md 指导主控 Agent，主控 Agent 调度 reviewer-agent，reviewer-agent.md 指导 subagent） | 内容审查阶段 | 开发人员 | 1.4.0 |
| 2026-07-28 | 优化 | **检查点恢复机制**：technical_writing SKILL.py 新增 identify_failed_nodes 函数（自动扫描叶子节点文件状态和字数情况，识别"文件缺失"或"字数严重不足（<50%）"的失败节点并更新 metadata.json 中的 failed_nodes 字段）；新增 update_retry_count 函数（管理失败节点重试计数，达到 MAX_RETRY_COUNT=2 时标记为 exhausted 需人工介入）；优化 build_task_queue 函数集成失败节点自动检测和优先重试编排（failed_nodes 中的节点优先排在任务队列最前，标记为 retry 状态；重试耗尽的节点标记为 exhausted 并从队列中排除）；新增 _reorder_with_retry_first 和 _topological_sort_with_retry 辅助函数；run_skill.py 新增 --node_id 和 --increment 命令行参数支持 | 正文撰写阶段 | 开发人员 | 1.5.0 |
| 2026-07-28 | 优化 | **AI 审查自动化（脚本+语义双轨制）**：review_optimization SKILL.py 新增 4 个函数：get_ai_review_status（自动检测 review_file/ai_review_*.json 文件完成情况，区分 pending/completed/failed 三种状态）、plan_ai_review_tasks（基于脚本审查结果智能规划 AI 审查任务，实现"能使用脚本的就用脚本，用脚本效果不好的就使用语义检查"原则）、identify_failed_ai_reviews（识别失败的 AI 审查任务，区分可重试和重试耗尽）、update_ai_review_retry_count（管理 AI 审查重试计数，达到 AI_REVIEW_MAX_RETRY=2 时标记为 exhausted）；更新 reviewer-agent.md 明确输出文件命名规则（ai_review_content.json/ai_review_scoring.json/ai_review_language.json）和主控 Agent 检测机制；更新 session_start.py 注入阶段五和阶段六新操作规范；run_skill.py 新增 --task_type 命令行参数支持 | 内容审查阶段 | 开发人员 | 1.5.0 |
| 2026-07-30 | 新增 | **阶段七内容优化开发**：创建 content_optimization Skill（SKILL.md + SKILL.py，含 12 个函数：读取优化输入、按节点分组问题、二次验证、生成优化报告、锁定文件、检查大纲变更、分组用户反馈、更新状态、获取优化状态、更新轮次、检查失败任务、管理重试计数），实现"按节点分组调度 + 分级优化 + 二次验证 + 用户审查循环（最多3次）"完整流程；创建 optimizer-agent.md 子智能体定义（指导 subagent 执行分级优化：严重→重写、一般→补充、建议→微调）；创建 optimization_rules.md 优化规则文档（定义分级处理标准、字数控制、格式规范、反 AI 味规则）；复用阶段六的 script_review 和 reviewer-agent 进行二次验证；更新 session_start.py 注入阶段七详细操作规范（阶段7A自动优化 + 阶段7B人工审查循环 + 中断恢复机制）；run_skill.py 新增 --round、--user_feedback、--issues/--issues_file、--target_node_ids/--target_node_ids_file、--optimization_records/--optimization_records_file 参数支持；采用三层架构（SKILL.md 指导主控 Agent，主控 Agent 调度 optimizer-agent，optimizer-agent.md 指导 subagent）；所有 12 个函数已基于现有工作空间测试通过 | 内容优化阶段 | 开发人员 | 1.6.0 |
| 2026-07-30 | 修复 | **run_skill.py epilog 转义修复**：修复 argparse epilog 帮助文本中 JSON 示例的花括号 `{}` 与 Python `.format()` 方法冲突导致 KeyError 的问题（如 `{"01_source.md":...}` 被误解析为格式占位符）；将所有字面量花括号转义为 `{{}}`，仅保留 `{env}` 和 `{env_hint}` 占位符 | 全部阶段（命令行调用） | 开发人员 | 1.6.0 |
| 2026-07-30 | 修复 | **content_optimization SKILL.py 修复**：修复路径注入变量名拼写错误（`_TRAAE_PATH` → `_TRAE_PATH`）；优化 group_issues_by_node 函数容错性（当部分文件缺失导致 read_optimization_inputs 返回 success=false 但已收集到 issues 时，允许继续分组而不阻断流程） | 内容优化阶段 | 开发人员 | 1.6.0 |
| 2026-08-02 | 新增 | **阶段八合并导出开发**：创建 merge_export Skill（SKILL.md + SKILL.py，含 7 个函数：前置条件校验、深度优先合并顺序、图表映射生成、合并报告生成、状态更新、导出状态获取、产出验证）；创建 merge-agent.md 子智能体定义（指导 subagent 执行合并/渲染/导出，含 RunCommand 权限调用脚本）；创建 export_rules.md 导出规则文档（定义合并规则、图表处理、图题编号、Word 自动编号、样式规范）；创建 render_mermaid.py 脚本（Mermaid 代码块渲染为 PNG，支持三级降级：保留代码块→占位图→文字描述）；创建 md_to_docx.py 脚本（Markdown 转 Word，应用样式模板：标题自动编号、正文宋体小四1.5倍行距、表格表头加粗灰底、图片居中80%宽度）；更新 session_start.py 注入阶段八详细操作规范（含中断恢复机制）；run_skill.py 新增 --export_stats/--export_stats_file、--export_file_path 参数支持；采用三层架构（SKILL.md 指导主控 Agent，主控 Agent 调度 merge-agent，merge-agent.md 指导 subagent） | 合并导出阶段 | 开发人员 | 1.7.0 |
| 2026-08-02 | 修复 | **阶段八职责归一化与增强**：1) merge-agent 移除 RunCommand 工具，仅负责合并/统计/生成中间文件（merged_proposal_raw.md、charts_inventory.json、merge_stats.json），render_mermaid.py 和 md_to_docx.py 改由主控 Agent 通过 RunCommand 调用；2) check_export_prerequisites 新增环境依赖预检（python-docx/Pillow 必需、mermaid-cli/python-markdown 可选），缺失时返回 warnings/errors；3) SKILL.py 新增 _count_words 统一字数统计口径函数（不计入标题/Mermaid代码块/图题/图片引用/表格分隔行），消除 merge-agent 与报告生成的字数统计偏差；4) generate_merge_report 参数化：export_stats 可选，缺失时自动从 merge_stats.json 和 _render_stats.json 汇总，自动扫描 final_document_file 目录获取文件大小，报告生成后回填 merge_report.md 自身大小；5) render_mermaid.py 占位图增强：不截断 chart_description，按 40 字符自动换行，图片高度自适应描述行数；6) 同步更新 SKILL.md、merge-agent.md、session_start.py 职责划分说明 | 合并导出阶段 | 开发人员 | 1.7.0 |
| 2026-08-02 | 优化 | **阶段八取消子智能体架构**：取消 merge-agent 子智能体，合并/统计/图表清单工作改由 SKILL.py 新增 merge_proposal 函数（含 _extract_mermaid_blocks 辅助方法）由主控 Agent 直接调用；render_mermaid.py 新增 --stats-output 参数直接写统计文件（规避 PowerShell stdout 重定向问题）；修复 _auto_collect_stats 读取 _render_stats.json 时未取 result 嵌套层导致报告图表统计为空的 bug；merge_proposal 记录合并耗时写入 merge_stats.json；export_rules.md 新增「字数统计口径」章节（8.5节）；删除 merge-agent.md；采用两层架构（SKILL.md 指导主控 Agent，主控 Agent 直接执行全部工作） | 合并导出阶段 | 开发人员 | 1.8.0 |
| 2026-08-02 | 优化 | **阶段八 Mermaid 真实渲染与耗时增强**：1) 安装 mermaid-cli（淘宝镜像源 npmmirror + PUPPETEER_DOWNLOAD_BASE_URL 镜像）实现 Mermaid→PNG 真实渲染，5 个图表全部成功（不再降级占位图）；2) render_mermaid.py 新增 _find_system_chrome 和 _create_puppeteer_config 方法，自动检测系统 Chrome/Edge 并通过 -p 参数指定，解决 Windows 下 Puppeteer Chromium 无法启动问题（错误码 3221225595 STATUS_STACK_BUFFER_OVERRUN）；3) _check_mmdc_available 和 mmdc 调用使用 shutil.which 解析 mmdc.CMD 完整路径（Windows .cmd 兼容）；4) 耗时精度提升：< 1 秒显示毫秒（如「10 毫秒」），>= 1 秒显示秒（如「28.2 秒」）；5) 报告耗时分别标注合并和渲染（如「合并 10 毫秒 + 渲染 28.2 秒」）；6) render_mermaid.py 新增渲染耗时统计（time.time()）写入 _render_stats.json 的 duration 字段；7) puppeteer 配置文件在 main() 末尾自动清理；8) SKILL.md 新增 mermaid-cli 安装说明（国内环境淘宝源 + Chromium 镜像）和系统 Chrome 自动检测说明 | 合并导出阶段 | 开发人员 | 1.8.1 |
| 2026-08-31 | 优化 | **文档职责分离**：将原 AGENTS.md 拆分为 README.md（使用者视角：项目定位、工作流程、交互节点、项目结构与产出、环境要求、配置变更记录）和 AGENTS.md（智能体视角：工作流程与责任人、Agent 定义与协作机制、Skills 表、关键文件说明、项目结构、辅助工具）；配置变更记录整体迁移至 README.md | 全部 | 开发人员 | 1.8.2 |
