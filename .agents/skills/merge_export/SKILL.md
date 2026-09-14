---
# ═══════════════════════════════════════════════════════════════════════════════
# BidGenie Flow - Merge Export Skill
# ═══════════════════════════════════════════════════════════════════════════════

# Basic Information
name: merge_export
description: 主控Agent调用，用于阶段八合并导出——校验前置条件（proposal_files_locked），获取outline.json深度优先合并顺序，生成chart_id到图题编号的映射，主控Agent直接执行合并（merge_proposal）、渲染（render_mermaid.py）、Word转换（md_to_docx.py），生成merge_report.md，更新项目状态为"合并导出完成"，通知用户导出完成
version: "1.0"
author: BidGenie Flow Development Team
license: MIT

# Categorization
category: orchestration
tags:
  - merge_export
  - phase8
  - word_export
  - mermaid_render
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
  - document_merging
  - mermaid_rendering
  - word_conversion
  - metadata_update
  - report_generation

# Language Support
languages:
  - zh
---

# 合并导出 Skill

## Overview

本 Skill 面向**主控 Agent**，用于执行阶段八（合并导出）的完整流程。主控 Agent 通过本 Skill 校验前置条件，获取合并顺序和图表映射，**直接执行**合并、渲染和 Word 转换，最终生成 Word 文档和导出报告。

**重要**：阶段八**全部由主控 Agent 直接完成**，不调度任何子智能体（已取消 merge-agent）。合并、统计、图表清单由 SKILL.py 的 `merge_proposal` 函数完成；Mermaid 渲染和 Word 转换由主控 Agent 通过 RunCommand 调用脚本完成。

**职责边界**：
- SKILL.md 指导主控 Agent：如何校验前置条件、如何获取合并顺序、如何生成图表映射、如何调用 merge_proposal、如何调用渲染和转换脚本、如何生成报告、如何更新状态
- SKILL.py：提供前置校验、合并顺序计算、图表映射生成、**合并执行（merge_proposal）**、报告生成、状态管理能力
- export_rules.md：定义导出格式规则、编号标准和字数统计口径，供主控 Agent 参考
- render_mermaid.py：Mermaid 代码块渲染为 PNG 的独立脚本（支持三级降级、--stats-output 直接写统计文件）
- md_to_docx.py：Markdown 转换为 Word 的独立脚本（样式模板+自动编号）

**架构**：两层架构（SKILL.md 指导主控 Agent，主控 Agent 直接执行全部工作）

**前置条件**：
- 阶段七已完成，metadata.json 中 `proposal_files_locked` 为 `true`
- 项目状态为「审查优化全部完成」
- proposal_file 目录下有完整的正文 .md 文件
- outline.json 存在且结构完整
- 环境依赖已安装：python-docx、Pillow（必需）；mermaid-cli/mmdc（可选，缺失时图表降级为占位图）

**产出文件**：
- `final_document_file/merged_proposal_raw.md`（merge_proposal 生成，保留原 Mermaid 代码块）
- `final_document_file/charts_inventory.json`（merge_proposal 生成，图表清单）
- `final_document_file/merge_stats.json`（merge_proposal 生成，合并统计，含耗时）
- `final_document_file/merged_proposal.md`（render_mermaid.py 生成，含图片引用）
- `final_document_file/images/<chart_id>.png`（render_mermaid.py 生成，渲染后的图表图片）
- `final_document_file/<日期>_<项目名称>_技术方案.docx`（md_to_docx.py 生成，最终 Word 文档）
- `final_document_file/merge_report.md`（generate_merge_report 生成，合并导出报告）

## 工作流程

