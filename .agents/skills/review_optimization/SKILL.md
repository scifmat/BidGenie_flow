---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Review Optimization Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: review_optimization
description: 主控Agent调用，用于阶段六内容审查——读取审查素材，执行脚本审查（字数、图表、章节结构），调度reviewer-agent执行AI审查（内容完整性、评分点响应、技术语言规范），汇总审查结果，生成optimization_suggestions.md，更新项目状态
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - review_optimization
  - reviewer_agent
  - phase6
department: All

# AI Model Compatibility
models:
  recommended:
    - glm-5.2
    - minimax-m3
  compatible:
    - glm-5.1
    - DeepSeek-V4-Pro
    - qwen-3.7-plus

# Skill Capabilities
capabilities:
  - file_reading
  - file_writing
  - script_review
  - ai_review_orchestration
  - review_result_summary
  - metadata_update

# Language Support
languages:
  - zh
---

# 内容审查 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段六（内容审查）的完整流程。主控 Agent 通过本 Skill 协调 reviewer-agent 子智能体完成技术方案正文的多维度审查，执行脚本审查（字数、图表、章节结构）和AI审查（内容完整性、评分点响应、技术语言规范），汇总审查结果并生成优化建议报告。

**重要**：本 Skill 不包含 AI 审查的具体逻辑（语义理解、内容分析等），这些智能工作由 **reviewer-agent 子智能体** 完成。本 Skill 仅提供文件操作、脚本审查和审查结果汇总能力。

**职责边界**：
- SKILL.md 指导主控 Agent：如何调用工具、如何调度 reviewer-agent、如何执行脚本审查、如何汇总审查结果
- reviewer-agent.md 指导 subagent：如何读取素材、如何执行AI审查、如何生成审查问题列表
- review_rules.md：定义审查标准和规则，供 reviewer-agent 参考

## 前置条件

- 项目状态为「正文撰写完成」
- proposal\_file 目录下已有完整的正文 .md 文件
- outline.json 已通过结构完整性校验
- summary\_report.md 已生成（阶段五产出）
- extraction\_file 目录下有完整的评审标准和技术要求文件
- metadata.json 已包含「当前需撰写标段」「预期总字数」字段

## 工作流程

```
步骤1: 确定工作空间，读取 metadata.json 确认项目状态为「正文撰写完成」
    ↓
步骤2: 调用 read_review_materials(workspace_path) 读取审查素材
    ↓
步骤3: 调用 script_review(workspace_path) 执行脚本审查（字数、图表、章节结构）
    ↓
步骤4: 调用 plan_ai_review_tasks(workspace_path) 智能规划 AI 审查任务（脚本→语义分流）
       - 基于脚本审查结果决定哪些 AI 审查任务需要执行、优先级如何
       - 字数严重不足 → 强制内容完整性审查
       - 图表问题 → 强制评分点响应审查
       - 结构问题 → 强制技术与语言规范审查
    ↓
步骤5: 调用 get_ai_review_status(workspace_path) 检测 AI 审查任务完成情况（中断恢复）
       - 已完成的任务跳过
       - pending/failed 任务调度 reviewer-agent 执行
    ↓
步骤6: 主控 Agent 调度 reviewer-agent 执行 AI 审查（按 plan_ai_review_tasks 推荐顺序）
       - 优先执行 high 优先级任务
       - reviewer-agent 完成后将结果写入 review_file/ai_review_*.json
       - 失败任务调用 update_ai_review_retry_count 增加重试计数
    ↓
步骤7: 调用 identify_failed_ai_reviews(workspace_path) 识别失败的 AI 审查任务
       - 失败且可重试的任务 → 重新调度 reviewer-agent
       - 重试次数耗尽的任务 → 记录为 exhausted，需人工介入
    ↓
步骤8: 调用 collect_review_results(workspace_path) 收集所有审查结果
    ↓
步骤9: 调用 classify_and_prioritize(review_results) 执行问题分级和优先级排序
    ↓
步骤10: 调用 generate_optimization_report(workspace_path, review_results) 生成优化建议报告
    ↓
步骤11: 调用 update_metadata_status(workspace_path, "内容审查完成") 更新项目状态
```

### 脚本+语义双轨制设计原则

**核心原则**：能使用脚本的就用脚本，用脚本效果不好的就使用语义检查。

