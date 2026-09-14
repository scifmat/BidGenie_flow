---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Document Parsing Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: document_parsing
description: 主控Agent调用，用于协调子智能体从招标文件中提取关键信息，创建目录结构，校验提取结果，回填元数据，更新项目状态
version: "3.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - document
  - parsing
  - information_extraction
  - bid_documents
  - agent_orchestration
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
  - agent_orchestration
  - directory_structure
  - extraction_validation
  - metadata_validation
  - status_update

# Language Support
languages:
  - zh
---

# 文档解析 Skill

## Overview

本 Skill 面向**主控 Agent**，用于协调子智能体（extract-info-agent）从招标文件中提取关键信息。主控 Agent 通过本 Skill 了解职责分工、辅助脚本功能、目录结构规范和提取分类。

## 职责分工

### 主控 Agent 职责（流程编排 + 质量把关）

| 职责     | 说明                                                 |
| ------ | -------------------------------------------------- |
| 流程编排   | 管理文件分析阶段整体流程，自主决定子智能体启动数量和方式                       |
| 子智能体调度 | 根据项目情况自行决策调度策略（并行/串行/单次/多次）                        |
| 模板分配   | 为子智能体指明需要参考的模板文件路径                                 |
| 完整性校验  | 子智能体完成后，直接阅读提取文件校验内容完整性                            |
| 元数据校验  | 调用 SKILL.py 校验 01\_Basic\_Information.md 与 metadata.json 中阶段一已回填字段的一致性（不覆盖） |
| 状态更新   | 校验通过后更新项目状态为「文件分析完成」                               |
| 结果汇总   | 汇总执行结果，生成阶段完成报告                                    |

### 子智能体（extract-info-agent）职责（信息提取执行）

| 职责     | 说明                                   |
| ------ | ------------------------------------ |
| 读取招标文件 | 读取 source\_file/ 下所有文件               |
| 读取参考模板 | 读取主控 Agent 指定的模板文件                   |
| 提取关键信息 | 根据模板从招标文件中提取信息                       |
| 写入提取文件 | 使用 Write 工具写入 extraction\_file/ 对应目录 |
| 结果反馈   | 返回提取执行报告                             |

### 职责边界

| 操作      | 主控 Agent               | 子智能体 |
| ------- | ---------------------- | ---- |
| 创建目录结构  | ✅（调用 SKILL.py）         | ❌    |
| 读取招标文件  | ✅（需了解招标文件，后续验证提取内容时对照） | ✅    |
| 读取参考模板  | ❌                      | ✅    |
| 提取关键信息  | ❌                      | ✅    |
| 写入提取文件  | ❌                      | ✅    |
| 校验提取完整性 | ✅（直接阅读文件）              | ❌    |
| 校验元数据   | ✅（调用 SKILL.py）         | ❌    |
| 更新项目状态  | ✅（调用 SKILL.py）         | ❌    |

## 工作流程

### 主控 Agent 执行流程

```
步骤1: 确定工作空间
    ↓
步骤2: 读取 metadata.json，确认项目状态为「文件上传完成」
    ↓
步骤3: 判断标段情况（自行决策，可预提取关键信息辅助判断）
    ↓
步骤4: 调用 SKILL.py 的 create_extraction_structure 创建目录结构
    ↓
步骤5: 启动子智能体提取信息
        — 主控自行决策：启动几个子智能体、串行还是并行
        — 为每个子智能体指明参考模板路径和输出目录
    ↓
步骤6: 校验提取结果（直接阅读 extraction_file/ 下的文件）
        — 检查文件是否全部生成
        — 检查关键必填项是否有内容（项目编号、项目名称、采购方式、资格要求、评分标准等）
        — 【语义校验】阅读关键提取文件（如 07_Evaluation_Criteria.md）验证评分标准完整性，确保技术评分项、商务评分项、价格评分项均已提取，无遗漏重要评分指标
    ↓
步骤7: 校验通过后，调用 SKILL.py 的 update_metadata_from_extraction 校验元数据一致性
        — 项目编号、项目名称、采购方式、是否分标段、项目标段数已在阶段一由 Agent 回填
        — 本步骤仅做一致性校验，不覆盖阶段一已回填的值
        — 如发现不一致，Agent 应人工判断以哪个为准并手动修正
    ↓
步骤8: 调用 SKILL.py 的 update_metadata_status 更新项目状态
    ↓
步骤9: 生成阶段完成报告
```

### 完整性校验指南

主控 Agent 应在子智能体完成后，直接阅读提取文件进行校验：

1. **文件存在性**：确认 extraction\_file/ 下 9 个文件全部存在
2. **内容完整性**：重点检查以下关键字段是否有实际内容（非空、非"待确认"）
   - `01_Basic_Information.md`：项目编号、项目名称、预算金额、投标截止时间、采购单位
   - `02_Eligibility_Review.md`：投标人的资格要求
   - `06_Procurement_Content.md`：采购内容
   - `07_Evaluation_Criteria.md`：技术评分标准
3. **格式一致性**：各文件格式是否与模板的「输出示例」一致

**重要**：校验由主控 Agent 通过阅读文件自行完成，不依赖脚本自动化判断。如果发现缺失，可启动子智能体或自行补提，失败时可请人工介入。

**注：**确认招标文件及附件中某些关键信息缺失时，校验可忽略；

## 目录结构

### 模板目录（供子智能体参考）

