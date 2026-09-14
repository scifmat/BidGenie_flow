# BidGenie Flow

版本：1.8.2（变更记录见 README.md）

***

## 1. 项目定位

本项目是基于 TraeCode 的投标文件技术方案自动化撰写工作流，依托 TraeCode 的 Agent 能力，配合自定义 Subagents、Hooks、Skills、MCP 等基础配置，实现从招标文件上传到技术方案导出的全流程自动化。

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

| 阶段  | 流程名称 | 责任人                               | 主要产出                                             |
| --- | ---- | --------------------------------- | ------------------------------------------------ |
| 阶段一 | 文件上传 | 用户 + Agent                        | 项目工作空间、转换并重命名后的 .md 文件、metadata.json             |
| 阶段二 | 文件分析 | Agent（编排）+ extract-info-agent（执行） | 关键信息提取文件（9类）、验证报告                                |
| 阶段三 | 信息补充 | Agent + 用户                        | metadata.json、Supplementary\_info.md             |
| 阶段四 | 大纲编写 | outline-agent + 用户                | outline.json、outline.md、目录结构                     |
| 阶段五 | 正文撰写 | writer-agent                      | 各章节正文 .md 文件、summary\_report.md                  |
| 阶段六 | 内容审查 | Agent（编排）+ reviewer-agent（AI审查执行） | optimization\_suggestions.md、ai\_review\_\*.json |
| 阶段七 | 内容优化 | optimizer-agent + 用户              | 优化后的正文、optimization\_report.md                   |
| 阶段八 | 合并导出 | Agent（主控直接执行）                     | merged\_proposal.md、技术方案.docx                    |

***

## 3. Agent 定义

### 3.1 主 Agent

**身份**：投标文件技术方案自动化撰写工作流主控 Agent

**职责**：

- 维护整体流程（TodoWrite）
- 协调项目工作流程
- 与用户交互
- 调用其他 Subagents 完成项目任务

### 3.2 Subagents

| Subagent           | 职责                                         | 所属阶段 |
| ------------------ | ------------------------------------------ | ---- |
| extract-info-agent | 从招标文件中提取关键信息，存储到 extraction\_file/         | 文件分析 |
| outline-agent      | 根据评分标准编写技术方案大纲                             | 大纲编写 |
| writer-agent       | 根据大纲和素材撰写技术方案正文                            | 正文撰写 |
| reviewer-agent     | 执行 3 维度 AI 审查（内容完整性、评分点响应、技术语言规范），生成审查结果文件 | 内容审查 |
| optimizer-agent    | 根据审查结果优化技术方案内容                             | 内容优化 |

### 3.3 Agent 协作机制

- 所有 Subagent 由主 Agent 统一协调调度
- Subagent 之间通过文件系统传递数据，不直接调用
- 流程按顺序执行，每个阶段完成后更新 metadata.json 的"项目状态"字段

### 3.4 Skills

| Skill                   | 职责                                                                                                                                                                                                                                                                     | 所属阶段 |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| file\_conversion        | 将招标文件（.doc/.docx/.pdf）转换为 Markdown，创建工作空间和初始 metadata.json，提供批量重命名和关键信息回填功能                                                                                                                                                                                            | 文件上传 |
| document\_parsing       | 主控Agent协调子智能体提取信息，创建目录结构，校验文件，校验元数据一致性，更新项目状态                                                                                                                                                                                                                          | 文件分析 |
| information\_supplement | 确认标段与字数并回填metadata.json，生成Supplementary\_info.md模板，分5组收集投标人补充信息，执行完整性校验                                                                                                                                                                                                | 信息补充 |
| outline\_writing        | 主控Agent调用，用于阶段四大纲编写——校验输入文件、校验outline.json结构完整性，生成outline.md，生成proposal\_file目录结构，更新项目状态                                                                                                                                                                               | 大纲编写 |
| technical\_writing      | 主控Agent调用，用于阶段五正文撰写——读取大纲和素材，构建任务队列，调度writer-agent撰写正文，统计字数，执行质量自查，生成summary\_report.md，更新项目状态                                                                                                                                                                         | 正文撰写 |
| review\_optimization    | 主控Agent调用，用于阶段六内容审查——读取审查素材，执行脚本审查（字数、图表、章节结构），调度reviewer-agent执行AI审查（内容完整性、评分点响应、技术语言规范），智能规划AI审查任务优先级，汇总审查结果，生成optimization\_suggestions.md，更新项目状态                                                                                                                   | 内容审查 |
| content\_optimization   | 主控Agent调用，用于阶段七内容优化——读取阶段六审查报告，按节点分组调度optimizer-agent执行分级优化（严重→重写、一般→补充、建议→微调），执行二次验证（复用阶段六脚本+AI审查能力），生成optimization\_report.md，与用户进行人工审查交互（最多3次循环），锁定正文文件，更新项目状态                                                                                                      | 内容优化 |
| merge\_export           | 主控Agent调用，用于阶段八合并导出——校验前置条件（proposal\_files\_locked），获取outline.json深度优先合并顺序，生成chart\_id到图题编号的映射，主控Agent直接执行合并（merge\_proposal）、渲染（render\_mermaid.py）、Word转换（md\_to\_docx.py）（Mermaid→PNG三级降级、Markdown合并、Word转换+自动编号+样式模板），生成merge\_report.md，更新项目状态为"合并导出完成"，通知用户导出完成 | 合并导出 |

***

## 4. 关键文件说明

