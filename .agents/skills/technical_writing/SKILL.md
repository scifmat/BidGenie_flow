---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Technical Writing Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: technical_writing
description: 主控Agent调用，用于阶段五正文撰写——读取大纲和素材，构建任务队列，调度writer-agent撰写正文，统计字数，执行质量自查，生成summary_report.md，更新项目状态
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - technical_writing
  - writer_agent
  - phase5
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
  - task_queue_management
  - word_count_statistics
  - quality_inspection
  - metadata_update
  - checkpoint_management

# Language Support
languages:
  - zh
---

# 正文撰写 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段五（正文撰写）的完整流程。主控 Agent 通过本 Skill 协调 writer-agent 子智能体完成技术方案正文的撰写，管理任务依赖和执行顺序，执行字数统计和质量自查，并生成撰写完成报告。

**重要**：本 Skill 不包含正文撰写的具体逻辑（内容创作、图表生成等），这些智能工作由 **writer-agent 子智能体** 完成。本 Skill 仅提供文件操作、任务队列管理和质量检查能力。

**职责边界**：

- SKILL.md 指导主控 Agent：如何调用工具、如何调度 writer-agent、如何管理任务队列、如何执行质量检查
- writer-agent.md 指导 subagent：如何读取素材、如何撰写正文、如何生成 Mermaid 图表、如何遵循撰写规范
- writing\_rules.md：定义撰写规范和规则，供 writer-agent 参考

## 前置条件

- 项目状态为「大纲确认完成」
- proposal\_file 目录下已有完整的目录结构和 .md 骨架文件
- outline.json 已通过结构完整性校验
- metadata.json 已包含「当前需撰写标段」「预期总字数」「采购方式」字段
- Supplementary\_info.md 已生成且校验通过

## 工作流程

```
步骤1: 确定工作空间，读取 metadata.json 确认项目状态为「大纲确认完成」
    ↓
步骤2: 调用 read_outline_and_materials(workspace_path) 读取大纲和所有撰写素材
    ↓
步骤3: 调用 build_task_queue(workspace_path) 构建撰写任务队列（含依赖处理）
    ↓
步骤4: 主控 Agent 按队列顺序调度 writer-agent 执行撰写任务（串/并行混合）
    ↓
步骤5: 每个 writer-agent 完成后，主控 Agent 调用 word_count_statistics(workspace_path) 更新字数统计
    ↓
步骤6: 所有任务完成后，调用 quality_self_check(workspace_path) 执行质量自查
    ↓
步骤7: 调用 generate_summary_report(workspace_path) 生成撰写完成报告
    ↓
步骤8: 调用 update_metadata_status(workspace_path, "正文撰写完成") 更新项目状态
```

***

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录
2. 读取 `metadata.json`，确认「项目状态」为「大纲确认完成」
3. 读取「当前需撰写标段」「预期总字数」「采购方式」字段，供后续步骤使用

**N 的确定**：根据 metadata.json 的「当前需撰写标段」字段确定标段编号 N：

- 「标段1」或「01」 → N=1
- 「标段2」或「02」 → N=2
- 不分标段时 N=1

### 步骤2：读取大纲和素材

调用 `read_outline_and_materials(workspace_path)` 读取所有必要文件。

**仅读取对技术方案撰写有用的文件**（避免资质商务内容导致上下文爆炸）：

- proposal\_file/outline.json（大纲结构和节点信息）
- extraction\_file/common\_file/01\_Basic\_Information.md（基础信息，用于了解项目背景）
- extraction\_file/packages\_file/package\_N/06\_Procurement\_Content.md（采购内容）
- extraction\_file/packages\_file/package\_N/07\_Evaluation\_Criteria.md（评审标准，核心撰写依据）
- extraction\_file/packages\_file/package\_N/08\_Business\_Requirements.md（商务要求，部分内容可能需要响应）
- extraction\_file/packages\_file/package\_N/09\_Technical\_Requirements.md（技术要求，核心撰写依据）
- Supplementary\_info.md（投标人补充信息，资质/人员/设备等）
- metadata.json（项目元数据）

<br />

**返回值处理**：

- `success=true`：继续步骤3
- `success=false`：向用户报告 `missing_files`，提示补充后重新执行本步骤

