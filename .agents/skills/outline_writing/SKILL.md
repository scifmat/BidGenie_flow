---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Outline Writing Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: outline_writing
description: 主控Agent调用，用于阶段四大纲编写——读取提取文件供Agent分析，校验outline.json结构完整性，生成outline.md，生成proposal_file目录结构，更新项目状态
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - outline_writing
  - outline_agent
  - phase4
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
  - structure_validation
  - directory_generation
  - metadata_update

# Language Support
languages:
  - zh
---

# 大纲编写 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段四（大纲编写）的完整流程。主控 Agent 通过本 Skill 协调 outline-agent 子智能体完成大纲编写，与用户交互确认大纲，并完成完整性校验。

**重要**：本 Skill 不包含大纲编写的具体逻辑（解析评分标准、构建大纲结构等），这些智能工作由 **outline-agent 子智能体** 完成。本 Skill 仅提供文件操作和校验能力。

**职责边界**：
- SKILL.md 指导主控 Agent：如何调用工具、如何调度 subagent、如何与用户交互
- outline-agent.md 指导 subagent：如何解析文件、如何构建大纲、如何生成 outline.json

## 前置条件

- 项目状态为「信息补充完成」
- metadata.json 已包含「当前需撰写标段」「预期总字数」「采购方式」字段
- Supplementary_info.md 已生成且校验通过
- extraction_file 目录下有完整的提取文件

## 工作流程

```
步骤1: 确定工作空间，读取 metadata.json 确认项目状态为「信息补充完成」
    ↓
步骤2: 调用 read_input_files(workspace_path, package) 校验所有输入文件存在且完整
    ↓
步骤3: 主控 Agent 调用 outline-agent 子智能体，下发大纲编写任务
    ↓
步骤4: outline-agent 完成后，主控 Agent 调用 validate_outline_structure(workspace_path) 校验 outline.json 结构完整性
    ↓
步骤5: 调用 generate_outline_md(workspace_path) 生成 outline.md 供用户审查
    ↓
步骤6: 主控 Agent 使用 AskUserQuestion 提交大纲确认
  ├─ 用户确认：继续步骤7
  └─ 用户不确认：outline-agent 根据用户反馈修改大纲（反复，直到用户确认为止）
    ↓
步骤7: 调用 generate_directory_structure(workspace_path) 生成 proposal_file 目录结构
    ↓
步骤8: 调用 update_metadata_status(workspace_path, "大纲确认完成") 更新项目状态
```

---

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录（可根据 metadata.json 中的工作空间路径定位）
2. 读取 `metadata.json`，确认「项目状态」为「信息补充完成」
3. 读取「当前需撰写标段」「预期总字数」「采购方式」字段，供后续步骤使用

### 步骤2：前置文件校验

调用 `read_input_files(workspace_path, package)` 检查所有必要文件是否存在且完整。

**校验文件列表**：
- common_file/ 下的公共信息文件（01、02、04、05）
- packages_file/package_N/ 下的标段专属文件（06、07、08、09）
- metadata.json
- Supplementary_info.md

**关键规则**：
- 此步骤仅做文件存在性校验，**不读取文件内容**（文件内容由 outline-agent 独立读取分析）
- 如果文件缺失或不完整，提示用户补充后重新校验
- `package` 参数从 metadata.json 的「当前需撰写标段」字段获取（如「标段2」对应 N=2，不分标段时 N=1）

**返回值处理**：
- `success=true`：继续步骤3
- `success=false`：向用户报告 `missing_files`，提示补充后重新执行本步骤

### 步骤3：调用 outline-agent 子智能体

**调用机制**：主控 Agent 通过 TraeCode 内置的 agent 调用机制（Task 工具，subagent_type 选择对应类型），使用任务描述向 outline-agent 传递参数。

**传递参数**：
- 工作空间路径（绝对路径）
- 标段编号（从 metadata.json 的「当前需撰写标段」获取，并转换为数字 N：如「标段2」→ 2，「01」→ 1）

**任务描述模板**：