```
步骤1: 确定工作空间，读取 metadata.json 确认项目状态为「审查优化全部完成」
       同时确认 proposal_files_locked 为 true
    ↓
步骤2: 调用 check_export_prerequisites(workspace_path) 校验前置条件
       （校验 outline.json 存在、正文 .md 文件完整、final_document_file 目录可创建、环境依赖可用性）
    ↓
步骤3: 调用 get_merge_order(workspace_path) 获取深度优先合并顺序列表
       （返回有序的节点列表，含 node_id、title、level、write_content、文件路径）
    ↓
步骤4: 调用 generate_chart_mapping(workspace_path) 获取图表映射
       （返回 chart_id → {图题编号, PNG 路径, chart_title, chart_type} 的映射表）
    ↓
步骤5: 主控 Agent 调用 merge_proposal(workspace_path) 直接执行合并
       （SKILL.py 内部完成：读取正文、合并、提取图表清单、统计字数、生成中间文件）
    ↓
    merge_proposal 执行：
    - 获取合并顺序和图表映射（内部调用 get_merge_order 和 generate_chart_mapping）
    - 按合并顺序读取所有正文 .md 文件
    - 按大纲顺序合并 → 生成 merged_proposal_raw.md（保留原 Mermaid 代码块）
    - 提取 Mermaid 代码块，按 chart_id 匹配 → 生成 charts_inventory.json
    - 统计字数（统一口径，参考 export_rules.md 8.5 节）和图表数 → 生成 merge_stats.json（含合并耗时）
    - 返回合并结果统计
    ↓
步骤6: 主控 Agent 调用 render_mermaid.py 渲染 PNG（通过 RunCommand）
       输入：merged_proposal_raw.md → 输出：merged_proposal.md + images/*.png
       （支持三级降级：保留代码块 → 占位图 → 文字描述；--stats-output 直接写 _render_stats.json）
    ↓
步骤7: 主控 Agent 调用 md_to_docx.py 转换 Word（通过 RunCommand）
       输入：merged_proposal.md → 输出：<日期>_<项目名称>_技术方案.docx
       （应用样式模板：标题自动编号、正文宋体小四1.5倍行距、表格表头加粗灰底、图片居中80%宽度）
    ↓
步骤8: 调用 generate_merge_report(workspace_path, export_stats) 生成合并导出报告
       （export_stats 可选，缺失时自动从 merge_stats.json 和 _render_stats.json 汇总）
    ↓
步骤9: 调用 update_metadata_status(workspace_path, "合并导出完成") 更新项目状态
    ↓
步骤10: 主控 Agent 通知用户导出完成（提供文档路径和报告路径）
```

***

## 步骤详解

### 步骤1：确定工作空间与状态确认

1. 在 `bid_project/` 下定位当前项目工作空间目录
2. 读取 `metadata.json`，确认「项目状态」为「审查优化全部完成」
3. 确认 `proposal_files_locked` 字段为 `true`（阶段七锁定）
4. 读取「项目名称」「当前需撰写标段」字段（用于 Word 文件命名）

**前置条件不满足时**：向用户报告当前状态和锁定情况，提示需先完成阶段七人工审查并通过。

### 步骤2：校验前置条件

调用 `check_export_prerequisites(workspace_path)` 校验以下条件：
- `metadata.json` 存在且 `proposal_files_locked` 为 `true`
- `proposal_file/outline.json` 存在且为有效 JSON
- outline.json 中所有 `write_content: true` 的节点有对应的 .md 文件
- `final_document_file/` 目录可创建（如不存在则创建）
- `final_document_file/images/` 目录可创建
- 环境依赖检测：python-docx/Pillow（必需，缺失阻断）、mermaid-cli/mmdc（可选，缺失 warning）

校验失败时返回缺失文件列表，主控 Agent 提示用户检查。

### 步骤3：获取合并顺序

调用 `get_merge_order(workspace_path)` 执行深度优先遍历，返回合并顺序列表。

### 步骤4：生成图表映射

调用 `generate_chart_mapping(workspace_path)` 生成图表映射表。

### 步骤5：主控 Agent 调用 merge_proposal 直接执行合并

调用 `merge_proposal(workspace_path)` 执行合并。本函数**内部自动**完成：
1. 获取合并顺序和图表映射
2. 按合并顺序读取所有正文 .md 文件
3. 按大纲顺序合并生成 `merged_proposal_raw.md`（保留原 Mermaid 代码块）
4. 提取 Mermaid 代码块，按 chart_id 匹配生成 `charts_inventory.json`
5. 统计字数（统一口径）和图表数，生成 `merge_stats.json`（含合并耗时）
6. 返回合并结果统计

**无需调度子智能体**，主控 Agent 直接通过 run_skill.py 调用即可。

### 步骤6：主控 Agent 调用 render_mermaid.py 渲染 PNG