**关键规则**：此步骤仅做文件存在性校验和内容读取，不做智能分析（智能分析由 writer-agent 独立完成）。

### 步骤3：构建撰写任务队列

调用 `build_task_queue(workspace_path)` 根据 outline.json 构建任务队列。

**任务队列结构**：

```python
{
    'node_id': '1_1_1',
    'title': '需求分析',
    'level': 3,
    'word_count': 2000,
    'content_plan': '1. xxx；2. xxx；3. xxx',
    'generate_chart': True,
    'charts': [...],
    'depends_on': ['1_1'],  # 依赖的其他节点 ID 数组（可选，可能不存在）
    'file_path': 'proposal_file/1_1_整体项目理解/1_1_1_需求分析.md',
    'status': 'pending'  # pending/processing/completed/failed
}
```

**依赖处理**：

- **检查节点是否存在** **`depends_on`** **字段**：
  - 存在 `depends_on`：使用该字段构建节点依赖图，使用拓扑排序算法生成执行顺序
  - 不存在 `depends_on`：默认按大纲深度优先遍历顺序执行（同级节点可并行）
- 使用拓扑排序算法，确保依赖节点先于被依赖节点执行

**任务优先级**：

- 无依赖的节点优先级最高
- 有依赖的节点需等待所有依赖完成后才能执行
- 同级节点可并行执行（受资源限制）

**检查点恢复**：

- 调用 `get_completed_nodes(workspace_path)` 获取已完成的节点列表
- 任务队列构建时，跳过已完成的节点
- 失败的节点记录到 metadata.json 的 `failed_nodes` 字段

### 步骤4：调度 writer-agent 执行撰写

**调度策略**：串/并行混合执行

- 同一级别的独立节点（无相互依赖）可并行执行
- 有依赖关系的节点按依赖顺序串行执行
- 最多同时启动 **3 个** writer-agent（资源限制）

**调用机制**：主控 Agent 通过 TraeCode 内置的 agent 调用机制（Task 工具，subagent\_type 选择对应类型），使用任务描述向 writer-agent 传递参数。

**传递参数**：

- 工作空间路径（绝对路径）
- 节点信息（node\_id、title、level、content\_plan、word\_count、generate\_chart、charts、depends\_on）
- 输出文件路径（file\_path）
- 标段编号 N

**任务描述模板**：

```
请执行正文撰写任务。
- 工作空间路径：<绝对路径>
- 标段编号：<N>
- 节点信息：
  - node_id: <节点ID>
  - title: <节点标题>
  - level: <节点层级>
  - content_plan: <细纲要点>
  - word_count: <建议正文字数>
  - generate_chart: <是否生成图表>
  - charts: <图表定义数组>
  - file_path: <输出文件相对路径>
请阅读 .trae/agents/writer-agent.md 了解你的职责和工作流程，然后：
1. 读取相关素材文件（01_Basic_Information.md、06_Procurement_Content.md、07_Evaluation_Criteria.md、08_Business_Requirements.md、09_Technical_Requirements.md、Supplementary_info.md、metadata.json）
2. 根据 content_plan 撰写正文，覆盖所有要点
3. 根据 charts 数组生成 Mermaid 图表代码块
4. 遵循 writing_rules.md 中的撰写规则
5. 使用 Write 工具将撰写结果写入指定的 file_path
```

**writer-agent 独立工作**：收到任务后，writer-agent 自行使用 Read 工具读取素材、撰写正文、生成 Mermaid 图表、写入 .md 文件。

**主控 Agent 监控**：主控 Agent 监控任务执行状态，处理异常情况，记录完成节点到 metadata.json（检查点机制）。

#### 步骤4.1：子智能体调度详细策略