```
请执行大纲编写任务。
- 工作空间路径：<绝对路径>
- 标段编号：<N>
请阅读 .trae/agents/outline-agent.md 了解你的职责和工作流程，然后：
1. 读取 metadata.json 确认「当前需撰写标段」「预期总字数」「采购方式」
2. 读取 extraction_file 下对应标段的提取文件（重点 07_Evaluation_Criteria.md）
3. 执行技术评分标准内容缺失检测（步骤0），如检测到异常立即提交异常报告
4. 解析评审标准，构建树形大纲结构
5. 规划细纲和字数分配，判断图表生成需求
6. 使用 Write 工具将 outline.json 写入 bid_project/<工作空间>/proposal_file/outline.json
```

**outline-agent 独立工作**：收到任务后，outline-agent 自行使用 Read 工具读取文件、解析评审标准、构建大纲、生成 outline.json。

**主控 Agent 无需干预**：主控 Agent 将任务下发后，等待 outline-agent 完成即可，不干预具体工作过程。

**异常报告处理**：

当 outline-agent 返回异常报告时（`status: "abnormal"`，`abnormal_type: "evaluation_criteria_missing"`），主控 Agent 需执行以下处理流程：

#### 3.1 情况验证

主控 Agent 读取 `07_Evaluation_Criteria.md` 文件，核实技术评分标准内容缺失情况是否属实。

**验证内容**：
- 文件是否存在
- 文件内容是否完整
- 是否包含足够的评审因素和评分要点

#### 3.2 分类处理

**情况一：误判（情况不属实）**

主控 Agent 向 outline-agent 发送具体指正信息，明确指出误判原因，并指令其继续执行原定大纲编写流程。

**情况二：属实（内容确实缺失或不完整）**

主控 Agent 立即调用 `AskUserQuestion` 工具向用户确认是否存在文件漏传情况：

```json
{
  "questions": [
    {
      "question": "检测到技术评分标准内容缺失或不完整，可能影响大纲编写质量。\n\n【检测详情】\n- 文件位置：extraction_file/packages_file/package_N/07_Evaluation_Criteria.md\n- 问题描述：<outline-agent 报告的具体问题>\n- 识别到的评审因素：<数量> 个\n\n请确认是否存在文件漏传情况？",
      "header": "确认文件漏传",
      "multiSelect": false,
      "options": [
        {"label": "确有漏传", "description": "请上传补充文件，系统将重新执行阶段一至阶段三流程"},
        {"label": "并非漏传", "description": "招标文件确实无相关内容或内容过于简单"}
      ]
    }
  ]
}
```

**用户确认漏传**：
1. 进入文件等待状态，提示用户上传补充文件
2. 用户上传后，重新执行阶段一（文件解析）、阶段二（信息提取）、阶段三（内容分析）的完整流程
3. 完成后再继续执行阶段四（大纲编写）工作

**用户确认并非漏传**：
主控 Agent 调用 `AskUserQuestion` 工具向用户提供以下标准化可行性方案供选择：

```json
{
  "questions": [
    {
      "question": "技术评分标准内容缺失，无法自动生成完整大纲。请选择以下方案之一：",
      "header": "选择处理方案",
      "multiSelect": false,
      "options": [
        {"label": "方案1：AI补充生成", "description": "主控Agent根据已提取的相关文件内容，结合内置联网搜索工具收集补充信息，生成包含标题及范围的二级大纲，传递给outline-agent执行大纲撰写"},
        {"label": "方案2：用户提供二级大纲", "description": "由用户提供包含标题及范围的二级大纲，经主控Agent优化后传递给outline-agent执行大纲撰写"},
        {"label": "方案3：用户提供完整大纲", "description": "由用户提供完整大纲，经主控Agent优化后传递给outline-agent执行大纲撰写"},
        {"label": "方案4：其他", "description": "用户自定义解决方案，由主控Agent负责标准化处理后传递给相应subagents"}
      ]
    }
  ]
}
```