| 审查维度 | 审查方式 | 适用场景 | 优势 | 局限 |
|----------|----------|----------|------|------|
| 字数符合度 | 脚本 | 字数统计、偏差计算 | 准确、快速 | 无法判断内容质量 |
| 图表正确性 | 脚本 | Mermaid 语法、数量匹配 | 准确、可量化 | 无法判断图表内容 |
| 章节结构 | 脚本 | 标题层级、格式规范 | 准确、规则化 | 无法判断逻辑连贯性 |
| 内容完整性 | 语义（AI） | content_plan 覆盖、同义/近义识别 | 智能理解、语义匹配 | 依赖 Agent 能力 |
| 评分点响应 | 语义（AI） | 评分标准响应充分性 | 智能判断、权重考量 | 依赖 Agent 能力 |
| 技术语言规范 | 语义（AI） | 逻辑漏洞、内容重复、风格一致性 | 智能分析、跨章节判断 | 依赖 Agent 能力 |

**智能分流规则**（基于脚本审查结果决定 AI 审查任务）：

| 脚本审查发现 | 触发的 AI 审查任务 | 优先级 | 原因 |
|--------------|---------------------|--------|------|
| 字数严重不足（<50%） | 内容完整性审查 | high | 字数严重不足可能意味着内容未覆盖要点 |
| 实际字数极少（<50字） | 内容完整性审查 | high | 极少字数几乎肯定未覆盖要点 |
| 字数偏差较大（<85%） | 内容完整性审查 | medium | 字数偏差可能影响内容完整性 |
| 图表数量不匹配 | 评分点响应审查 | high | 图表通常对应评分点 |
| 标题层级问题 | 技术与语言规范审查 | medium | 结构混乱可能伴随逻辑问题 |
| 无结构问题 | 技术与语言规范审查 | low（可选） | 可仅做抽样检查，减少 Agent 调用成本 |

***

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录
2. 读取 `metadata.json`，确认「项目状态」为「正文撰写完成」
3. 读取「当前需撰写标段」「预期总字数」字段，供后续步骤使用

**N 的确定**：根据 metadata.json 的「当前需撰写标段」字段确定标段编号 N：

- 「标段1」或「01」 → N=1
- 「标段2」或「02」 → N=2
- 不分标段时 N=1

### 步骤2：读取审查素材

调用 `read_review_materials(workspace_path)` 读取所有必要文件。

**读取文件列表**：

- proposal\_file/outline.json（大纲结构和节点信息）
- proposal\_file/\*.md（所有正文文件）
- proposal\_file/summary\_report.md（阶段五撰写报告）
- extraction\_file/packages\_file/package\_N/07\_Evaluation\_Criteria.md（评审标准，审查依据）
- extraction\_file/packages\_file/package\_N/09\_Technical\_Requirements.md（技术要求，审查依据）
- metadata.json（项目元数据）

**返回值处理**：

- `success=true`：继续步骤3
- `success=false`：向用户报告 `missing_files`，提示补充后重新执行本步骤

**关键规则**：此步骤仅做文件存在性校验和内容读取，不做智能分析（智能分析由 reviewer-agent 独立完成）。

### 步骤3：执行脚本审查

调用 `script_review(workspace_path)` 执行三项脚本审查：

**3.1 字数符合度审查**
- 统计各章节实际字数，与 outline.json 中 word\_count 对比
- **只下限不限上限策略**（与阶段五一致）：
  - 实际字数少于计划字数偏差 > 15%：一般问题（需补充内容）
  - 实际字数超过计划字数：仅记录，不限制（鼓励充分论述）
- 统计口径：正文段落、表格内容、列表内容、引用内容计入；标题、图表代码块、图题不计入

**3.2 图表正确性审查**
- Mermaid 代码块语法检查（使用简单规则检测）
- 图表数量与 outline.json 中 charts 数组长度匹配
- 图题格式规范检查（`*图 <层级编号>-<图表序号> <图题名称>*`）
- 图表与正文呼应检查（图表代码块附近是否有相关论述）

**3.3 章节结构审查**
- 标题层级连续性检查（不跳级）
- 标题格式检查（不添加数字编号）
- 标题层级超限检查（不超过大纲节点层级一级）
- 段落格式检查（段落之间空一行分隔）

**脚本审查特点**：机械性检查，准确度高，不需要语义理解。

### 步骤4：调度 reviewer-agent 执行 AI 审查

**审查任务拆分**：将 AI 审查分为三个独立任务，可并行执行：

| 任务 | 任务类型 | 审查目标 |
|------|----------|----------|
| 任务1 | content\_completeness（内容完整性审查） | 检查正文是否覆盖 content\_plan 中的所有要点 |
| 任务2 | scoring\_response（评分点响应审查） | 检查正文是否充分响应评审标准中的评分点 |
| 任务3 | technical\_language（技术与语言规范审查） | 检查逻辑漏洞、内容重复、语言风格一致性 |

**调度策略**：

| 策略项 | 说明 |
|--------|------|
| 并行度控制 | 最多同时启动 **3 个** reviewer-agent，避免资源过度消耗 |
| 任务拆分 | AI审查分为3个独立任务：内容完整性、评分点响应、技术语言规范 |
| 执行方式 | 三个AI审查任务可并行执行（无依赖关系） |
| 审查顺序 | 脚本审查先于AI审查执行（脚本审查结果可为AI审查提供参考） |
| 异常处理 | 单个审查任务失败不影响其他任务，失败任务记录到审查报告 |