| 策略项   | 说明                                                                                                        |
| ----- | --------------------------------------------------------------------------------------------------------- |
| 并行度控制 | 最多同时启动 **3 个** writer-agent，避免资源过度消耗                                                                      |
| 依赖处理  | 使用拓扑排序，确保依赖节点先执行                                                                                          |
| 执行顺序  | 按大纲深度优先遍历顺序，同级节点可并行                                                                                       |
| 检查点机制 | 每个节点完成后调用 `update_completed_nodes(workspace_path, node_id)` 更新 metadata.json 的 completed\_nodes 字段，支持中断恢复 |
| 异常处理  | 单个节点撰写失败不影响其他节点，失败节点记录到 metadata.json 的 failed\_nodes 字段                                                  |
| 重试机制  | 失败节点最多重试 **2 次**，仍失败则标记并继续其他节点                                                                            |

### 步骤5：字数统计

每个 writer-agent 完成后，主控 Agent 调用 `word_count_statistics(workspace_path)` 更新字数统计。

**统计口径**（参考附件3）：

| 统计项    | 是否计入字数 |
| ------ | ------ |
| 正文段落文字 | 是      |
| 标题文字   | 否      |
| 图表代码块  | 否      |
| 图题文字   | 否      |
| 表格内容   | 是      |
| 列表内容   | 是      |
| 引用内容   | 是      |

**偏差校验规则**：

- 实际字数与 word\_count 偏差 ≤ ±15%：合格
- 偏差 > ±15%：标记为警告

### 步骤6：质量自查

所有任务完成后，调用 `quality_self_check(workspace_path)` 执行质量自查。

**自查内容**：

1. **标题层级检查**：
   - 标题层级连续，不跳级
   - 标题层级不超过大纲节点层级一级
   - 标题不添加数字编号
2. **格式规范检查**：
   - 段落格式（空行分隔）
   - 图表代码块格式（\`\`\`mermaid 标记）
   - 图题引用标记（`*图 X-Y-Z-N 图题名称*`）
   - 表格标题格式（`**表 X-Y-Z-N 表格名称**`）
3. **内容完整性检查**：
   - 正文是否覆盖 content\_plan 中的所有要点
   - 要点覆盖率 ≥ 80% 为合格
4. **图表规范检查**：
   - Mermaid 代码块语法正确性
   - 图表数量与 charts 数组长度一致

### 步骤7：生成撰写完成报告

调用 `generate_summary_report(workspace_path)` 生成 `summary_report.md`。

**报告内容包括**：

- 完成时间
- 章节统计（总节点数、已完成数、失败数、跳过数）
- 字数统计（各章节实际字数、与计划偏差、合格状态）
- 图表生成统计（总图表数、生成成功数、失败数）
- 自查结果汇总（格式问题数、内容问题数、图表问题数）
- 问题详情列表

**报告位置**：`bid_project/<工作空间>/proposal_file/summary_report.md`

### 步骤8：更新项目状态

调用 `update_metadata_status(workspace_path, "正文撰写完成")` 更新项目状态。

***

## API Reference

### read\_outline\_and\_materials

**功能**：读取大纲和所有撰写素材

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
        'outline_path': str      # outline.json 路径
    }
}
```

### build\_task\_queue

**功能**：根据 outline.json 构建撰写任务队列，处理依赖关系

**参数**：

- `workspace_path`: str - 工作空间路径

**返回**：

```python
{
    'success': bool,
    'task_queue': list,         # 任务队列列表（按执行顺序）
    'parallel_groups': list,    # 可并行执行的节点分组
    'total_tasks': int,         # 总任务数
    'skipped_tasks': list       # 跳过的已完成任务（检查点恢复）
}
```

### word\_count\_statistics

**功能**：统计各章节字数，校验偏差

**参数**：

- `workspace_path`: str - 工作空间路径

**返回**：

```python
{
    'success': bool,
    'statistics': list,         # 各章节字数统计
    'summary': {                # 汇总信息
        'total_actual': int,    # 实际总字数
        'total_planned': int,   # 计划总字数
        'qualified_count': int, # 合格章节数
        'warning_count': int    # 警告章节数
    }
}
```

### quality\_self\_check

**功能**：执行质量自查（标题层级、格式、内容完整性、图表规范）

**参数**：

- `workspace_path`: str - 工作空间路径

**返回**：

```python
{
    'success': bool,
    'passed': bool,             # 整体是否通过
    'checks': {                 # 各项检查结果
        'heading_level': dict,
        'format': dict,
        'content_completeness': dict,
        'chart': dict
    },
    'issues': list              # 问题详情列表
}
```