**方案执行流程**：
- **方案1（AI补充生成）**：主控 Agent 使用联网搜索工具收集相关信息，生成二级大纲（包含标题和范围描述），传递给 outline-agent 执行大纲撰写
- **方案2（用户提供二级大纲）**：用户提供二级大纲后，主控 Agent 优化格式，传递给 outline-agent 执行大纲撰写
- **方案3（用户提供完整大纲）**：用户提供完整大纲（可能是文档、纯文字或其他格式）后，主控 Agent 将其转换为 .md（或文字）格式，直接传递给 outline-agent 执行大纲撰写（由 outline-agent 负责生成 outline.json）
- **方案4（其他）**：用户描述自定义方案，主控 Agent 负责标准化处理后执行

### 步骤4：校验大纲结构完整性

调用 `validate_outline_structure(workspace_path)` 检查 outline.json 的结构完整性。

**校验内容**：
- JSON 格式有效性
- 层级关系正确性（子节点层级 = 父节点层级 + 1）
- node_id 唯一性
- write_content 与 children 一致性（write_content=false 有 children，write_content=true 无 children）
- 字数分配合理性（总字数 ≥ 预期总字数，单节点字数在 100~8000 范围内）
- chart_count 与 charts 数组长度一致性

**校验结果处理**：
- `valid=true`：继续步骤5
- `valid=false`：阅读 `errors` 和 `warnings`，调用 outline-agent 修正后重新校验

### 步骤5：生成 outline.md

调用 `generate_outline_md(workspace_path)` 根据 outline.json 生成人类可读的 Markdown 格式大纲。

**生成位置**：`bid_project/<工作空间>/proposal_file/outline.md`

**格式规范**：参考附件3-大纲JSON结构规范.md 的「4. markdown 大纲格式规范」

生成后，主控 Agent 应**直接阅读** outline.md，对大纲内容进行整体审查，确认结构合理、字数分配均衡、图表规划恰当。

### 步骤6：提交大纲确认

使用 `AskUserQuestion` 工具提交大纲供用户确认。

**AskUserQuestion 调用示例**：

```json
{
  "questions": [
    {
      "question": "大纲已生成，请审查 outline.md 后确认。\n\n【文件位置】bid_project/<工作空间>/proposal_file/outline.md\n\n【大纲概要】\n- 共 <N> 个一级评审因素\n- 共 <M> 个需撰写正文的叶子节点\n- 总字数分配：<总字数> 字（预期 <预期总字数> 字）\n- 图表规划：<图表数量> 个\n\n请确认大纲是否符合预期，或提出修改意见。",
      "header": "确认大纲",
      "multiSelect": false,
      "options": [
        {"label": "确认大纲", "description": "大纲符合预期，继续生成目录结构"},
        {"label": "需要修改", "description": "大纲需要调整，我将提供修改意见"}
      ]
    }
  ]
}
```

**用户确认**：继续步骤7。

**用户不确认**：进入大纲修改循环：
1. 主控 Agent 收集用户修改意见，整理成结构化需求列表
2. 主控 Agent 调用 outline-agent，传递修改意见
3. outline-agent 根据修改意见更新 outline.json
4. 主控 Agent 调用 `validate_outline_structure` 重新验证
5. 主控 Agent 调用 `generate_outline_md` 重新生成
6. 主控 Agent 再次提交大纲供用户确认
7. 重复步骤1-6，直到用户确认为止

**修改循环限制**：最多重试 3 次。如果用户仍然不确认，暂停流程，人工介入协调。

**特殊情况处理**：如果用户长时间不确认或反馈模糊，主控 Agent 可主动询问用户具体修改意见，引导用户明确需求。

### 步骤7：生成目录结构

用户确认大纲后，调用 `generate_directory_structure(workspace_path)` 创建 proposal_file 目录结构。

**生成内容**：
- 创建 `proposal_file/` 目录（如不存在）
- 为每个非叶子节点（`write_content=false`）创建目录文件夹，命名格式：`{node_id}_{title}`（例如 `1_1_整体项目理解`）
- 为每个叶子节点（`write_content=true`）创建 `.md` 文件，命名格式：`{node_id}_{title}.md`（例如 `1_1_1_需求分析.md`）
- `.md` 文件内容：自动添加对应层级的标题（例如 `### 需求分析`）

### 步骤8：更新项目状态

调用 `update_metadata_status(workspace_path, "大纲确认完成")` 更新项目状态。