| 文件                           | 作用                                                | 更新时机                 |
| ---------------------------- | ------------------------------------------------- | -------------------- |
| metadata.json                | 项目元数据（项目名称、编号、采购方式、是否分标段、项目标段数、当前需撰写标段、预期总字数、状态等） | 文件上传阶段创建，后续阶段更新状态和字段 |
| Supplementary\_info.md       | 用户补充的投标人信息（基本信息、资质、人员、设备、荣誉、其他）                   | 信息补充阶段               |
| outline.json                 | 大纲结构定义（标题、层级、node\_id、字数、图表定义等）                   | 大纲编写阶段               |
| outline.md                   | 大纲审查文件（人类可读的 Markdown 格式大纲）                       | 大纲编写阶段               |
| summary\_report.md           | 正文撰写完成报告                                          | 正文撰写阶段               |
| optimization\_suggestions.md | 审查报告及优化建议                                         | 内容审查阶段               |
| optimization\_report.md      | 优化完成报告                                            | 内容优化阶段               |
| merged\_proposal.md          | 合并后的完整 Markdown 文档                                | 合并导出阶段               |
| merge\_report.md             | 合并导出报告                                            | 合并导出阶段               |

***

## 5. 项目结构

```
BidGenie_flow/
  ├── .trae/
  │   ├── hooks.json           # Hooks 配置文件
  │   ├── mcp.json             # MCP 配置文件
  │   ├── agents/              # Subagents 存放目录
  │   │   ├── extract-info-agent.md # 信息提取子智能体
  │   │   ├── outline-agent.md    # 大纲编写子智能体
  │   │   ├── writer-agent.md     # 正文撰写子智能体
  │   │   ├── reviewer-agent.md   # 内容审查子智能体
  │   │   └── optimizer-agent.md  # 内容优化子智能体（阶段七新增）
  │   ├── hooks_scripts/       # Hooks 执行脚本
  │   │   └── session_start.py # 会话开始时注入规则提示
  │   ├── rules/               # 规则文档目录
  │   │   ├── assistive_tools_rles.md  # 辅助工具使用规则
  │   │   ├── longtext_reading_rules.md # 长文本读取规则
  │   │   ├── writing_rules.md         # 正文撰写规则
  │   │   ├── anti_ai_writing_rules.md # 反AI写作痕迹规则
  │   │   ├── review_rules.md          # 内容审查规则
  │   │   ├── optimization_rules.md    # 内容优化规则（阶段七新增）
  │   │   └── export_rules.md          # 合并导出规则（阶段八新增）
  │   ├── scripts/             # 辅助脚本目录
  │   │   ├── run_skill.py     # Skill 统一调用入口脚本
  │   │   ├── render_mermaid.py # Mermaid 渲染脚本（阶段八新增）
  │   │   └── md_to_docx.py    # Markdown 转 Word 脚本（阶段八新增）
  │   ├── utils/               # 工具类目录
  │   │   └── temp_manager.py  # 临时文件管理工具
  │   └── ai-operations.log    # AI 操作日志（自动生成）
  ├── .agents/                 # 自定义 Skills 目录
  │   └── skills/              # Skill 存放目录，按需创建具体 Skill
  │       ├── file_conversion/       # 文件转换 Skill
  │       ├── document_parsing/      # 文档解析 Skill
  │       ├── information_supplement/ # 信息补充 Skill
  │       ├── outline_writing/       # 大纲编写 Skill
  │       ├── technical_writing/     # 正文撰写 Skill
  │       ├── review_optimization/   # 内容审查 Skill
  │       ├── content_optimization/  # 内容优化 Skill（阶段七新增）
  │       └── merge_export/          # 合并导出 Skill（阶段八新增）
  ├── README.md
  ├── AGENTS.md
  └── bid_project/             # 招标项目工作空间根目录
      └── <时间戳>_<随机字符>/ # 动态命名的项目工作空间（格式：YYYYMMDD HHMMSS_abc123）
          ├── source_file/           # 转换后的招标文件
          ├── extraction_file/       # 提取的关键信息
          ├── proposal_file/         # 技术方案章节和正文
          ├── review_file/           # 审查结果和优化报告
          ├── final_document_file/   # 最终文档
          ├── metadata.json          # 项目元数据
          └── Supplementary_info.md  # 投标人补充信息
```

***

## 6. 辅助工具说明

### 6.1 run\_skill.py — Skill 统一调用入口

**文件位置**：`.trae/scripts/run_skill.py`

**作用**：解决 `.agents` 目录无法直接作为 Python 包导入的问题，提供统一的命令行接口调用各 Skill 函数。

**JSON 参数传递优化**：

- 支持多环境（PowerShell/CMD/Bash）自动检测
- 支持 `--ps-mode` PowerShell 友好模式
- 支持 `*_file` 后缀参数从文件读取 JSON（解决 PowerShell 转义问题）
- 支持 6 级容错解析链：标准 → 反斜杠 → 反引号+反斜杠 → 反引号 → 单引号 → 补全键名
- 临时文件自动回退机制

**使用方法**：参考 `.trae/rules/assistive_tools_rles.md`

### 6.2 temp\_manager.py — 临时文件管理工具

**文件位置**：`.trae/utils/temp_manager.py`

**作用**：在系统临时目录下创建项目专属临时文件夹，用于存放转换过程中的中间文件，避免工作空间污染。

**使用方法**：参考 `.trae/rules/assistive_tools_rles.md`
