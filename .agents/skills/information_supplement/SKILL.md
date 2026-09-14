---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Information Supplement Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: information_supplement
description: 主控Agent调用，用于阶段三信息补充——确认标段与字数并回填metadata.json，读取提取文件供Agent分析招标文件要求，Agent使用Write工具直接创建Supplementary_info.md（适配项目类型），提示用户手动填写，校验填写完整性后更新项目状态
version: "3.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - information_supplement
  - user_interaction
  - metadata
  - supplementary_info
  - phase3
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
  - user_interaction
  - metadata_backfill
  - completeness_validation

# Language Support
languages:
  - zh
---

# 信息补充 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段三（信息补充）的完整流程。主控 Agent 通过本 Skill 与用户交互，确认标段与字数，**直接使用 Write 工具创建** Supplementary_info.md（适配项目类型），提示用户手动填写，并完成完整性校验。

**重要**：阶段三无 Subagent 参与，所有工作由主控 Agent 直接完成。

## 前置条件

- 项目状态为「文件分析完成」
- extraction_file 目录下有完整的提取文件（9 类）
- metadata.json 已包含项目编号、项目名称、采购方式、是否分标段、项目标段数

## 工作流程

```
步骤1: 确定工作空间，读取 metadata.json 确认项目状态
    ↓
步骤2: 第一步——确认关键参数
  ├─ 标段确认（如分标段）→ AskUserQuestion → 回填 metadata.json
  └─ 字数确认 → AskUserQuestion → 回填 metadata.json
    ↓
步骤3: 第二步——创建模板并等待用户填写
  ├─ 读取提取文件，分析 7 类补充信息的招标文件要求
  ├─ Agent 使用 Write 工具直接创建 Supplementary_info.md（适配项目类型）
  └─ AskUserQuestion 提示用户填写模板 → 等待用户完成
    ↓
步骤4: 第三步——校验与完成
  ├─ 调用 validate_supplementary_info 校验完整性
  ├─ 直接阅读文件执行语义检查，必要时整理优化
  └─ 更新 metadata.json 项目状态为「信息补充完成」
```

---

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录（可根据 metadata.json 中的工作空间路径定位）
2. 读取 `metadata.json`，确认「项目状态」为「文件分析完成」
3. 读取「是否分标段」「项目标段数」「采购方式」字段，判断后续是否需要标段确认及项目类型

### 步骤2：确认关键参数

#### 2a. 标段确认（仅分标段时执行）

**触发条件**：`metadata.json` 中「是否分标段」为「是」。

**执行方式**：调用 `AskUserQuestion` 工具，向用户确认当前需撰写的标段。

**关键规则**：
- 一个项目工作空间**仅允许针对一个标段**撰写技术方案
- 如用户指定多个标段，**拒绝请求**并提示用户新开对话重新上传招标文件
- 不分标段时跳过本步骤，「当前需撰写标段」默认填充为「01」

**AskUserQuestion 调用示例**（假设 3 个标段）：

```json
{
  "questions": [
    {
      "question": "本项目分 3 个标段，请确认当前需撰写技术方案的标段。注意：一个工作空间仅针对一个标段撰写方案，如需撰写多个标段请新开对话。",
      "header": "确认标段",
      "multiSelect": false,
      "options": [
        {"label": "标段1", "description": "撰写第 01 标段的技术方案"},
        {"label": "标段2", "description": "撰写第 02 标段的技术方案"},
        {"label": "标段3", "description": "撰写第 03 标段的技术方案"}
      ]
    }
  ]
}
```

> 若标段数超过 4 个，options 中放前 3 个标段，用户可通过「Other」输入其它标段编号。

**回填**：获取用户选择后，调用 `update_metadata_package(workspace_path, package)` 回填「当前需撰写标段」字段。

#### 2b. 字数确认

**执行方式**：调用 `AskUserQuestion` 工具，向用户确认方案预期总字数。