**调用机制**：主控 Agent 通过 TraeCode 内置的 agent 调用机制（Task 工具，subagent\_type 选择对应类型），使用任务描述向 reviewer-agent 传递参数。

**传递参数**：

- workspace\_path（工作空间路径，绝对路径）
- task\_type（审查任务类型：content\_completeness / scoring\_response / technical\_language）
- output\_file（审查结果输出文件路径，临时文件）

**任务描述模板**：

```
请执行内容审查任务。
- 工作空间路径：<绝对路径>
- 审查任务类型：<task_type>
- 输出文件路径：<output_file>
请阅读 .trae/agents/reviewer-agent.md 了解你的职责和工作流程，然后：
1. 根据任务类型读取相关素材文件
2. 遵循 .trae/rules/review_rules.md 中的审查规则
3. 执行对应的AI审查
4. 将审查结果（JSON格式）写入指定的 output_file
```

**reviewer-agent 独立工作**：收到任务后，reviewer-agent 自行使用 Read 工具读取素材、执行审查、生成审查问题列表、写入临时文件。

**主控 Agent 监控**：主控 Agent 监控任务执行状态，处理异常情况，记录失败任务。

### 步骤5：收集审查结果

调用 `collect_review_results(workspace_path)` 收集所有审查结果。

**审查结果来源**：

1. 脚本审查结果（来自 SKILL.py 的 script\_review 函数）
2. AI审查结果（来自 reviewer-agent 生成的临时审查文件）

**审查结果格式**：统一为问题列表，每个问题包含：问题级别、问题描述、影响章节、优化建议。

### 步骤6：问题分级和优先级排序

调用 `classify_and_prioritize(review_results)` 执行问题分级。

**分级标准**：

| 问题级别 | 定义 | 判断条件 |
|----------|------|----------|
| **严重问题** | 影响方案完整性或评分结果 | 缺失要点≥2个、未响应评分点≥1个、逻辑漏洞、技术参数错误、技术方案不可行 |
| **一般问题** | 影响方案质量但不影响核心评分 | 缺失要点=1个、响应不充分、内容重复>20%、实际字数少于计划字数偏差>15%、Mermaid语法错误、图表数量不匹配、标题格式错误、标准规范引用错误 |
| **建议性问题** | 提升方案质量的改进建议 | 轻微遗漏、语言风格不一致、图题格式错误、段落格式不规范、表述不够专业 |

**字数偏差处理策略（与阶段五一致，只下限不限上限）**：
- 实际字数少于计划字数偏差 > 15%：一般问题，需补充内容
- 实际字数超过计划字数：仅记录，不限制（鼓励充分论述，不判定为问题）

**优先级排序**：严重问题 > 一般问题 > 建议性问题；同级别按影响章节排序。

### 步骤7：生成优化建议报告

调用 `generate_optimization_report(workspace_path, review_results)` 生成 `optimization_suggestions.md`。

**报告内容**：

- 审查完成时间
- 审查概览（总问题数、严重问题数、一般问题数、建议性问题数）
- 审查维度汇总（各维度问题统计）
- 问题分级列表（按优先级排序，含问题描述、影响章节、优化建议）
- 审查通过判定（是否需要优化、建议的优化策略）

**报告位置**：`bid_project/<工作空间>/review_file/optimization_suggestions.md`

### 步骤8：更新项目状态

调用 `update_metadata_status(workspace_path, "内容审查完成")` 更新项目状态。

***

## API Reference

### read\_review\_materials

**功能**：读取审查素材（大纲、正文、评审标准等）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'result': {
        'files': list,           # 已存在的文件相对路径列表
        'missing_files': list,   # 缺失文件相对路径列表
        'metadata': dict,        # metadata.json 关键字段
        'outline_path': str,     # outline.json 路径
        'package_n': str         # 标段编号
    }
}
```

### script\_review

**功能**：执行脚本审查（字数、图表、章节结构）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'review_type': 'script_review',
    'review_results': list,     # 问题列表
    'summary': {                # 汇总信息
        'word_count_issues': int,
        'chart_issues': int,
        'structure_issues': int
    }
}
```

### collect\_review\_results