**chart_mapping JSON 文件准备**：
- 主控 Agent 将步骤4返回的 chart_mapping 写入 `final_document_file/_chart_mapping.json`

**推荐调用方式**（使用 --stats-output 规避 PowerShell 重定向问题）：

```bash
python .trae/scripts/render_mermaid.py \
    --input final_document_file/merged_proposal_raw.md \
    --output final_document_file/merged_proposal.md \
    --images-dir final_document_file/images/ \
    --chart-mapping final_document_file/_chart_mapping.json \
    --stats-output final_document_file/_render_stats.json
```

**PowerShell 环境注意**：
- 推荐使用 `--stats-output` 参数直接写统计文件，避免 stdout 重定向受脚本执行策略限制
- 如不使用 `--stats-output`，需用 Python subprocess 捕获 stdout

**异常处理**：
- mermaid-cli 未安装：自动触发占位图降级，不阻断流程
- Puppeteer Chromium 无法启动（Windows 常见）：自动检测系统 Chrome/Edge 并通过 puppeteer 配置文件指定，规避 Chromium 依赖问题
- 部分图表渲染失败：不阻断流程，继续处理其他图表

**mermaid-cli 安装（国内环境）**：
```bash
# 设置淘宝镜像源加速
npm config set registry https://registry.npmmirror.com
# 设置 Puppeteer Chromium 下载镜像
set PUPPETEER_DOWNLOAD_BASE_URL=https://registry.npmmirror.com/-/binary/chrome-for-testing
# 全局安装
npm install -g @mermaid-js/mermaid-cli
```
**注意**：Windows 下 Puppeteer 下载的 Chromium 可能因缺依赖无法启动（错误码 3221225595），render_mermaid.py 会自动检测系统已安装的 Chrome/Edge 并通过 `-p` 参数指定，无需额外配置。

### 步骤7：主控 Agent 调用 md_to_docx.py 转换 Word

```bash
python .trae/scripts/md_to_docx.py \
    --input final_document_file/merged_proposal.md \
    --output final_document_file/<日期>_<项目名称>_技术方案.docx \
    --project-name <项目名称> \
    --images-dir final_document_file/images/
```

**日期格式**：`yyyy-MM-dd`（从系统时间获取）
**特殊字符处理**：项目名称中的 `/ \ : * ? " < > |` 需替换为下划线

### 步骤8：生成合并导出报告

调用 `generate_merge_report(workspace_path, export_stats)` 生成 `merge_report.md`。

**export_stats 参数（可选）**：
- 如提供：使用传入的统计信息
- 如不提供：自动从 `merge_stats.json` 和 `_render_stats.json` 汇总
- 自动扫描 `final_document_file/` 目录获取实际文件大小
- 报告生成后自动回填 merge_report.md 自身大小

### 步骤9：更新项目状态

调用 `update_metadata_status(workspace_path, "合并导出完成")` 更新项目状态。

### 步骤10：通知用户导出完成

主控 Agent 向用户通知导出完成，提供 Word 文档路径、报告路径、文档统计、异常提示。

***

## API Reference

### check_export_prerequisites

**功能**：校验导出前置条件（含环境依赖检测）

**参数**：`workspace_path`: str

**返回**：`{'success': bool, 'result': {..., 'warnings': list, 'dependencies': dict, 'errors': list}}`

### get_merge_order

**功能**：深度优先遍历 outline.json，返回合并顺序列表

**参数**：`workspace_path`: str

**返回**：`{'success': bool, 'result': {'merge_order': [...], 'total_nodes': int, 'content_nodes': int, 'directory_nodes': int}}`

### generate_chart_mapping

**功能**：生成 chart_id 到图题编号和 PNG 路径的映射表

**参数**：`workspace_path`: str

**返回**：`{'success': bool, 'result': {'chart_mapping': {...}, 'total_charts': int, 'chart_types': dict}}`

### merge_proposal

**功能**：主控 Agent 直接执行合并（替代原 merge-agent 子智能体）

**参数**：`workspace_path`: str