---

## API Reference

### read_input_files

**功能**：校验所有输入文件存在性（不读取文件内容，仅 metadata.json 读取关键字段）

**参数**：
- `workspace_path`: str - 工作空间路径
- `package`: str - 标段编号（如 "1"、"2"、"3"，不分标段时传 "1"）

**返回**：
```python
{
    'success': bool,
    'result': {
        'files': list,           # 已存在的文件相对路径列表
        'missing_files': list,   # 缺失文件相对路径列表
        'empty_files': list,     # 空文件相对路径列表
        'metadata': {            # metadata.json 关键字段
            '预期总字数': str,
            '采购方式': str,
            '当前需撰写标段': str
        }
    }
}
```

### validate_outline_structure

**功能**：验证 outline.json 结构完整性

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'valid': bool,
    'errors': list,        # 错误列表（必须修正）
    'warnings': list,     # 警告列表（建议修正）
    'stats': {            # 大纲统计
        'total_nodes': int,
        'leaf_nodes': int,
        'total_word_count': int,
        'expected_word_count': int,
        'chart_count': int
    }
}
```

### generate_outline_md

**功能**：根据 outline.json 生成 outline.md

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'outline_md_path': str,   # 生成的 outline.md 路径
    'stats': dict              # 大纲统计
}
```

### generate_directory_structure

**功能**：根据 outline.json 生成 proposal_file 目录结构

生成包含层级关系的目录文件夹结构，在对应目录文件夹内存放.md文件：
- 目录文件夹命名格式：`{node_id}_{title}`（例如 `1_1_整体项目理解`）
- .md文件命名格式：`{node_id}_{title}.md`（例如 `1_1_1_需求分析.md`）
- .md文件内容：自动添加对应层级标题（例如 `### 需求分析`）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool,
    'proposal_dir': str,      # proposal_file 目录路径
    'created_files': list,    # 创建的 .md 文件路径列表
    'created_dirs': list,     # 创建的目录文件夹路径列表
    'total_nodes': int        # 创建的文件总数
}
```

### update_metadata_status

**功能**：更新 metadata.json 项目状态

**参数**：
- `workspace_path`: str - 工作空间路径
- `status`: str - 项目状态值（默认：大纲确认完成）

**返回**：
```python
{
    'success': bool,
    'status': str,
    'updated_fields': list
}
```

---

## run_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 校验输入文件存在性
python .trae/scripts/run_skill.py outline_writing read_input_files --workspace_path "bid_project/test" --package 2

# 校验 outline.json 结构完整性
python .trae/scripts/run_skill.py outline_writing validate_outline_structure --workspace_path "bid_project/test"

# 生成 outline.md
python .trae/scripts/run_skill.py outline_writing generate_outline_md --workspace_path "bid_project/test"

# 生成 proposal_file 目录结构
python .trae/scripts/run_skill.py outline_writing generate_directory_structure --workspace_path "bid_project/test"

# 更新项目状态
python .trae/scripts/run_skill.py outline_writing update_metadata_status --workspace_path "bid_project/test" --status "大纲确认完成"
```

**注意**：outline.json 由 outline-agent 使用 Write 工具直接创建（非脚本生成）。outline.md 和目录结构由 SKILL.py 生成。

**返回格式**：JSON 格式
```json
{"success": true, "result": {...}}
```

---

## 特殊情况处理机制

### 用户响应超时处理

**超时阈值配置**：
- 配置文件：`.trae/hooks.json` 或项目配置文件中可配置
- 默认值：30 分钟
- 配置项名称：`user_response_timeout_minutes`

**超时检测机制**：
- 每次调用 `AskUserQuestion` 工具时，记录提问时间
- 定期检查用户是否已响应
- 超过超时阈值仍未响应时，自动触发兜底方案

**兜底方案**：
主控 Agent 根据已提取的相关文件内容，结合内置联网搜索工具收集足够信息，生成包含标题及范围的二级大纲，传递给 outline-agent 执行大纲撰写（生成 outline.json）。

