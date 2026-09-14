---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Content Optimization Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: content_optimization
description: 主控Agent调用，用于阶段七内容优化——读取阶段六审查报告，按节点分组调度optimizer-agent执行分级优化（严重→重写、一般→补充、建议→微调），执行二次验证（复用阶段六脚本+AI审查能力），生成optimization_report.md，与用户进行人工审查交互（最多3次循环），锁定正文文件，更新项目状态
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - content_optimization
  - optimizer_agent
  - phase7
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
  - issue_grouping
  - optimization_orchestration
  - revalidation
  - user_interaction
  - file_locking
  - metadata_update

# Language Support
languages:
  - zh
---

# 内容优化 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段七（内容优化）的完整流程。主控 Agent 通过本 Skill 协调 optimizer-agent 子智能体完成技术方案正文的分级优化，执行二次验证（复用阶段六的脚本审查 + AI 审查能力），与用户进行人工审查交互，并在用户确认通过后锁定正文文件。

**重要**：本 Skill 不包含优化的具体逻辑（内容重写、图表修正等），这些智能工作由 **optimizer-agent 子智能体** 完成。本 Skill 仅提供文件操作、问题分组、状态管理、二次验证调度和用户交互能力。

**职责边界**：
- SKILL.md 指导主控 Agent：如何读取审查报告、如何分组问题、如何调度 optimizer-agent、如何执行二次验证、如何与用户交互
- optimizer-agent.md 指导 subagent：如何读取问题、如何修改正文、如何修正图表、如何保证格式规范
- optimization_rules.md：定义优化规则和标准，供 optimizer-agent 参考

**两阶段流程**：
- **阶段 7A（自动优化）**：读取阶段六审查报告 → 按节点分组 → 调度 optimizer-agent 优化 → 二次验证 → 生成 optimization_report.md
- **阶段 7B（人工审查 + 优化循环）**：提交用户审查 → 收集反馈 → 优化调整 → 二次验证 → 重新提交（最多 3 次循环）→ 锁定文件

## 前置条件

- 项目状态为「内容审查完成」
- review_file/optimization_suggestions.md 已生成（阶段六产出）
- review_file/ai_review_*.json 已生成（阶段六产出，可能为空文件或非空文件）
- proposal_file 目录下已有完整的正文 .md 文件
- outline.json 已通过结构完整性校验
- metadata.json 已包含「当前需撰写标段」「预期总字数」字段

## 工作流程

```
【阶段 7A：自动优化】
步骤1: 确定工作空间，读取 metadata.json 确认项目状态为「内容审查完成」
    ↓
步骤2: 调用 read_optimization_inputs(workspace_path) 读取审查报告和问题列表
    ↓
步骤3: 调用 group_issues_by_node(issues) 按节点分组问题（避免写冲突）
    ↓
步骤4: 主控 Agent 调度 optimizer-agent 执行优化（按批次：严重→一般→建议；同批次内不同节点可并行，最多 3 个）
    ↓
步骤5: 调用 run_revalidation(workspace_path, round=1) 执行二次验证
       （复用阶段六的 script_review + 调度 reviewer-agent 执行 AI 审查）
    ↓
步骤6: 调用 generate_optimization_report(workspace_path, round=1) 生成优化报告
    ↓
步骤7: 调用 update_metadata_status(workspace_path, "自动优化完成") 更新项目状态

【阶段 7B：人工审查 + 优化循环】
步骤8: 主控 Agent 向用户提交人工审查请求（展示 optimization_report.md）
    ↓
步骤9: 用户回复：确认通过 / 提出修改意见
    ↓
[若通过]
步骤10: 调用 lock_proposal_files(workspace_path) 锁定所有正文 .md 文件
步骤11: 调用 update_metadata_status(workspace_path, "审查优化全部完成") 更新状态
步骤12: 通知用户已锁定，准备进入阶段八

[若不通过]
步骤10': 收集用户修改意见，整理为结构化需求列表
步骤11': 调用 check_outline_structure_change(user_feedback) 检查是否涉及大纲结构变更
         [若涉及] 先调用 outline-agent 更新 outline.json、重新生成 outline.md 和目录结构
步骤12': 调用 group_user_feedback(user_feedback) 将用户反馈按节点分组
步骤13': 调度 optimizer-agent 执行第二轮优化（round=2）
步骤14': 调用 run_revalidation(workspace_path, round=2) 二次验证
步骤15': 更新 optimization_report.md（追加第二轮记录）
步骤16': 回到步骤8 重新提交用户审查（最多 3 次；超出后暂停流程，人工介入）
```