```
.agents/skills/document_parsing/templates/
  ├── common_file/           # 公共信息模板
  │   ├── 01_Basic_Information.md
  │   ├── 02_Eligibility_Review.md
  │   ├── 03_Invalid_Bid_Item.md
  │   ├── 04_Compilation_Requirements.md
  │   └── 05_Substantive_Response.md
  └── packages_file/         # 标段专属信息模板
      ├── 06_Procurement_Content.md
      ├── 07_Evaluation_Criteria.md
      ├── 08_Business_Requirements.md
      └── 09_Technical_Requirements.md
```

### 输出目录（提取结果存储）

```
bid_project/<项目工作空间>/extraction_file/
  ├── common_file/           # 公共信息
  │   ├── 01_Basic_Information.md
  │   ├── 02_Eligibility_Review.md
  │   ├── 03_Invalid_Bid_Item.md
  │   ├── 04_Compilation_Requirements.md
  │   └── 05_Substantive_Response.md
  └── packages_file/         # 标段专属信息
      ├── package_1/
      │   ├── 06_Procurement_Content.md
      │   ├── 07_Evaluation_Criteria.md
      │   ├── 08_Business_Requirements.md
      │   └── 09_Technical_Requirements.md
      └── package_N/
          └── ...
```

## 信息提取分类

| 类别         | 提取文件                         | 存储路径                                          |
| ---------- | ---------------------------- | --------------------------------------------- |
| 公共信息（5类）   | 基础信息、资格审查、无效投标项、编制要求、实质性应标资料 | extraction\_file/common\_file/                |
| 标段专属信息（4类） | 采购内容、评审标准、商务要求、技术服务要求        | extraction\_file/packages\_file/package\_{N}/ |

## 提取原则

| 原则  | 说明                     |
| --- | ---------------------- |
| 完整性 | 确保所有关键信息都被提取，不遗漏重要条款   |
| 准确性 | 提取内容应与招标文件原文一致，不得篡改或臆测 |
| 规范性 | 按照统一模板格式存储，便于后续读取和使用   |
| 适应性 | 对不同采购方式、不同行业的招标文件具有适应性 |

## API Reference

### create\_extraction\_structure

**功能**：创建 extraction\_file 目录结构

**参数**：

- `workspace_path`: str - 工作空间路径
- `package_count`: int - 标段数量（默认1）

**返回**：

```python
{
    'success': bool,
    'directories_created': list,
    'extraction_path': str
}
```

### update\_metadata\_from\_extraction

**功能**：校验 01\_Basic\_Information.md 与 metadata.json 中阶段一已回填字段的一致性

**⚠️ 重要**：项目编号、项目名称、采购方式、是否分标段、项目标段数已在阶段一由 Agent 从招标文件中提取并回填。本函数不再覆盖这些字段，仅做一致性校验。

**参数**：

- `workspace_path`: str - 工作空间路径
- `package_count`: int - 标段数量（默认1）

**校验字段**：

- 项目编号、项目名称、采购方式（从提取文件解析，与 metadata.json 对比）
- 是否分标段、项目标段数（与 metadata.json 对比）

**返回**：

```python
{
    'success': bool,
    'extracted_fields': dict,    # 提取文件中解析到的值
    'metadata_values': dict,     # metadata.json 中已有的值
    'inconsistencies': dict,     # 不一致的字段及双方值
    'note': str                  # 说明信息
}
```

### update\_metadata\_status

**功能**：更新 metadata.json 的项目状态

**参数**：

- `workspace_path`: str - 工作空间路径
- `status`: str - 项目状态值（默认：文件分析完成）

**返回**：

```python
{
    'success': bool,
    'status': str,
    'updated_fields': list
}
```

### get\_template\_path

**功能**：获取参考模板文件路径

**参数**：

- `template_name`: str - 模板文件名

**返回**：

```python
str  # 模板文件路径
```

## run_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 创建提取目录结构
python .trae/scripts/run_skill.py document_parsing create_extraction_structure --workspace_path "bid_project/test" --package_count 3

# 校验提取文件存在性
python .trae/scripts/run_skill.py document_parsing check_extraction_files --workspace_path "bid_project/test/extraction_file" --package_count 3

# 校验元数据一致性
python .trae/scripts/run_skill.py document_parsing update_metadata_from_extraction --workspace_path "bid_project/test" --package_count 3

# 更新项目状态
python .trae/scripts/run_skill.py document_parsing update_metadata_status --workspace_path "bid_project/test" --status "文件分析完成"

# 获取模板路径
python .trae/scripts/run_skill.py document_parsing get_template_path --files "01_Basic_Information.md"
```

**返回格式**：JSON 格式
```json
{"success": true, "result": {...}}
```

## Error Handling

| 错误类型              | 处理方式                        |
| ----------------- | --------------------------- |
| 工作空间不存在           | 提示用户先执行阶段一                  |
| 标段数量为0            | 默认为1个标段                     |
| 提取不完整             | 主控 Agent 阅读文件判断，缺失项要求子智能体补提 |
| metadata.json 不存在 | 自动创建并初始化                    |
| 子智能体调用失败 | 主控 Agent 重试或提示用户检查子智能体状态 |
| 子智能体运行异常或超时 | 主控 Agent 重启该子智能体或提示用户检查子智能体日志 |

## Limitations

- 子智能体调用依赖 TraeCode 的 Subagent 调度机制
- 复杂招标文件的提取可能需要人工辅助验证
- 校验由主控 Agent 通过阅读文件进行，非自动脚本判断