**AskUserQuestion 调用示例**：

```json
{
  "questions": [
    {
      "question": "请确认技术方案的预期总字数（单位：字）。字数将作为大纲字数分配的依据，可在「Other」中输入自定义字数。",
      "header": "确认字数",
      "multiSelect": false,
      "options": [
        {"label": "30000字", "description": "精简版，适合内容较少的项目"},
        {"label": "80000字", "description": "标准版，适合常规项目"},
        {"label": "200000字", "description": "详细版，适合复杂大型项目"}
      ]
    }
  ]
}
```
> 若预设的 3 个字数选项均非用户预期，options 中放前 3 个字数选项，用户可通过「Other」输入其它字数。

**回填**：获取用户选择后，调用 `update_metadata_wordcount(workspace_path, word_count)` 回填「预期总字数」字段。

### 步骤3：创建模板并等待用户填写

#### 3a. 读取提取文件，分析招标文件要求

调用 `read_extraction_for_supplementary(workspace_path, package)` 读取与 7 类补充信息相关的提取文件内容。该函数返回以下文件的内容：

| 文件 | 关联的补充信息类别 |
|-----|-----------------|
| common_file/02_Eligibility_Review.md | 资质情况、人员、设备（资格要求） |
| packages_file/package_N/06_Procurement_Content.md | 设备、人员（采购内容） |
| packages_file/package_N/07_Evaluation_Criteria.md | 资质、人员、荣誉、设备（评审标准） |
| packages_file/package_N/08_Business_Requirements.md | 设备（商务要求） |
| packages_file/package_N/09_Technical_Requirements.md | 人员、设备（技术要求） |

**分析任务**：主控 Agent 阅读返回的文件内容，**语义分析**并归纳出以下 7 类信息各自的「招标文件要求」：

| 补充信息类别 | 分析要点 |
|-----------|---------|
| 1. 投标人基本信息 | 通常无特定招标文件要求，使用默认提示即可 |
| 2. 预计开工日期及进度计划 | 从招标文件中提取开标日期、工期（服务期）、项目启动时限等要求 |
| 3. 投标人的资质情况 | 从 02 资格审查、07 评审标准中提取企业资质、ISO 认证、行业资质等要求 |
| 4. 拟派技术人员的基本情况 | 从 07 评审标准、09 技术要求中提取人员数量、人员资质、技术能力、工作经验等要求 |
| 5. 拟投入的设备情况 | 从07 评审标准、08 商务要求、09 技术要求、或招标文件（`source_file\01_Bidding_Documents.md`）中提取履行合同所需的设备、工具等相关要求 |
| 6. 投标人荣誉 | 从 07 评审标准中提取企业荣誉、个人荣誉等要求 |
| 7. 其它信息 | 从各文件中提取对技术方案有用的其它要求（商务部分可忽略） |

#### 3b. Agent 使用 Write 工具创建 Supplementary_info.md

**参考模板**：`./templates/Supplementary_info_template.md`（同目录下的 templates 文件夹）

**创建步骤**：
1. **读取参考模板**：使用 Read 工具读取 `./templates/Supplementary_info_template.md`
2. **分析招标文件要求**：结合步骤 3a 读取的提取文件内容，针对每类补充信息提取招标文件的具体要求
3. **适配项目类型**：根据 metadata.json 中的「采购方式」判断项目类型（工程施工/服务采购/货物采购），参考模板末尾的「项目类型适配要点」调整各章节内容
4. **生成模板文件**：使用 Write 工具在 `bid_project/<项目工作空间>/Supplementary_info.md` 创建文件

**关键要求**：
- **文件保存位置**：`bid_project/<项目工作空间>/Supplementary_info.md`
- **文件结构**：包含 7 类信息章节，每类章节中「招标文件要求」部分由 Agent 根据提取文件分析结果填写，「投标人补充」部分留占位符 `{{待补充}}` 待用户填写
- **项目类型适配**：根据项目类型调整各章节侧重点