***

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录
2. 读取 `metadata.json`，确认「项目状态」为「内容审查完成」
3. 读取「当前需撰写标段」「预期总字数」字段
4. 读取 `optimization_round` 字段（如不存在，初始化为 0；每轮优化递增）

**N 的确定**：根据 metadata.json 的「当前需撰写标段」字段确定标段编号 N：
- 「标段1」或「01」 → N=1
- 「标段2」或「02」 → N=2
- 不分标段时 N=1

### 步骤2：读取优化输入

调用 `read_optimization_inputs(workspace_path)` 读取所有必要文件。

**读取文件列表**：
- `review_file/optimization_suggestions.md`（阶段六生成的优化建议报告，主输入）
- `review_file/ai_review_content.json`（AI 审查结果：内容完整性）
- `review_file/ai_review_scoring.json`（AI 审查结果：评分点响应）
- `review_file/ai_review_language.json`（AI 审查结果：技术与语言规范）
- `proposal_file/outline.json`（大纲结构，用于定位节点）
- `proposal_file/*.md`（所有正文文件，用于优化参考）
- `proposal_file/summary_report.md`（阶段五撰写报告，了解撰写时已知问题）
- `extraction_file/packages_file/package_N/07_Evaluation_Criteria.md`（评审标准，优化参考）
- `extraction_file/packages_file/package_N/09_Technical_Requirements.md`（技术要求，优化参考）
- `metadata.json`（项目元数据）

**返回值处理**：
- `success=true`：继续步骤3
- `success=false`：向用户报告 `missing_files`，提示补充后重新执行本步骤

**关键规则**：此步骤仅做文件存在性校验和内容读取，不做智能分析（智能分析由 optimizer-agent 独立完成）。本函数同时会复用阶段六的 `collect_review_results` 收集审查问题列表，供步骤3分组使用。

### 步骤3：按节点分组问题

调用 `group_issues_by_node(issues)` 将所有审查问题按 `node_id` 分组。

**分组目的**：避免多个 optimizer-agent 同时修改同一节点导致写冲突。

**分组结果**：每个节点对应一个优化任务，包含该节点的所有问题（含严重/一般/建议）。

**批次划分**：
- 第一批 `batch_1_serious`：含严重问题的节点（优先级最高）
- 第二批 `batch_2_general`：仅含一般问题的节点
- 第三批 `batch_3_suggestion`：仅含建议性问题的节点

**去重处理**：同一节点中相同问题（来自脚本审查和 AI 审查的重复发现）合并为一个。

**无问题处理**：如果 `issues` 为空（阶段六审查无问题），直接跳到步骤7（生成空报告并提交用户审查）。

### 步骤4：调度 optimizer-agent 执行优化

**调度策略**：

| 策略项 | 说明 |
|--------|------|
| 并行度控制 | 最多同时启动 **3 个** optimizer-agent，避免资源过度消耗 |
| 任务分组 | 按 node_id 分组：同节点所有问题合并为一个任务（避免写冲突） |
| 批次顺序 | 严重问题节点 → 一般问题节点 → 建议性问题节点（按优先级） |
| 同批次并行 | 同批次内不同节点可并行执行（受 3 个并发上限约束） |
| 重试机制 | 失败节点最多重试 **2 次**（OPTIMIZER_MAX_RETRY=2），仍失败则标记并继续其他节点 |
| 异常处理 | 单个节点优化失败不影响其他节点，失败节点记录到 metadata.json |
| 上下文限制 | 每个 optimizer-agent 仅处理一个节点的所有问题，避免上下文过大 |

