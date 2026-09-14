---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - File Conversion Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: file_conversion
description: 将招标文件及附件（.doc/.docx/.pdf）转换为 Markdown 格式，创建项目工作空间并按规范存储
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: conversion
tags:
  - office
  - markdown
  - conversion
  - bid_documents
department: All

# AI Model Compatibility
models:
  recommended:
    - claude-sonnet-4
    - claude-opus-4
  compatible:
    - claude-3-5-sonnet
    - gpt-4
    - gpt-4o

# Skill Capabilities
capabilities:
  - office_conversion
  - workspace_creation
  - error_reporting

# Language Support
languages:
  - zh
---

# 文件转换 Skill

## Overview

本 Skill 用于将招标文件及附件（.doc/.docx/.pdf）转换为 Markdown 格式，同时创建项目工作空间并按规范存储转换后的文件。基于 Microsoft 开源的 `markitdown` 库实现转换。

## How to Use

### 完整工作流程（必须严格按顺序执行）

1. **文件转换**：提供招标文件及附件文件列表，调用 `convert_documents(files)` 方法
2. **阅读内容**：读取转换后的 `01_source.md`、`02_source.md` 等文件，理解每个文件的内容
3. **确定命名**：根据文件内容判断文件类型，对照文件命名规范确定最终文件名
4. **批量重命名**：调用 `rename_files(workspace_path, rename_map)` 方法完成重命名
5. **提取关键信息并回填**：从转换后的 .md 文件中提取项目核心信息，调用 `update_metadata_fields(workspace_path, fields)` 回填到 metadata.json

**Example prompts:**

- "将这些招标文件转换为 Markdown"
- "创建项目工作空间并转换文件"
- "处理招标文件上传，转换为 .md 格式"

**完整操作示例：**

```python
# 步骤1：转换文件
result = convert_documents([
    "招标文件.docx",
    "技术要求.docx",
    "评审标准.pdf"
])
workspace = result["workspace_path"]

# 步骤2：阅读转换后的文件（Agent 自动识别读取）
# 读取 source_file/“01_source.md”、source_file/“02_source.md”、source_file/“03_source.md”...等 → 发现文件类型


# 步骤3：构建重命名映射
rename_map = {
    "01_source.md": "01_Bidding_Documents.md",
    "02_source.md": "02_Technical_Requirements.md",
    "03_source.md": "04_Evaluation_Criteria.md",
    "{N}_<更多文件>.md":"{N}_<内容描述>.md"
}

# 步骤4：执行重命名
rename_result = rename_files(workspace, rename_map)

# 步骤5：从转换后的 .md 文件中提取关键信息并回填 metadata.json
# Agent 阅读重命名后的招标文件（如 01_Bidding_Documents.md），提取以下信息：
fields = {
    "项目编号": "HBZB-2026-123456",
    "项目名称": "XXX信息系统集成项目",
    "采购方式": "公开招标",
    "是否分标段": "否",
    "项目标段数": "1"
}
update_result = update_metadata_fields(workspace, fields)
```

## Domain Knowledge

### 文件命名规范

文件命名分为两个阶段：

**阶段一：转换时命名（按上传顺序编码）**

转换后的文件先按上传顺序编码命名，存储在 `source_file/` 目录下：

| 格式 | 示例 |
|------|------|
| `01_source.md` | 第一个上传的文件 |
| `02_source.md` | 第二个上传的文件 |
| `03_source.md` | 第三个上传的文件 |
| `{N}_<更多文件>.md` | 其他根据内容上传的文件 |

**阶段二：阅读后重命名（按内容确定）**

Agent 阅读转换后的文档内容后，根据文件内容确定最终命名：

| 序号  | 文件名                            | 说明           | 是否必需 |
| --- | ------------------------------ | ------------ | ---- |
| 01  | 01\_Bidding\_Documents.md      | 招标文件         | 必需   |
| 02  | 02\_Technical\_Requirements.md | 技术要求附件       | 可选   |
| 03  | 03\_procurement\_list.md       | 采购（服务/工程量）清单 | 可选   |
| 04  | 04\_Evaluation\_Criteria.md    | 评审标准附件       | 可选   |
| 05  | 05\_Construction\_design.md    | 施工设计说明       | 可选   |
| 06  | 06\_Proposal\_scheme.md        | 方案建议书        | 可选   |
| 07+ | 07\_<内容描述>.md                   | 其它附件         | 可选   |

**重命名流程**：调用 `rename_files()` 函数，传入重命名映射字典 `{'01_source.md': '01_Bidding_Documents.md', ...}`

### 文件内容识别规则

Agent 阅读转换后的文件时，应根据以下规则判断文件类型：

| 文件类型 | 识别关键词（中文） | 识别关键词（英文） |
|----------|-------------------|-------------------|
| 招标文件 | 招标公告、竞争性磋商、投标人须知、投标邀请、招标文件 | bidding document, tender document, invitation to bid |
| 技术要求 | 技术参数、技术规范、性能指标、系统架构、技术要求 | technical requirements, technical specifications |
| 采购清单 | 采购内容、工程量清单、服务清单、采购需求 | procurement list, bill of quantities, purchase requirements |
| 评审标准 | 评审办法、评分标准、综合评分法、评审程序 | evaluation criteria, scoring standards, review method |
| 施工设计 | 施工组织设计、设计方案、实施方案、施工方案 | construction design, design plan, implementation plan |
| 方案建议 | 方案建议书、可行性研究、技术方案 | proposal, feasibility study, technical proposal |

### 转换完成后的强制操作

**⚠️ 重要**：文件转换完成后，Agent **必须**执行以下操作：