**项目类型适配指导**：

| 项目类型 | 章节适配要点 |
|---------|------------|
| **工程施工** | 章节2侧重工期、施工进度；章节3侧重施工资质（如总承包资质、专业承包资质）；章节4侧重施工人员（项目经理、技术负责人、施工员等）；章节5侧重施工设备（起重机械、运输车辆等） |
| **服务采购** | 章节2侧重服务期、服务启动时间；章节3侧重服务资质（如信息系统集成资质、CMMI等）；章节4侧重服务团队（技术架构师、运维工程师等）；章节5侧重服务工具（运维平台、监控系统等） |
| **货物采购** | 章节2侧重交货期；章节3侧重生产资质、产品认证；章节4侧重安装调试人员；章节5侧重安装工具、检测设备 |

**文件内容规范**：
- 文件头部包含说明：`> 以下信息均以文字性描述补充，无需提供实质性资料（如图片、证书等）`
- 章节 1（投标人基本信息）：表格形式，5 行（名称、地址、电话、邮箱、简介）
- 章节 2~7：每章节包含「招标文件要求：」（Agent 填写）和「投标人补充：」（留 `{{待补充}}` 占位符）
- 招标文件中未要求的章节（2~7），不生成该章节

**创建方式**：Agent 直接使用 Write 工具创建文件，文件内容由 Agent 根据分析结果组织生成

#### 3c. 提示用户填写模板

创建模板后，调用 `AskUserQuestion` 工具提示用户手动填写模板。

**AskUserQuestion 调用示例**：

```json
{
  "questions": [
    {
      "question": "已创建 Supplementary_info.md 模板文件，请手动填写后继续。\n\n【文件位置】bid_project/<工作空间目录>/Supplementary_info.md\n\n【填写规范】\n1. 将表格和各章节中的 {{待补充}} 占位符替换为实际内容\n2. 所有信息均以文字描述形式填写，无需提供实质性资料\n3. 2~7 项以招标文件要求为准，招标文件中未要求的项可填「无」\n4. 填写完成后选择「已完成填写」继续",
      "header": "填写模板",
      "multiSelect": false,
      "options": [
        {"label": "已完成填写", "description": "我已填写完 Supplementary_info.md，请继续校验"},
        {"label": "需要帮助", "description": "我对某些章节不确定，需要指导"}
      ]
    }
  ]
}
```

**等待状态**：发起询问后进入等待状态，直至用户完成填写并选择「已完成填写」。

**若用户选择「需要帮助」**：主控 Agent 针对用户疑问进行解答指导，然后再次发起询问等待用户完成。

### 步骤4：校验与完成

#### 4a. 脚本结构校验

用户完成填写后，调用 `validate_supplementary_info(workspace_path)` 检查：
- 7 类信息章节是否齐全
- 各章节是否仍有未填充的占位符 `{{待补充}}`
- 各章节补充内容是否非空

#### 4b. 主控 Agent 语义自查

主控 Agent **直接读取** Supplementary_info.md，执行以下语义检查：
- **完整性**：7 类信息是否均已补充（用户明确填「无」的可接受）
- **【语义校验】对应性**：阅读每个章节的「招标文件要求」与「投标人补充」内容，验证补充内容是否与招标文件要求对应。例如：招标文件要求 ISO 认证，则补充内容应包含 ISO 认证信息；招标文件要求特定资质级别，则补充内容应明确具备该资质。
- **规范性**：是否仍有 `{{待补充}}` 占位符未替换
- **合理性**：补充内容是否具体详实，避免笼统表述（如"具备相应资质"不如"具备电子与智能化工程专业承包壹级资质，证书编号XXX"）

**校验不通过处理**：
- 若存在占位符未替换，提示用户补充对应章节
- 若语义检查发现明显错误（如答非所问），向用户确认后使用 Write 工具整理优化
- 必要时再次调用 `AskUserQuestion` 让用户修正