**调用机制**：主控 Agent 通过 TraeCode 内置的 agent 调用机制（Task 工具，subagent_type 选择对应类型），使用任务描述向 optimizer-agent 传递参数。

**传递参数**：
- workspace_path（工作空间路径，绝对路径）
- node_id、node_title、content_plan、word_count、charts（节点信息）
- issues（该节点所有问题列表，含 level/description/dimension/suggestion）
- round（优化轮次：1=第一轮自动优化，2/3=用户反馈优化）
- user_feedback（仅 round > 1 时提供，可选）

**任务描述模板**：

```
请执行内容优化任务。
- 工作空间路径：<绝对路径>
- 节点 ID：<node_id>
- 节点标题：<node_title>
- 内容计划：<content_plan>
- 计划字数：<word_count>
- 图表定义：<charts>
- 优化轮次：<round>
- 用户反馈：<user_feedback（如有）>
- 该节点的问题列表：<issues JSON>

请阅读 .trae/agents/optimizer-agent.md 了解你的职责和工作流程，然后：
1. 读取当前正文文件和审查素材
2. 遵循 .trae/rules/optimization_rules.md 中的优化规则
3. 按问题严重程度分级处理（严重→重写；一般→补充；建议→微调）
4. 遵循 .trae/rules/writing_rules.md 和 .trae/rules/anti_ai_writing_rules.md
5. 将优化结果覆盖写入原 .md 文件
```

**optimizer-agent 独立工作**：收到任务后，optimizer-agent 自行使用 Read 工具读取素材和当前正文、执行优化、使用 Write 工具覆盖写入 .md 文件。

**主控 Agent 监控**：主控 Agent 监控任务执行状态，处理异常情况，记录完成节点。每个节点完成后调用 `update_metadata_status` 或在 metadata.json 的 `optimization_completed_nodes` 中追加节点 ID。

### 步骤5：执行二次验证

调用 `run_revalidation(workspace_path, round=1)` 执行二次验证。

**复用阶段六能力**：
- **脚本审查**：调用 `review_optimization/SKILL.py` 的 `script_review` 函数（直接导入）
- **AI 审查**：调度 reviewer-agent 执行 3 维度 AI 审查（content_completeness、scoring_response、technical_language），最多并行 3 个

**验证结果判定**：
- 所有严重问题已修复：验证通过，可提交用户审查
- 仍存在严重问题：自动追加一轮优化（仅针对未修复的严重问题），再次验证
- 仍存在一般/建议性问题：记录到报告，不影响提交用户审查

**追加优化上限**：自动追加最多 1 次，仍无法修复则标记为"需人工处理"。

**AI 审查调度**：本函数返回 `ai_tasks`（需执行的 AI 审查任务列表），主控 Agent 据此调度 reviewer-agent。reviewer-agent 完成后，主控 Agent 再次调用本函数收集结果（或调用阶段六的 `collect_review_results`）。

### 步骤6：生成优化报告

调用 `generate_optimization_report(workspace_path, round=1)` 生成 `optimization_report.md`。

**报告内容**：
- 优化完成时间
- 优化概览（总问题数、已修复数、未修复数、新增问题数）
- 优化执行记录（按节点列表，含修改前后对比摘要）
- 二次验证结果（3 维度脚本审查 + 3 维度 AI 审查）
- 优化前后对比（字数变化、问题数变化）
- 未修复问题清单（需用户关注）

**报告格式**：Markdown，写入 `review_file/optimization_report.md`（追加模式，每轮优化追加一个章节）。

### 步骤7：更新项目状态

调用 `update_metadata_status(workspace_path, "自动优化完成")` 更新项目状态。
同时更新 `optimization_round` 字段为 1，`optimization_status` 为 `auto_completed`。

### 步骤8：提交用户人工审查

主控 Agent 通过 AskUserQuestion 向用户提交人工审查请求。

**提交内容**：
- optimization_report.md 路径
- 优化概览摘要（总问题数、已修复数、未修复数）
- 未修复问题清单（如有）
- 询问用户：是否通过人工审查 / 提出修改意见

**不通过时**：用户需提供具体的修改意见（可针对整体或具体章节）。