1. **读取所有转换后的文件**：依次读取 `source_file/` 目录下的 `01_source.md`、`02_source.md` 等文件
2. **识别文件内容**：根据上述文件内容识别规则判断每个文件的类型
3. **确定最终文件名**：对照文件命名规范，为每个文件确定最终文件名
4. **执行批量重命名**：调用 `rename_files(workspace_path, rename_map)` 完成重命名
5. **验证重命名结果**：检查 `source_file/` 目录下的文件是否已正确重命名
6. **提取关键信息**：从重命名后的招标文件（如 `01_Bidding_Documents.md`）中提取以下核心信息：
   - **项目编号**：招标文件中注明的项目编号
   - **项目名称**：招标文件中注明的项目名称
   - **采购方式**：招标文件中的采购方式（如：公开招标、竞争性磋商、竞争性谈判、单一来源等）
   - **是否分标段**：根据招标文件内容判断是否分标段（"是"或"否"）
   - **项目标段数**：招标文件中的标段总数（不分标段时为"1"）
7. **回填 metadata.json**：调用 `update_metadata_fields(workspace_path, fields)` 将提取的关键信息回填

**只有完成关键信息回填，阶段一才算真正完成！**

### 工作空间命名规则

项目工作空间目录命名：`<系统当前日期和时间（YYYYMMDD HHMMSS）>_<随机字符>`

目录结构：

```
bid_project/
  └── 20260717 103000_HBZB-2026-123456_XXX项目/
      ├── source_file/           # 转换后的招标文件
      ├── extraction_file/       # 提取的关键信息
      ├── proposal_file/         # 技术方案章节和正文
      ├── review_file/           # 审查结果和优化报告
      └── final_document_file/   # 最终文档
```

### 支持的格式

| 格式           | 扩展名   | 转换方式                                       | 说明                     |
| ------------ | ----- | ------------------------------------------ | ---------------------- |
| Word (.docx) | .docx | markitdown 直接转换                            | 完整支持标题、表格、加粗、斜体、列表、超链接 |
| Word (.doc)  | .doc  | 先转为 .docx（使用 libreoffice），再用 markitdown 转换 | 旧版二进制格式，需要额外工具支持       |
| PDF          | .pdf  | markitdown 直接转换                            | 文本提取，部分表格支持            |

## API Reference

### convert_documents

**功能**：转换招标文件及附件，创建项目工作空间

**参数**：

- `files`: list - 文件路径列表

**返回**：

```python
{
    'success': bool,           # 是否全部转换成功
    'workspace_path': str,     # 工作空间路径
    'converted_files': list,   # 成功转换的文件列表
    'failed_files': list,      # 转换失败的文件列表及原因
    'error_report': str,       # 错误报告（如有）
    'metadata_created': bool   # 是否创建了 metadata.json
}
```

### create_workspace

**功能**：创建项目工作空间目录结构

**参数**：

- `timestamp`: str - 时间戳（YYYYMMDD HHMMSS）

**返回**：

```python
{
    'workspace_path': str,      # 工作空间路径
    'directories_created': list # 创建的目录列表
}
```

### rename_files

**功能**：批量重命名 source_file 目录下的 .md 文件

**参数**：

- `workspace_path`: str - 工作空间路径
- `rename_map`: dict - 重命名映射（原文件名 -> 新文件名）

**返回**：

```python
{
    'success': bool,           # 是否全部重命名成功
    'success_count': int,      # 成功重命名的文件数量
    'failed_count': int,       # 重命名失败的文件数量
    'renamed_files': list,     # 成功重命名的文件列表
    'failed_files': list       # 重命名失败的文件列表及原因
}
```

### update_metadata_fields

**功能**：更新 metadata.json 中的指定字段（供 Agent 回填关键信息）

Agent 阅读转换后的 .md 文件后，提取项目编号、项目名称、项目类型、是否分标段、项目标段数等关键信息，调用本函数回填到 metadata.json。

**参数**：

- `workspace_path`: str - 工作空间路径
- `fields`: dict - 需要更新的字段及值，例如：

```python
{
    '项目编号': 'HBZB-2026-123456',
    '项目名称': 'XXX信息系统集成项目',
    '项目类型': '服务',
    '是否分标段': '否',
    '项目标段数': '1'
}
```

**返回**：

```python
{
    'success': bool,           # 是否更新成功
    'updated_fields': dict     # 实际更新的字段及值
}
```

## run_skill.py 调用方式

当 Agent 无法直接导入本 Skill 模块时，可通过命令行调用 `run_skill.py`：

```bash
# 转换文件并创建工作空间
python .trae/scripts/run_skill.py file_conversion convert_documents --files "招标文件.docx" "技术要求.docx"

# 批量重命名文件
python .trae/scripts/run_skill.py file_conversion rename_files --workspace_path "bid_project/test" --rename_map '{"01_source.md": "01_Bidding_Documents.md"}'

# 回填关键信息到 metadata.json
python .trae/scripts/run_skill.py file_conversion update_metadata_fields --workspace_path "bid_project/test" --fields '{"项目编号": "HBZB-2026-123456", "项目名称": "XXX项目", "采购方式": "公开招标", "是否分标段": "否", "项目标段数": "1"}'
```

**返回格式**：JSON 格式
```json
{"success": true, "result": {...}}
```

## Installation

```bash
pip install markitdown
```

## Limitations

- .doc 格式需要安装 libreoffice 并添加到系统 PATH
- 复杂表格转换可能不完全准确
- 图片不嵌入 Markdown，仅保留文字内容
- PDF 扫描件无法提取文字（需 OCR 工具）

## Error Handling

转换失败时生成错误报告，包含：

- 失败文件名
- 失败原因
- 建议的处理方案