**返回**：
```python
{
    'success': bool,
    'result': {
        'total_nodes': int,
        'content_nodes': int,
        'directory_nodes': int,
        'total_words': int,
        'chapter_stats': [{'node_id': str, 'title': str, 'level': int, 'words': int, 'charts': int}],
        'chart_inventory': {'total_charts': int, 'matched': int, 'unmatched': int},
        'errors': list,
        'duration': str,    # 合并耗时，如 "0.5 秒"
        'output_files': {
            'merged_raw': {'path': str, 'size': str},
            'charts_inventory': {'path': str},
            'merge_stats': {'path': str}
        }
    }
}
```

### generate_merge_report

**功能**：生成合并导出报告 merge_report.md（export_stats 可选，缺失时自动汇总）

**参数**：`workspace_path`: str, `export_stats`: dict（可选）

**返回**：`{'success': bool, 'report_path': str, 'stats': dict}`

### update_metadata_status

**功能**：更新 metadata.json 项目状态为「合并导出完成」

**参数**：`workspace_path`: str, `status`: str（默认"合并导出完成"）, `export_file_path`: str（可选）

**返回**：`{'success': bool, 'status': str, 'updated_fields': list, 'export_file_path': str}`

### get_export_status

**功能**：获取导出状态（用于中断恢复）

**参数**：`workspace_path`: str

**返回**：`{'success': bool, 'result': {..., 'resume_from': str}}`

### validate_export_output

**功能**：验证导出产出文件完整性

**参数**：`workspace_path`: str

**返回**：`{'success': bool, 'result': {merged_proposal, docx_file, merge_report, images}}`

***

## run_skill.py 调用方式

```bash
# 校验前置条件
python .trae/scripts/run_skill.py merge_export check_export_prerequisites --workspace_path "bid_project/20260802_120000_abc123"

# 获取合并顺序
python .trae/scripts/run_skill.py merge_export get_merge_order --workspace_path "bid_project/20260802_120000_abc123"

# 生成图表映射
python .trae/scripts/run_skill.py merge_export generate_chart_mapping --workspace_path "bid_project/20260802_120000_abc123"

# 主控直接执行合并（替代原 merge-agent）
python .trae/scripts/run_skill.py merge_export merge_proposal --workspace_path "bid_project/20260802_120000_abc123"

# 生成合并报告（export_stats 可选，缺失时自动汇总）
python .trae/scripts/run_skill.py merge_export generate_merge_report --workspace_path "bid_project/20260802_120000_abc123"

# 更新项目状态
python .trae/scripts/run_skill.py merge_export update_metadata_status --workspace_path "bid_project/20260802_120000_abc123" --status "合并导出完成"

# 获取导出状态
python .trae/scripts/run_skill.py merge_export get_export_status --workspace_path "bid_project/20260802_120000_abc123"

# 验证导出产出
python .trae/scripts/run_skill.py merge_export validate_export_output --workspace_path "bid_project/20260802_120000_abc123"
```

**返回格式**：JSON 格式 `{"success": true, "result": {...}}`

***

## Error Handling

| 错误类型 | 处理方式 |
|----------|----------|
| metadata.json 不存在 | 提示用户先执行阶段一至七 |
| 项目状态非「审查优化全部完成」 | 提示当前状态，引导用户从正确阶段继续 |
| proposal_files_locked 非 true | 提示用户需先完成阶段七人工审查并通过 |
| outline.json 不存在或解析失败 | 提示用户检查大纲文件 |
| 正文 .md 文件缺失 | merge_proposal 记录缺失并插入占位文字，不阻断 |
| 图表渲染失败 | 三级降级方案（保留代码块→占位图→文字描述），不阻断导出 |
| Word 转换失败 | 记录错误信息，提示用户检查依赖库和脚本 |
| 必需依赖缺失 | check_export_prerequisites 阻断流程，提示安装 |
| 可选依赖缺失 | check_export_prerequisites 返回 warning，启用降级 |

## Limitations

- 阶段八全部由主控 Agent 直接完成，不调度子智能体
- Mermaid 渲染依赖 `mermaid-cli`（Node.js 环境），缺失时降级为占位图
- Word 转换依赖 `python-docx` 和 `Pillow`，需提前安装
- 图表渲染失败时采用三级降级方案，不阻断导出流程
- 本阶段不修改正文 .md 文件（已锁定），仅在 `final_document_file/` 目录下生成新文件
- 中断恢复机制通过 metadata.json 的项目状态和 final_document_file 目录文件存在性支持