### 步骤9：处理用户反馈

- 用户确认通过 → 跳转步骤10
- 用户提出修改意见 → 跳转步骤10'

### 步骤10-12：用户通过后的处理

- 调用 `lock_proposal_files(workspace_path)` 锁定所有正文 .md 文件
  - **锁定机制**：在 metadata.json 中添加 `proposal_files_locked: true` 字段
  - **锁定效果**：后续阶段（阶段八）和 optimizer-agent 在文件锁定后拒绝修改
- 调用 `update_metadata_status(workspace_path, "审查优化全部完成")` 更新状态
- 通知用户：所有正文已锁定，可进入阶段八（合并导出）

### 步骤10'-16'：用户不通过的处理（优化循环）

- **步骤10'**：收集用户修改意见，整理为结构化需求列表
  - 用户意见格式：自然语言描述（针对整体或具体章节）
  - 主控 Agent 解析为结构化列表：`{node_id, feedback_content, expected_change}`
- **步骤11'**：调用 `check_outline_structure_change(user_feedback)` 检查是否涉及大纲结构变更
  - 涉及变更的判断依据：用户要求新增/删除/移动章节、修改章节标题、调整章节层级
  - [若涉及] 先调用 outline-agent 更新 outline.json，重新生成 outline.md 和目录结构
  - outline-agent 更新后，主控 Agent 需同步处理：新增节点的正文需新撰写（调用 writer-agent）、删除节点的正文需删除
- **步骤12'**：调用 `group_user_feedback(user_feedback)` 将用户反馈按节点分组
- **步骤13'**：调度 optimizer-agent 执行第二轮优化（round=2）
  - 仅处理用户反馈涉及的问题（无需重新优化所有节点）
  - 优化范围：用户指出的具体节点
- **步骤14'**：调用 `run_revalidation(workspace_path, round=2)` 二次验证
  - 仅验证被修改的节点（减少验证开销）
- **步骤15'**：更新 `optimization_report.md`，追加第二轮优化记录
- **步骤16'**：回到步骤8 重新提交用户审查
  - **循环上限**：最多 3 次（含首轮自动优化共 3 轮）
  - **超出上限**：暂停流程，向用户说明情况，请求人工介入协调

***

## API Reference

### read_optimization_inputs

**功能**：读取优化输入（审查报告、AI 审查结果、正文、大纲等），并收集审查问题列表

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'result': {
        'files': list,              # 已存在的文件相对路径列表
        'missing_files': list,      # 缺失文件相对路径列表
        'metadata': dict,           # metadata.json 关键字段
        'outline_path': str,        # outline.json 路径
        'package_n': str,           # 标段编号
        'md_files': list,           # 正文 .md 文件列表
        'issues': list,             # 收集到的审查问题列表（复用阶段六 collect_review_results）
        'issues_count': int         # 审查问题总数
    }
}
```

### group_issues_by_node

**功能**：按节点分组问题（避免写冲突），并按批次划分

**参数**：
- `issues`: list - 审查问题列表（来自 read_optimization_inputs 或 collect_review_results）

**返回**：
```python
{
    'success': bool,
    'grouped': {
        'batch_1_serious': list,    # 含严重问题的节点列表
        'batch_2_general': list,    # 仅含一般问题的节点列表
        'batch_3_suggestion': list  # 仅含建议性问题的节点列表
    },
    'summary': {
        'total_nodes': int,         # 需优化的节点总数
        'serious_nodes': int,       # 含严重问题的节点数
        'general_nodes': int,       # 仅含一般问题的节点数
        'suggestion_nodes': int,    # 仅含建议性问题的节点数
        'total_issues': int         # 问题总数（去重后）
    }
}
```

### run_revalidation

**功能**：执行二次验证（复用阶段六脚本+AI 审查能力）

**参数**：
- `workspace_path`: str - 工作空间路径
- `round`: int - 优化轮次（1、2、3），用于在报告中标示
- `target_node_ids`: list - 可选，仅验证指定节点（用户反馈循环时使用，减少开销）

**返回**：
```python
{
    'success': bool,
    'round': int,
    'script_results': dict,      # 脚本审查结果（复用阶段六 script_review）
    'ai_tasks': list,            # 需主控 Agent 调度 reviewer-agent 的 AI 审查任务列表
    'revalidation_time': str     # 验证时间
}
```

**注意**：本函数仅负责调度和收集脚本审查结果，AI 审查的具体执行由 reviewer-agent 完成（主控 Agent 调度）。主控 Agent 调度 reviewer-agent 完成后，可再次调用本函数或 `collect_review_results` 收集 AI 审查结果。

### generate_optimization_report

**功能**：生成优化完成报告（追加模式）

**参数**：
- `workspace_path`: str - 工作空间路径
- `round`: int - 优化轮次

**返回**：
```python
{
    'success': bool,
    'report_path': str,      # 报告文件路径
    'round': int,            # 优化轮次
    'stats': dict            # 报告统计信息
}
```

### lock_proposal_files

**功能**：锁定所有正文 .md 文件

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'result': {
        'locked_files': list,    # 已锁定的文件列表
        'lock_time': str,        # 锁定时间
        'locked': bool           # 是否已锁定
    }
}
```