#### 4c. 更新项目状态

校验通过后，调用 `update_metadata_status(workspace_path, '信息补充完成')` 更新项目状态。

---

## API Reference

### update_metadata_package

**功能**：回填 metadata.json 的「当前需撰写标段」字段

**参数**：
- `workspace_path`: str - 工作空间路径
- `package`: str - 标段编号/名称

**返回**：
```python
{'success': bool, 'updated_fields': list, '当前需撰写标段': str}
```

### update_metadata_wordcount

**功能**：回填 metadata.json 的「预期总字数」字段

**参数**：
- `workspace_path`: str - 工作空间路径
- `word_count`: int/str - 预期总字数

**返回**：
```python
{'success': bool, 'updated_fields': list, '预期总字数': str}
```

### update_metadata_status

**功能**：更新 metadata.json 项目状态

**参数**：
- `workspace_path`: str - 工作空间路径
- `status`: str - 项目状态值（默认：信息补充完成）

**返回**：
```python
{'success': bool, 'status': str, 'updated_fields': list}
```

### read_extraction_for_supplementary

**功能**：读取与 7 类补充信息相关的提取文件内容，供 Agent 分析招标文件要求

**参数**：
- `workspace_path`: str - 工作空间路径
- `package`: str - 标段编号（不分标段时传 "1"）

**返回**：
```python
{
    'success': bool,
    'files': { '<相对路径>': '<文件内容>' },
    'missing_files': list
}
```

### validate_supplementary_info

**功能**：校验 Supplementary_info.md 完整性（7 类信息）

**参数**：
- `workspace_path`: str - 工作空间路径

**返回**：
```python
{
    'success': bool, 'valid': bool,
    'existing_sections': list, 'missing_sections': list,
    'incomplete_sections': list, 'empty_sections': list,
    'section_details': dict
}
```

---

## run_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 回填标段信息
python .trae/scripts/run_skill.py information_supplement update_metadata_package --workspace_path "bid_project/test" --package "标段1"

# 回填预期总字数
python .trae/scripts/run_skill.py information_supplement update_metadata_wordcount --workspace_path "bid_project/test" --word_count 80000

# 读取提取文件用于分析
python .trae/scripts/run_skill.py information_supplement read_extraction_for_supplementary --workspace_path "bid_project/test" --package 1

# 校验补充信息完整性
python .trae/scripts/run_skill.py information_supplement validate_supplementary_info --workspace_path "bid_project/test"

# 更新项目状态
python .trae/scripts/run_skill.py information_supplement update_metadata_status --workspace_path "bid_project/test" --status "信息补充完成"
```

**注意**：Supplementary_info.md 模板由 Agent 直接使用 Write 工具创建，无需通过脚本生成。参考模板见同目录下的 `templates/Supplementary_info_template.md`。

**返回格式**：JSON 格式
```json
{"success": true, "result": {...}}
```

---

## Error Handling

| 错误类型 | 处理方式 |
|---------|---------|
| metadata.json 不存在 | 提示用户先执行阶段一、二 |
| 项目状态非「文件分析完成」 | 提示当前状态，引导用户从正确阶段继续 |
| 提取文件缺失 | 记录缺失文件，向用户说明缺失情况 |
| 用户指定多个标段 | 拒绝请求，提示用户新开对话重新上传招标文件 |
| Supplementary_info.md 创建失败 | 检查目录权限，尝试重试 |
| 校验不通过（占位符未替换） | 提示用户补充对应章节后重新校验 |
| 校验不通过（内容为空） | 提示用户填写对应章节后重新校验 |

## Limitations

- 用户交互依赖 TraeCode 内置的 AskUserQuestion 工具
- 招标文件要求的语义分析由主控 Agent 完成，非脚本自动化
- Supplementary_info.md 由 Agent 直接创建，用户自行填写补充内容
- 用户填写内容的质量需主控 Agent 语义自查把关