### generate\_summary\_report

**功能**：生成撰写完成报告

**参数**：

- `workspace_path`: str - 工作空间路径

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
- `status`: str - 项目状态值（默认：正文撰写完成）

**返回**：

```python
{
    'success': bool,
    'status': str,
    'updated_fields': list
}
```

### get\_completed\_nodes

**功能**：获取已完成节点列表（检查点恢复）

**参数**：

- `workspace_path`: str - 工作空间路径

**返回**：

```python
{
    'success': bool,
    'completed_nodes': list,    # 已完成节点 ID 列表
    'failed_nodes': list        # 失败节点 ID 列表
}
```

### update\_completed\_nodes

**功能**：更新已完成节点列表（检查点机制）

**参数**：

- `workspace_path`: str - 工作空间路径
- `node_id`: str - 节点 ID
- `status`: str - 节点状态（completed/failed，默认 completed）

**返回**：

```python
{
    'success': bool,
    'node_id': str,
    'status': str,
    'completed_nodes': list,
    'failed_nodes': list,
    'writing_progress': int     # 撰写进度百分比
}
```

***

## run\_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 读取大纲和素材
python .trae/scripts/run_skill.py technical_writing read_outline_and_materials --workspace_path "bid_project/test"

# 构建撰写任务队列
python .trae/scripts/run_skill.py technical_writing build_task_queue --workspace_path "bid_project/test"

# 字数统计
python .trae/scripts/run_skill.py technical_writing word_count_statistics --workspace_path "bid_project/test"

# 质量自查
python .trae/scripts/run_skill.py technical_writing quality_self_check --workspace_path "bid_project/test"

# 生成撰写完成报告
python .trae/scripts/run_skill.py technical_writing generate_summary_report --workspace_path "bid_project/test"

# 更新项目状态
python .trae/scripts/run_skill.py technical_writing update_metadata_status --workspace_path "bid_project/test" --status "正文撰写完成"

# 获取已完成节点
python .trae/scripts/run_skill.py technical_writing get_completed_nodes --workspace_path "bid_project/test"

# 更新已完成节点
python .trae/scripts/run_skill.py technical_writing update_completed_nodes --workspace_path "bid_project/test" --node_id "1_1_1" --status "completed"
```

**注意**：正文 .md 文件由 writer-agent 使用 Write 工具直接创建（非脚本生成）。summary\_report.md 由 SKILL.py 生成。

**返回格式**：JSON 格式

```json
{"success": true, "result": {...}}
```

***

## Error Handling

| 错误类型              | 处理方式                              |
| ----------------- | --------------------------------- |
| metadata.json 不存在 | 提示用户先执行阶段一、二、三、四                  |
| 项目状态非「大纲确认完成」     | 提示当前状态，引导用户从正确阶段继续                |
| outline.json 不存在  | 提示主控 Agent 先完成阶段四大纲编写             |
| 输入文件缺失            | 报告缺失文件列表，提示用户补充                   |
| writer-agent 调用失败 | 重试或标记为失败节点，继续其他节点                 |
| 正文文件写入失败          | 检查目录权限，尝试重试                       |
| 字数偏差超限            | 记录到 summary\_report.md，进入内容审查阶段处理 |
| 图表渲染失败            | 保留代码块并记录异常，内容审查阶段处理               |
| 检查点恢复失败           | 提示用户检查 metadata.json 完整性          |

## Limitations

- writer-agent 调用依赖 TraeCode 的 Subagent 调度机制
- 正文撰写、图表生成等智能工作由 writer-agent 完成
- 正文 .md 文件由 writer-agent 使用 Write 工具直接创建（非脚本生成）
- SKILL.py 仅负责文件操作、任务队列管理和质量检查，无智能逻辑
- 最多同时启动 3 个 writer-agent，避免资源过度消耗
- depends\_on 字段可能不存在（阶段四 outline-agent 可能遗漏），此时默认按大纲深度优先顺序执行
- 正文撰写阶段仅读取对技术方案有用的文件（01、06、07、08、09），避免资质商务内容导致上下文爆炸
- 用户交互依赖 TraeCode 内置的 AskUserQuestion 工具