### check_outline_structure_change

**功能**：检查用户反馈是否涉及大纲结构变更

**参数**：
- `user_feedback`: str - 用户反馈内容（自然语言）

**返回**：
```python
{
    'success': bool,
    'involves_change': bool,     # 是否涉及大纲结构变更
    'change_details': list,      # 变更详情 [{type, node_id, description}]
    'keywords_matched': list     # 匹配到的关键词
}
```

**注意**：本函数仅做关键词识别（如"新增"、"删除"、"调整结构"等），复杂判断由主控 Agent 通过语义理解完成。

### group_user_feedback

**功能**：将用户反馈按节点分组

**参数**：
- `user_feedback`: str - 用户反馈内容（自然语言）

**返回**：
```python
{
    'success': bool,
    'grouped_feedback': dict,    # 按 node_id 分组的反馈 {node_id: [feedback_items]}
    'overall_feedback': list,    # 未明确指向节点的整体反馈
    'total_feedback_items': int  # 反馈项总数
}
```

### update_metadata_status

**功能**：更新 metadata.json 的「项目状态」字段，并更新「状态更新时间」

**参数**：
- `workspace_path`: str - 工作空间路径
- `status`: str - 项目状态值（自动优化完成 / 审查优化全部完成）

**返回**：
```python
{
    'success': bool,
    'status': str,
    'updated_fields': list
}
```

**状态值**：
- `内容审查完成`（阶段六结束）
- `自动优化完成`（阶段 7A 结束）
- `审查优化全部完成`（阶段 7B 结束，文件已锁定）

### get_optimization_status

**功能**：获取优化状态，支持中断恢复

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'optimization_status': str,           # pending/in_progress/auto_completed/user_reviewing/completed
    'optimization_round': int,            # 当前优化轮次
    'optimization_start_time': str,
    'optimization_completed_nodes': list, # 已优化的节点
    'optimization_failed_nodes': list,    # 优化失败的节点
    'optimization_retry_counts': dict,    # 重试计数
    'proposal_files_locked': bool,        # 正文文件是否锁定
    'lock_time': str,                     # 锁定时间
    'user_feedback_history': list,        # 用户反馈历史
    'project_status': str                 # 项目状态
}
```

### update_optimization_round

**功能**：更新优化轮次

**参数**：
- `workspace_path`: str - 工作空间路径
- `round`: int - 优化轮次（1、2、3）

**返回**：
```python
{
    'success': bool,
    'round': int,
    'optimization_status': str
}
```

### check_failed_optimizations

**功能**：识别失败的优化任务

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'failed_nodes': list,         # 失败节点列表 [{node_id, retry_count, can_retry}]
    'retryable_nodes': list,      # 可重试节点列表
    'exhausted_nodes': list       # 重试耗尽节点列表（需人工介入）
}
```

### update_optimization_retry_count

**功能**：管理优化重试计数

**参数**：
- `workspace_path`: str - 工作空间路径
- `node_id`: str - 节点 ID
- `increment`: int - 增量（默认 1）