**超时处理流程**：
1. 检测到用户响应超时
2. 记录超时事件日志（超时时间、用户最后交互时间、触发的兜底方案）
3. 执行兜底方案（自动生成二级大纲）
4. 继续执行后续流程（大纲校验、生成目录结构等）
5. 在最终交付时，向用户说明超时处理情况

### 其他特殊场景处理

#### 场景1：outline-agent 执行超时

**识别条件**：outline-agent 在规定时间内未完成大纲编写任务

**处理流程**：
1. 记录超时日志
2. 主动询问 outline-agent 任务进度
3. 如仍无响应，调用 outline-agent 重新执行
4. 最多重试 2 次，仍失败则暂停流程，人工介入

#### 场景2：大纲校验多次不通过

**识别条件**：连续 3 次调用 `validate_outline_structure` 返回 `valid=false`

**处理流程**：
1. 汇总所有错误信息
2. 调用 outline-agent 一次性修正所有问题
3. 重新校验
4. 如仍不通过，暂停流程，人工介入协调

#### 场景3：文件权限不足

**识别条件**：生成 outline.md 或目录结构时出现权限错误

**处理流程**：
1. 记录权限错误日志
2. 尝试使用管理员权限重新执行
3. 如仍失败，提示用户检查目录权限设置

#### 场景4：网络搜索服务不可用（方案1依赖）

**识别条件**：方案1（AI补充生成）执行时联网搜索工具不可用

**处理流程**：
1. 记录网络错误日志
2. 自动切换到方案2（提示用户提供二级大纲）
3. 向用户说明网络状况及切换原因

### 日志记录要求

**所有特殊情况处理必须记录详细日志**，日志内容包括：

| 记录类型 | 记录内容 |
|---------|---------|
| 异常类型 | 异常分类（如 evaluation_criteria_missing、user_timeout、agent_timeout 等） |
| 检测时间 | 异常检测的具体时间戳 |
| 检测条件 | 触发异常的具体条件和判断依据 |
| 处理步骤 | 执行的处理步骤和操作记录 |
| 用户交互 | 用户的选择、反馈内容（如有） |
| 最终决策 | 最终采用的解决方案和决策依据 |
| 处理结果 | 处理后的状态和结果 |

**日志记录方式**：
- 通过 TodoWrite 工具记录关键节点
- 在 metadata.json 中添加「异常处理日志」字段
- 确保日志信息完整、可追溯，便于问题排查和审计

---

## Error Handling

| 错误类型 | 处理方式 |
|---------|---------|
| metadata.json 不存在 | 提示用户先执行阶段一、二、三 |
| 项目状态非「信息补充完成」 | 提示当前状态，引导用户从正确阶段继续 |
| 输入文件缺失 | 报告缺失文件列表，提示用户补充 |
| outline.json 不存在 | 提示主控 Agent 先调用 outline-agent 生成大纲 |
| outline.json 格式无效 | 报告具体错误，调用 outline-agent 修正 |
| outline.json 校验不通过 | 报告 errors 和 warnings，调用 outline-agent 修正 |
| outline.md 生成失败 | 检查 outline.json 是否有效，尝试重新生成 |
| 目录结构生成失败 | 检查目录权限，尝试重试 |
| 用户拒绝大纲且无法达成共识 | 暂停流程，人工介入协调 |
| outline-agent 调用失败 | 主控 Agent 重试或提示用户检查子智能体状态 |
| 技术评分标准内容缺失 | 执行异常报告处理流程（详见步骤3） |
| 用户响应超时 | 自动触发兜底方案（生成二级大纲） |
| outline-agent 执行超时 | 重试或暂停流程，人工介入 |
| 文件权限不足 | 记录日志，提示用户检查权限设置 |
| 网络搜索服务不可用 | 切换到备用方案（提示用户提供大纲） |

## Limitations

- outline-agent 调用依赖 TraeCode 的 Subagent 调度机制
- 大纲的解析、构建、字数分配、图表判断等智能工作由 outline-agent 完成
- outline.json 由 outline-agent 使用 Write 工具直接创建（非脚本生成）
- SKILL.py 仅负责文件操作和校验，无智能逻辑
- 用户交互依赖 TraeCode 内置的 AskUserQuestion 工具