**功能**：收集所有审查结果（脚本+AI）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'review_results': list,     # 合并后的审查结果列表
    'source_count': int         # 审查结果来源数量
}
```

### classify\_and\_prioritize

**功能**：执行问题分级和优先级排序

**参数**：
- `review_results`: list - 审查结果列表

**返回**：
```python
{
    'success': bool,
    'classified_results': {     # 分级后的结果
        'serious': list,
        'general': list,
        'suggestion': list
    },
    'sorted_issues': list,      # 排序后的问题列表
    'pass_judgment': str,       # 审查通过判定
    'suggestion_strategy': str  # 优化建议策略
}
```

### generate\_optimization\_report

**功能**：生成优化建议报告

**参数**：
- `workspace_path`: str - 工作空间路径
- `review_results`: list - 审查结果列表（可选，默认自动收集）

**返回**：
```python
{
    'success': bool,
    'report_path': str,         # 报告文件路径
    'stats': dict               # 报告统计信息
}
```

### update\_metadata\_status

**功能**：更新 metadata.json 项目状态

**参数**：
- `workspace_path`: str - 工作空间路径
- `status`: str - 项目状态值（默认：内容审查完成）

**返回**：
```python
{
    'success': bool,
    'status': str,
    'updated_fields': list
}
```

### get\_review\_status

**功能**：获取审查状态（用于中断恢复）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'review_status': str,           # pending/in_progress/completed
    'review_start_time': str,
    'review_completed_tasks': list, # 已完成的审查任务
    'review_failed_tasks': list     # 失败的审查任务
}
```

***

## run\_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 读取审查素材
python .trae/scripts/run_skill.py review_optimization read_review_materials --workspace_path "bid_project/test"

# 执行脚本审查
python .trae/scripts/run_skill.py review_optimization script_review --workspace_path "bid_project/test"

# 收集审查结果
python .trae/scripts/run_skill.py review_optimization collect_review_results --workspace_path "bid_project/test"

# 问题分级和优先级排序
python .trae/scripts/run_skill.py review_optimization classify_and_prioritize --workspace_path "bid_project/test"

# 生成优化建议报告
python .trae/scripts/run_skill.py review_optimization generate_optimization_report --workspace_path "bid_project/test"

# 更新项目状态
python .trae/scripts/run_skill.py review_optimization update_metadata_status --workspace_path "bid_project/test" --status "内容审查完成"

# 获取审查状态
python .trae/scripts/run_skill.py review_optimization get_review_status --workspace_path "bid_project/test"

# 检测 AI 审查任务完成情况（脚本+语义双轨制核心）
python .trae/scripts/run_skill.py review_optimization get_ai_review_status --workspace_path "bid_project/test"

# 智能规划 AI 审查任务（基于脚本审查结果）
python .trae/scripts/run_skill.py review_optimization plan_ai_review_tasks --workspace_path "bid_project/test"

# 识别失败的 AI 审查任务（中断恢复）
python .trae/scripts/run_skill.py review_optimization identify_failed_ai_reviews --workspace_path "bid_project/test"

# 更新 AI 审查重试计数
python .trae/scripts/run_skill.py review_optimization update_ai_review_retry_count --workspace_path "bid_project/test" --task_type "content_completeness" --increment 1
```

**注意**：optimization\_suggestions.md 由 SKILL.py 生成。AI 审查结果由 reviewer-agent 写入临时文件，SKILL.py 负责收集和汇总。

**返回格式**：JSON 格式

```json
{"success": true, "result": {...}}
```

***

## Error Handling

| 错误类型 | 处理方式 |
|----------|----------|
| metadata.json 不存在 | 提示用户先执行阶段一至五 |
| 项目状态非「正文撰写完成」 | 提示当前状态，引导用户从正确阶段继续 |
| outline.json 不存在 | 提示主控 Agent 先完成阶段四大纲编写 |
| 正文 .md 文件缺失 | 报告缺失文件列表，提示用户补充 |
| 评审标准文件缺失 | 报告缺失文件，提示用户检查阶段二产出 |
| reviewer-agent 调用失败 | 记录失败任务，继续其他任务，失败任务记录到审查报告 |
| 临时审查文件读取失败 | 跳过该来源，记录异常，继续收集其他结果 |
| 审查报告写入失败 | 检查目录权限，尝试重试 |
| 检查点恢复失败 | 提示用户检查 metadata.json 完整性 |

## Limitations

- reviewer-agent 调用依赖 TraeCode 的 Subagent 调度机制
- AI 审查（内容完整性、评分点响应、技术语言规范）由 reviewer-agent 完成
- SKILL.py 仅负责文件操作、脚本审查和审查结果汇总，无智能逻辑
- 最多同时启动 3 个 reviewer-agent，避免资源过度消耗
- 脚本审查先于 AI 审查执行，脚本审查结果可为 AI 审查提供参考
- 阶段六仅作审查，所有审查完成后统一进入阶段七优化
- 字数偏差处理策略与阶段五一致：只下限不限上限
- AI 审查结果存储在临时目录，由 collect\_review\_results 统一收集
- 用户交互依赖 TraeCode 内置的 AskUserQuestion 工具