**返回**：
```python
{
    'success': bool,
    'node_id': str,
    'retry_count': int,
    'status': str,            # retry / exhausted
    'max_retry': int
}
```

***

## run_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 读取优化输入
python .trae/scripts/run_skill.py content_optimization read_optimization_inputs --workspace_path "bid_project/test"

# 按节点分组问题（需通过 issues_file 传递 JSON）
python .trae/scripts/run_skill.py content_optimization group_issues_by_node --issues_file issues.json

# 执行二次验证
python .trae/scripts/run_skill.py content_optimization run_revalidation --workspace_path "bid_project/test" --round 1

# 生成优化报告
python .trae/scripts/run_skill.py content_optimization generate_optimization_report --workspace_path "bid_project/test" --round 1

# 锁定正文文件
python .trae/scripts/run_skill.py content_optimization lock_proposal_files --workspace_path "bid_project/test"

# 检查大纲结构变更
python .trae/scripts/run_skill.py content_optimization check_outline_structure_change --user_feedback "用户反馈内容"

# 按节点分组用户反馈
python .trae/scripts/run_skill.py content_optimization group_user_feedback --user_feedback "用户反馈内容"

# 更新项目状态
python .trae/scripts/run_skill.py content_optimization update_metadata_status --workspace_path "bid_project/test" --status "自动优化完成"

# 获取优化状态
python .trae/scripts/run_skill.py content_optimization get_optimization_status --workspace_path "bid_project/test"

# 更新优化轮次
python .trae/scripts/run_skill.py content_optimization update_optimization_round --workspace_path "bid_project/test" --round 1

# 识别失败优化任务
python .trae/scripts/run_skill.py content_optimization check_failed_optimizations --workspace_path "bid_project/test"

# 更新优化重试计数
python .trae/scripts/run_skill.py content_optimization update_optimization_retry_count --workspace_path "bid_project/test" --node_id "1_1_1" --increment 1
```

**返回格式**：JSON 格式

```json
{"success": true, "result": {...}}
```

***

## Error Handling

| 错误类型 | 处理方式 |
|----------|----------|
| metadata.json 不存在 | 提示用户先执行阶段一至六 |
| 项目状态非「内容审查完成」 | 提示当前状态，引导用户从正确阶段继续 |
| optimization_suggestions.md 不存在 | 提示主控 Agent 先完成阶段六内容审查 |
| 正文 .md 文件缺失 | 报告缺失文件列表，提示用户补充 |
| optimizer-agent 调用失败 | 记录失败节点，继续其他节点，失败节点记录到 metadata.json |
| 二次验证失败 | 记录异常，继续生成报告，标记需人工处理 |
| 审查报告写入失败 | 检查目录权限，尝试重试 |
| 文件锁定失败 | 检查 metadata.json 权限，尝试重试 |
| 检查点恢复失败 | 提示用户检查 metadata.json 完整性 |
| 优化循环超过 3 次 | 暂停流程，向用户说明情况，请求人工介入协调 |
| 阶段六 SKILL.py 导入失败 | 回退为仅执行脚本审查，跳过 AI 审查复用 |

## Limitations

- optimizer-agent 调用依赖 TraeCode 的 Subagent 调度机制
- 优化执行（内容重写、图表修正等）由 optimizer-agent 完成
- SKILL.py 仅负责文件操作、问题分组、状态管理和二次验证调度，无智能逻辑
- 二次验证复用阶段六的 `script_review` 和 `reviewer-agent`，不重新实现审查逻辑
- 最多同时启动 3 个 optimizer-agent，避免资源过度消耗
- 用户审查循环最多 3 次（含首轮自动优化），超出后暂停流程
- 用户通过人工审查后必须锁定正文文件，通过 metadata.json 的 `proposal_files_locked` 字段标记
- 字数控制策略与阶段五、六一致：只下限不限上限
- 如用户反馈涉及大纲结构变更，必须先通过 outline-agent 更新 outline.json，再执行优化
- 中断恢复机制通过 metadata.json 的 `optimization_status` 字段支持
