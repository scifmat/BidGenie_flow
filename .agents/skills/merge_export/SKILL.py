#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - 合并导出 Skill 执行脚本（阶段八）

功能：
1. 校验导出前置条件（check_export_prerequisites）
2. 获取深度优先合并顺序（get_merge_order）
3. 生成图表映射表（generate_chart_mapping）
4. 生成合并导出报告（generate_merge_report）
5. 更新项目状态（update_metadata_status）
6. 获取导出状态，支持中断恢复（get_export_status）
7. 验证导出产出文件（validate_export_output）

注意：
- 合并执行（Mermaid 渲染、Word 转换）由 merge-agent 配合脚本完成，本脚本无智能逻辑
- 本脚本仅提供前置校验、合并顺序计算、图表映射、报告生成、状态管理
- 路径注入参考 content_optimization/SKILL.py 的模式
"""

import os
import sys
import json
import re
import glob
from datetime import datetime


# ==========================================================
# 路径注入：解决 .agents / .trae 目录导入问题
# ==========================================================
# 将 .trae 目录注入 sys.path，以便导入 utils.temp_manager
_TRAE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.trae'))
if _TRAE_PATH not in sys.path:
    sys.path.insert(0, _TRAE_PATH)


# ==========================================================
# 常量定义
# ==========================================================

# 项目状态值
PROJECT_STATUS_EXPORT_COMPLETED = "合并导出完成"
PROJECT_STATUS_OPTIMIZATION_COMPLETED = "审查优化全部完成"

# final_document_file 子目录
FINAL_DOCUMENT_DIR = "final_document_file"
IMAGES_SUBDIR = "images"

# Word 文件命名格式
DOCX_NAME_FORMAT = "{date}_{project_name}_技术方案.docx"

# metadata.json 中需要更新的字段
FIELD_PROJECT_STATUS = "项目状态"
FIELD_STATUS_UPDATE_TIME = "状态更新时间"
FIELD_EXPORT_COMPLETED_AT = "export_completed_at"
FIELD_EXPORT_FILE_PATH = "export_file_path"
FIELD_PROPOSAL_FILES_LOCKED = "proposal_files_locked"

# 正文 .md 文件命名规则：<node_id>_<title>.md
# 父目录命名规则：<parent_node_id>_<parent_title>/


class MergeExportSkill:
    """
    合并导出 Skill 执行类

    为主控 Agent 提供前置条件校验、合并顺序计算、图表映射生成、
    报告生成、状态更新、导出状态查询、产出验证等能力。

    合并执行由 merge-agent 完成，本脚本不负责智能逻辑。
    """

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))

    # ==========================================================
    # 辅助方法
    # ==========================================================

    def _read_metadata(self, workspace_path: str) -> dict:
        """读取 metadata.json，返回字典；失败返回空字典"""
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        if not os.path.exists(metadata_path):
            return {}
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_metadata(self, workspace_path: str, metadata: dict) -> bool:
        """保存 metadata.json"""
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _read_outline(self, workspace_path: str) -> dict:
        """读取 outline.json，返回字典；失败返回空字典"""
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {}
        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _get_project_name(self, metadata: dict, workspace_path: str) -> str:
        """获取项目名称（用于 Word 文件命名）"""
        project_name = metadata.get('项目名称', '')
        if not project_name:
            # 回退到工作空间目录名
            project_name = os.path.basename(os.path.normpath(workspace_path))
        return project_name

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename

    def _find_md_file(self, workspace_path: str, node_id: str, title: str) -> str:
        """
        根据 node_id 在 proposal_file/ 目录下查找对应的 .md 文件

        查找策略：
        1. 递归搜索 proposal_file/ 目录下所有 .md 文件
        2. 优先匹配文件名前缀为 <node_id>_ 的文件
        3. 返回相对路径（相对 workspace_path）

        Returns:
            str: 文件相对路径，找不到返回空字符串
        """
        proposal_dir = os.path.join(workspace_path, 'proposal_file')
        if not os.path.isdir(proposal_dir):
            return ''

        # 文件名前缀：<node_id>_
        prefix = f"{node_id}_"

        for root, dirs, files in os.walk(proposal_dir):
            for file in files:
                if file.endswith('.md') and file.startswith(prefix):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, workspace_path)
                    # 转换为正向斜杠，便于跨平台使用
                    rel_path = rel_path.replace('\\', '/')
                    return rel_path

        return ''

    def _collect_content_nodes(self, outline: dict) -> list:
        """
        递归收集 outline 中所有 write_content=true 的节点

        Returns:
            list: 节点列表，每个节点为 dict（含 node_id, title, level, charts 等）
        """
        result = []

        def _walk(node):
            if not isinstance(node, dict):
                return
            if node.get('write_content', False):
                result.append(node)
            children = node.get('children', [])
            if isinstance(children, list):
                for child in children:
                    _walk(child)

        _walk(outline)
        return result

    def _node_id_to_figure_path(self, node_id: str) -> str:
        """
        node_id 路径转换为图题路径
        例：1_1_4 → 1-1-4
        """
        return node_id.replace('_', '-')

    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小为人类可读字符串"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _get_file_size_str(self, file_path: str) -> str:
        """获取文件大小字符串，文件不存在返回 '不存在'"""
        if not os.path.exists(file_path):
            return "不存在"
        try:
            size = os.path.getsize(file_path)
            return self._format_file_size(size)
        except Exception:
            return "未知"

    def _count_words(self, md_text: str) -> int:
        """
        统一字数统计口径（与 merge-agent、export_rules.md 第九章一致）

        统计规则：
        - 计入：正文段落文字、表格内容、列表内容、引用内容、行内代码字面字符
        - 不计入：标题行（# 开头）、Mermaid 代码块（```mermaid 到 ```）、
                  图题行（*图 X-Y-Z-N 开头）、表题行（*表 X-Y-Z-N 开头）、
                  图片引用行（![ 开头）、代码围栏行（```）、空行

        Args:
            md_text: Markdown 文本

        Returns:
            int: 字数（不含空格和换行）
        """
        if not md_text:
            return 0

        lines = md_text.split('\n')
        result_lines = []
        in_mermaid_block = False
        in_code_block = False

        for line in lines:
            stripped = line.strip()

            # 检测代码块开始/结束
            if stripped.startswith('```'):
                if stripped.startswith('```mermaid'):
                    in_mermaid_block = True
                    continue
                elif in_mermaid_block:
                    # Mermaid 块结束
                    in_mermaid_block = False
                    continue
                else:
                    # 普通代码块切换
                    in_code_block = not in_code_block
                    continue

            # 在 Mermaid 块内：跳过
            if in_mermaid_block:
                continue

            # 在普通代码块内：计入（代码也是内容）
            if in_code_block:
                result_lines.append(stripped)
                continue

            # 跳过标题行
            if stripped.startswith('#'):
                continue

            # 跳过图题行（*图 X-Y-Z-N 标题*）
            if stripped.startswith('*图 ') or stripped.startswith('图 '):
                continue

            # 跳过表题行（*表 X-Y-Z-N 标题*）
            if stripped.startswith('*表 ') or stripped.startswith('表 '):
                continue

            # 跳过图片引用行
            if stripped.startswith('!['):
                continue

            # 跳过表格分隔行（仅含 |、-、: 字符）
            if stripped.startswith('|') and all(c in '|-: ' for c in stripped):
                continue

            # 跳过空行
            if not stripped:
                continue

            result_lines.append(stripped)

        # 拼接所有有效行，移除空格和换行后统计字符数
        combined = ''.join(result_lines)
        # 移除空白字符
        combined = re.sub(r'\s+', '', combined)
        return len(combined)

    # ==========================================================
    # 1. check_export_prerequisites：校验导出前置条件
    # ==========================================================

    def check_export_prerequisites(self, workspace_path: str) -> dict:
        """
        校验导出前置条件

        校验内容：
        1. metadata.json 存在且 proposal_files_locked 为 true
        2. proposal_file/outline.json 存在且为有效 JSON
        3. outline.json 中所有 write_content: true 的节点有对应的 .md 文件
        4. final_document_file/ 目录可创建（如不存在则创建）
        5. final_document_file/images/ 目录可创建
        6. 环境依赖可用性检测（python-docx、Pillow 必需；mermaid-cli 可选）

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 校验结果，含 warnings 字段提示依赖缺失（不阻断流程）
        """
        errors = []
        warnings = []
        missing_files = []
        outline_valid = False
        md_files_count = 0

        # 校验工作空间存在
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {
                    'workspace_path': workspace_path,
                    'outline_valid': False,
                    'md_files_count': 0,
                    'final_document_dir': '',
                    'images_dir': '',
                    'missing_files': [],
                    'warnings': [],
                    'errors': [f'工作空间不存在: {workspace_path}']
                }
            }

        # 1. 校验 metadata.json 和 proposal_files_locked
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            errors.append('metadata.json 不存在或解析失败')
        else:
            locked = metadata.get(FIELD_PROPOSAL_FILES_LOCKED, False)
            if not locked:
                errors.append('proposal_files_locked 非 true，需先完成阶段七人工审查并通过')

        # 2. 校验 outline.json
        outline = self._read_outline(workspace_path)
        if not outline:
            errors.append('proposal_file/outline.json 不存在或解析失败')
        else:
            outline_valid = True
            # 3. 校验所有 write_content=true 节点有对应 .md 文件
            content_nodes = self._collect_content_nodes(outline)
            for node in content_nodes:
                node_id = node.get('node_id', '')
                title = node.get('title', '')
                md_file = self._find_md_file(workspace_path, node_id, title)
                if not md_file:
                    missing_files.append(f"proposal_file/.../{node_id}_{title}.md")
                else:
                    # 校验文件存在且非空
                    abs_path = os.path.join(workspace_path, md_file)
                    if not os.path.exists(abs_path) or os.path.getsize(abs_path) == 0:
                        missing_files.append(f"{md_file} (文件不存在或为空)")
                    else:
                        md_files_count += 1

        # 4. 创建 final_document_file/ 和 images/ 目录
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
        images_dir = os.path.join(final_doc_dir, IMAGES_SUBDIR)
        try:
            os.makedirs(final_doc_dir, exist_ok=True)
            os.makedirs(images_dir, exist_ok=True)
        except Exception as e:
            errors.append(f'创建目录失败: {str(e)}')

        # 5. 环境依赖检测（不阻断流程，仅提示）
        deps = self._check_environment_dependencies()
        for dep_name, dep_info in deps.items():
            if not dep_info['available']:
                if dep_info['required']:
                    # 必需依赖缺失：记为 error（阻断流程）
                    errors.append(f"必需依赖缺失: {dep_name}（{dep_info['install_hint']}）")
                else:
                    # 可选依赖缺失：记为 warning（不阻断，启用降级）
                    warnings.append(f"可选依赖缺失: {dep_name}（{dep_info['install_hint']}，将启用降级方案）")

        success = (len(errors) == 0 and len(missing_files) == 0 and outline_valid)

        return {
            'success': success,
            'result': {
                'workspace_path': workspace_path,
                'outline_valid': outline_valid,
                'md_files_count': md_files_count,
                'final_document_dir': FINAL_DOCUMENT_DIR,
                'images_dir': f"{FINAL_DOCUMENT_DIR}/{IMAGES_SUBDIR}",
                'missing_files': missing_files,
                'warnings': warnings,
                'dependencies': deps,
                'errors': errors
            }
        }

    def _check_environment_dependencies(self) -> dict:
        """
        检测环境依赖可用性

        Returns:
            dict: 依赖检测结果，{dep_name: {available, required, install_hint, version}}
        """
        deps = {}

        # python-docx（必需，用于 md_to_docx.py）
        try:
            import docx
            version = getattr(docx, '__version__', 'unknown')
            deps['python-docx'] = {
                'available': True, 'required': True,
                'version': version, 'install_hint': 'pip install python-docx'
            }
        except ImportError:
            deps['python-docx'] = {
                'available': False, 'required': True,
                'version': None, 'install_hint': 'pip install python-docx'
            }

        # Pillow（必需，用于占位图生成）
        try:
            from PIL import Image, ImageDraw, ImageFont
            import PIL
            deps['Pillow'] = {
                'available': True, 'required': True,
                'version': PIL.__version__, 'install_hint': 'pip install Pillow'
            }
        except ImportError:
            deps['Pillow'] = {
                'available': False, 'required': True,
                'version': None, 'install_hint': 'pip install Pillow'
            }

        # mermaid-cli / mmdc（可选，缺失时启用占位图降级）
        import shutil
        mmdc_path = shutil.which('mmdc')
        if mmdc_path:
            deps['mermaid-cli'] = {
                'available': True, 'required': False,
                'version': mmdc_path, 'install_hint': '已安装'
            }
        else:
            deps['mermaid-cli'] = {
                'available': False, 'required': False,
                'version': None, 'install_hint': 'npm install -g @mermaid-js/mermaid-cli'
            }

        # python-markdown（可选，当前脚本使用正则解析，未来扩展可能使用）
        try:
            import markdown
            deps['python-markdown'] = {
                'available': True, 'required': False,
                'version': markdown.__version__, 'install_hint': 'pip install markdown'
            }
        except (ImportError, AttributeError):
            deps['python-markdown'] = {
                'available': False, 'required': False,
                'version': None, 'install_hint': 'pip install markdown（可选，当前脚本使用正则解析）'
            }

        return deps

    # ==========================================================
    # 2. get_merge_order：获取深度优先合并顺序
    # ==========================================================

    def get_merge_order(self, workspace_path: str) -> dict:
        """
        深度优先遍历 outline.json，返回合并顺序列表

        遍历算法：
        1. 从根节点（level=1）开始
        2. 对每个节点，输出其标题行（如 "## 标题"，level 对应 # 数量）
        3. 若 write_content: true：记录对应的 .md 文件路径
        4. 若 write_content: false：递归处理其 children 数组
        5. 返回有序的节点列表

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 合并顺序列表
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}'}
            }

        outline = self._read_outline(workspace_path)
        if not outline:
            return {
                'success': False,
                'result': {'error': 'outline.json 不存在或解析失败'}
            }

        merge_order = []
        stats = {'total_nodes': 0, 'content_nodes': 0, 'directory_nodes': 0}

        def _dfs_traverse(node):
            if not isinstance(node, dict):
                return

            node_id = node.get('node_id', '')
            title = node.get('title', '')
            level = node.get('level', 1)
            write_content = node.get('write_content', False)

            # 构造标题行
            heading_prefix = '#' * level
            heading_line = f"{heading_prefix} {title}"

            # 查找对应的 .md 文件
            md_file = None
            charts = []
            if write_content:
                md_file = self._find_md_file(workspace_path, node_id, title)
                charts = node.get('charts', []) or []

            merge_order.append({
                'node_id': node_id,
                'title': title,
                'level': level,
                'write_content': write_content,
                'heading_line': heading_line,
                'md_file': md_file,
                'charts': charts
            })

            stats['total_nodes'] += 1
            if write_content:
                stats['content_nodes'] += 1
            else:
                stats['directory_nodes'] += 1

            # 递归处理子节点
            if not write_content:
                children = node.get('children', [])
                if isinstance(children, list):
                    for child in children:
                        _dfs_traverse(child)

        _dfs_traverse(outline)

        return {
            'success': True,
            'result': {
                'merge_order': merge_order,
                'total_nodes': stats['total_nodes'],
                'content_nodes': stats['content_nodes'],
                'directory_nodes': stats['directory_nodes']
            }
        }

    # ==========================================================
    # 3. generate_chart_mapping：生成图表映射表
    # ==========================================================

    def generate_chart_mapping(self, workspace_path: str) -> dict:
        """
        生成 chart_id 到图题编号和 PNG 路径的映射表

        映射逻辑：
        1. 遍历 outline.json，收集所有 generate_chart: true 的节点
        2. 对每个节点的 charts 数组，按顺序生成图题编号
        3. node_id 路径转换：1_1_4 → 1-1-4（下划线替换为连字符）
        4. 图表序号：该节点内第 N 个图表（从 1 开始）
        5. 组合编号：1-1-4-1
        6. PNG 文件名：<chart_id>.png

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 图表映射表
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}'}
            }

        outline = self._read_outline(workspace_path)
        if not outline:
            return {
                'success': False,
                'result': {'error': 'outline.json 不存在或解析失败'}
            }

        chart_mapping = {}
        chart_types = {}

        def _collect_charts(node):
            if not isinstance(node, dict):
                return

            # 仅处理 generate_chart=true 且有 charts 数组的节点
            if node.get('generate_chart', False) or node.get('charts'):
                node_id = node.get('node_id', '')
                charts = node.get('charts', []) or []
                if charts:
                    figure_path = self._node_id_to_figure_path(node_id)
                    for idx, chart in enumerate(charts, start=1):
                        if not isinstance(chart, dict):
                            continue
                        chart_id = chart.get('chart_id', f"{node_id}_c{idx}")
                        chart_title = chart.get('chart_title', '')
                        chart_type = chart.get('chart_type', 'flowchart')
                        figure_number = f"{figure_path}-{idx}"
                        png_filename = f"{chart_id}.png"
                        png_path = f"{FINAL_DOCUMENT_DIR}/{IMAGES_SUBDIR}/{png_filename}"

                        chart_mapping[chart_id] = {
                            'figure_number': figure_number,
                            'chart_title': chart_title,
                            'chart_type': chart_type,
                            'png_filename': png_filename,
                            'png_path': png_path,
                            'node_id': node_id
                        }

                        # 类型统计
                        chart_types[chart_type] = chart_types.get(chart_type, 0) + 1

            # 递归处理子节点
            children = node.get('children', [])
            if isinstance(children, list):
                for child in children:
                    _collect_charts(child)

        _collect_charts(outline)

        return {
            'success': True,
            'result': {
                'chart_mapping': chart_mapping,
                'total_charts': len(chart_mapping),
                'chart_types': chart_types
            }
        }

    # ==========================================================
    # 3.5 merge_proposal：主控 Agent 直接合并正文（替代 merge-agent）
    # ==========================================================

    def merge_proposal(self, workspace_path: str) -> dict:
        """
        主控 Agent 直接执行合并：读取所有正文 .md 文件，按大纲深度优先顺序
        合并生成 merged_proposal_raw.md（保留原 Mermaid 代码块），提取图表
        清单生成 charts_inventory.json，统计字数生成 merge_stats.json。

        本函数替代原 merge-agent 子智能体的全部工作，由主控 Agent 直接调用。

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 合并结果，含 total_nodes/content_nodes/total_words/
                  chapter_stats/chart_inventory/errors/duration/output_files
        """
        if not os.path.isdir(workspace_path):
            return {'success': False, 'error': f'工作空间不存在: {workspace_path}'}

        start_time = datetime.now()

        # 1. 获取合并顺序与图表映射
        order_result = self.get_merge_order(workspace_path)
        if not order_result.get('success'):
            return {'success': False, 'error': '获取合并顺序失败: ' + str(order_result.get('result', {}).get('error', ''))}
        merge_order = order_result['result']['merge_order']

        chart_result = self.generate_chart_mapping(workspace_path)
        chart_mapping = chart_result['result']['chart_mapping'] if chart_result.get('success') else {}

        # 2. 按合并顺序读取并拼接所有章节
        merged_lines = []
        chapter_stats = []
        errors = []

        for node in merge_order:
            if node.get('write_content') and node.get('md_file'):
                # 内容节点：直接输出 .md 文件内容（文件内部已含标题行，避免重复）
                md_abs_path = os.path.join(workspace_path, node['md_file'])
                if os.path.exists(md_abs_path):
                    try:
                        with open(md_abs_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except Exception as e:
                        content = f'[文件读取失败: {node["node_id"]} - {str(e)}]'
                        errors.append({
                            'node_id': node['node_id'],
                            'error': f'文件读取失败: {str(e)}',
                            'handling': '插入占位文字'
                        })
                    merged_lines.append(content)
                    words = self._count_words(content)
                    chapter_stats.append({
                        'node_id': node['node_id'],
                        'title': node['title'],
                        'level': node.get('level', 3),
                        'words': words,
                        'charts': len(node.get('charts', []))
                    })
                else:
                    placeholder = f'[文件缺失: {node["node_id"]}_{node["title"]}.md]'
                    merged_lines.append(placeholder)
                    errors.append({
                        'node_id': node['node_id'],
                        'error': '文件缺失',
                        'handling': '插入占位文字'
                    })
                    chapter_stats.append({
                        'node_id': node['node_id'],
                        'title': node['title'],
                        'level': node.get('level', 3),
                        'words': 0,
                        'charts': len(node.get('charts', []))
                    })
            else:
                # 目录节点：输出标题行
                merged_lines.append(node.get('heading_line', ''))
            merged_lines.append('')

        merged_content = '\n'.join(merged_lines)

        # 3. 写入 merged_proposal_raw.md（保留原 Mermaid 代码块）
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
        os.makedirs(final_doc_dir, exist_ok=True)
        raw_path = os.path.join(final_doc_dir, 'merged_proposal_raw.md')
        try:
            with open(raw_path, 'w', encoding='utf-8') as f:
                f.write(merged_content)
        except Exception as e:
            return {'success': False, 'error': f'写入 merged_proposal_raw.md 失败: {str(e)}'}

        # 4. 提取 Mermaid 代码块，生成 charts_inventory.json
        charts_inventory = self._extract_mermaid_blocks(merged_content, chart_mapping)
        inventory_path = os.path.join(final_doc_dir, 'charts_inventory.json')
        try:
            with open(inventory_path, 'w', encoding='utf-8') as f:
                json.dump(charts_inventory, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 不阻断主流程

        # 5. 统计并生成 merge_stats.json（含耗时）
        end_time = datetime.now()
        duration_sec = (end_time - start_time).total_seconds()
        # 耗时精度：< 1 秒显示毫秒，>= 1 秒显示秒
        if duration_sec < 1:
            duration_str = f'{int(duration_sec * 1000)} 毫秒'
        else:
            duration_str = f'{duration_sec:.1f} 秒'
        total_words = sum(c['words'] for c in chapter_stats)

        merge_stats = {
            'total_nodes': order_result['result']['total_nodes'],
            'content_nodes': order_result['result']['content_nodes'],
            'directory_nodes': order_result['result']['directory_nodes'],
            'total_words': total_words,
            'chapter_stats': chapter_stats,
            'chart_inventory': {
                'total_charts': charts_inventory['total_charts'],
                'matched': charts_inventory['matched'],
                'unmatched': charts_inventory['unmatched']
            },
            'errors': errors,
            'duration': duration_str,
            'output_files': {
                'merged_raw': {
                    'path': f'{FINAL_DOCUMENT_DIR}/merged_proposal_raw.md',
                    'size': self._get_file_size_str(raw_path)
                },
                'charts_inventory': {'path': f'{FINAL_DOCUMENT_DIR}/charts_inventory.json'},
                'merge_stats': {'path': f'{FINAL_DOCUMENT_DIR}/merge_stats.json'}
            }
        }

        stats_path = os.path.join(final_doc_dir, 'merge_stats.json')
        try:
            with open(stats_path, 'w', encoding='utf-8') as f:
                json.dump(merge_stats, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 不阻断主流程

        return {'success': True, 'result': merge_stats}

    def _extract_mermaid_blocks(self, merged_content: str, chart_mapping: dict) -> dict:
        """
        从合并后的 Markdown 内容中提取 Mermaid 代码块，按图题编号反查
        chart_mapping 匹配 chart_id，生成图表清单。

        Args:
            merged_content: 合并后的完整 Markdown 文本
            chart_mapping: chart_id → 图表信息映射表

        Returns:
            dict: 图表清单，含 total_charts/matched/unmatched/charts 数组
        """
        lines = merged_content.split('\n')
        charts = []

        # 构建 figure_number -> chart_id 反查表
        fig_to_chart = {}
        title_to_chart = {}
        for cid, info in chart_mapping.items():
            fig_num = info.get('figure_number', '')
            if fig_num:
                fig_to_chart[fig_num] = cid
            title = info.get('chart_title', '')
            if title:
                title_to_chart[title] = cid

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('```mermaid'):
                block_start = i
                # 找代码块结束（下一个 ``` 行）
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith('```'):
                    j += 1
                block_end = j  # ``` 结束行

                # 找紧随的图题行（跳过空行）
                k = block_end + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1

                figure_number = ''
                chart_title = ''
                if k < len(lines):
                    fig_line = lines[k].strip()
                    # 匹配 *图 X-Y-Z-N 标题* 或 图 X-Y-Z-N 标题
                    m = re.match(r'^\*?图\s+([\d-]+)\s+(.+?)\*?$', fig_line)
                    if m:
                        figure_number = m.group(1)
                        chart_title = m.group(2)

                # 反查 chart_id：优先按图题编号，其次按标题
                chart_id = fig_to_chart.get(figure_number, '')
                if not chart_id and chart_title:
                    chart_id = title_to_chart.get(chart_title, '')
                matched = bool(chart_id)

                chart_type = ''
                node_id = ''
                if chart_id and chart_id in chart_mapping:
                    chart_type = chart_mapping[chart_id].get('chart_type', '')
                    node_id = chart_mapping[chart_id].get('node_id', '')

                charts.append({
                    'chart_id': chart_id,
                    'title': chart_title,
                    'type': chart_type,
                    'figure_number': figure_number,
                    'node_id': node_id,
                    'matched': matched,
                    'line_start': block_start + 1,
                    'line_end': block_end + 1
                })
                i = block_end + 1
            else:
                i += 1

        matched_count = sum(1 for c in charts if c['matched'])
        return {
            'total_charts': len(charts),
            'matched': matched_count,
            'unmatched': len(charts) - matched_count,
            'charts': charts
        }

    # ==========================================================
    # 4. generate_merge_report：生成合并导出报告
    # ==========================================================

    def generate_merge_report(self, workspace_path: str, export_stats: dict = None) -> dict:
        """
        生成合并导出报告 merge_report.md

        参数化策略：
        - 如提供 export_stats：使用传入的统计信息
        - 如 export_stats 为 None 或空字典：自动从以下来源汇总：
          a) final_document_file/merge_stats.json（merge-agent 生成的合并统计）
          b) final_document_file/_render_stats.json（render_mermaid.py 输出的渲染统计，如存在）
          c) 扫描 final_document_file/ 目录获取实际文件大小
        - 报告生成后自动回填 merge_report.md 自身大小

        Args:
            workspace_path: 工作空间路径
            export_stats: 导出统计信息（可选，由 merge-agent 返回），包含：
                - total_nodes: 合并的节点总数
                - content_nodes: 内容节点数
                - total_words: 总字数
                - chapter_stats: 各章节字数统计列表
                - chart_stats: 图表渲染统计列表
                - errors: 异常记录列表
                - output_files: 输出文件路径和大小

        Returns:
            dict: 报告生成结果
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'report_path': '',
                'error': f'工作空间不存在: {workspace_path}'
            }

        if not isinstance(export_stats, dict):
            export_stats = {}

        # 创建 final_document_file 目录（如不存在）
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
        os.makedirs(final_doc_dir, exist_ok=True)

        # 读取项目元数据
        metadata = self._read_metadata(workspace_path)
        project_name = self._get_project_name(metadata, workspace_path)

        # 报告生成时间
        now = datetime.now()
        export_time = now.strftime('%Y-%m-%d %H:%M:%S')

        # 自动汇总统计信息（如 export_stats 不完整）
        export_stats = self._auto_collect_stats(workspace_path, export_stats)

        # 统计信息（提供默认值）
        total_nodes = export_stats.get('total_nodes', 0)
        content_nodes = export_stats.get('content_nodes', 0)
        total_words = export_stats.get('total_words', 0)
        chapter_stats = export_stats.get('chapter_stats', []) or []
        chart_stats = export_stats.get('chart_stats', []) or []
        errors = export_stats.get('errors', []) or []
        output_files = export_stats.get('output_files', {}) or {}

        # 图表统计
        total_charts = len(chart_stats)
        success_charts = sum(1 for c in chart_stats if c.get('render_result') == 'success')
        fallback_charts = sum(1 for c in chart_stats
                              if c.get('render_result') in ('fallback', 'placeholder'))
        failed_charts = sum(1 for c in chart_stats if c.get('render_result') == 'failed')

        # 构建报告内容
        report_lines = []
        report_lines.append("# 合并导出报告")
        report_lines.append("")
        report_lines.append("## 一、导出概览")
        report_lines.append("")
        report_lines.append(f"- 导出时间：{export_time}")
        report_lines.append(f"- 项目名称：{project_name}")
        report_lines.append(f"- 合并章节数：{content_nodes} 个内容节点（共 {total_nodes} 个大纲节点）")
        report_lines.append(f"- 文档总字数：约 {total_words} 字")
        report_lines.append(
            f"- 图表渲染：成功 {success_charts} 个 / 降级 {fallback_charts} 个 / 失败 {failed_charts} 个（共 {total_charts} 个）"
        )
        report_lines.append("")

        # 二、各章节字数统计
        report_lines.append("## 二、各章节字数统计")
        report_lines.append("")
        if chapter_stats:
            report_lines.append("| 节点ID | 节点标题 | 层级 | 字数 | 图表数 |")
            report_lines.append("|--------|----------|------|------|--------|")
            for ch in chapter_stats:
                node_id = ch.get('node_id', '')
                title = ch.get('title', '')
                level = ch.get('level', '')
                words = ch.get('words', 0)
                charts = ch.get('charts', 0)
                report_lines.append(f"| {node_id} | {title} | {level} | {words} | {charts} |")
        else:
            report_lines.append("（暂无章节字数统计信息）")
        report_lines.append("")

        # 三、图表渲染统计
        report_lines.append("## 三、图表渲染统计")
        report_lines.append("")
        if chart_stats:
            report_lines.append("| 图表ID | 图表标题 | 类型 | 图题编号 | 渲染结果 | 处理方式 |")
            report_lines.append("|--------|----------|------|----------|----------|----------|")
            for cs in chart_stats:
                cid = cs.get('chart_id', '')
                title = cs.get('title', '')
                ctype = cs.get('type', '')
                fig_num = cs.get('figure_number', '')
                render_result = cs.get('render_result', '')
                handling = cs.get('handling', '')
                report_lines.append(f"| {cid} | {title} | {ctype} | 图 {fig_num} | {render_result} | {handling} |")
        else:
            report_lines.append("（暂无图表渲染统计信息）")
        report_lines.append("")

        # 四、异常记录
        report_lines.append("## 四、异常记录")
        report_lines.append("")
        if errors:
            report_lines.append("| 序号 | 异常类型 | 详细描述 | 处理方式 |")
            report_lines.append("|------|----------|----------|----------|")
            for idx, err in enumerate(errors, start=1):
                if isinstance(err, dict):
                    err_type = err.get('type', '') or err.get('chart_id', '')
                    err_desc = err.get('error', '') or err.get('description', '')
                    handling = err.get('handling', '') or f"降级层级 {err.get('fallback_level', '')}"
                else:
                    err_type = '未知'
                    err_desc = str(err)
                    handling = '记录'
                report_lines.append(f"| {idx} | {err_type} | {err_desc} | {handling} |")
        else:
            report_lines.append("（无异常记录）")
        report_lines.append("")

        # 五、生成文件（自动扫描实际文件大小）
        report_lines.append("## 五、生成文件")
        report_lines.append("")
        report_lines.append("| 文件 | 路径 | 大小 |")
        report_lines.append("|------|------|------|")

        file_infos = self._scan_final_document_files(workspace_path)
        for fi in file_infos:
            report_lines.append(f"| {fi['name']} | {fi['path']} | {fi['size']} |")
        report_lines.append("")

        # 六、导出状态
        report_lines.append("## 六、导出状态")
        report_lines.append("")
        report_lines.append(f"- 项目状态：{PROJECT_STATUS_EXPORT_COMPLETED}")
        report_lines.append(f"- 导出耗时：{export_stats.get('duration', '未知')}")
        if fallback_charts > 0 or failed_charts > 0:
            report_lines.append("- 建议人工检查项：存在降级处理或渲染失败的图表，建议人工替换对应图片")
        else:
            report_lines.append("- 建议人工检查项：无")
        report_lines.append("")

        # 写入文件
        report_content = '\n'.join(report_lines)
        report_path = os.path.join(final_doc_dir, 'merge_report.md')
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
        except Exception as e:
            return {
                'success': False,
                'report_path': '',
                'error': f'写入报告失败: {str(e)}'
            }

        # 回填 merge_report.md 自身大小（二次写入）
        report_size = self._get_file_size_str(report_path)
        report_content = report_content.replace(
            f"| merge_report.md | {FINAL_DOCUMENT_DIR}/merge_report.md | 生成中 |",
            f"| merge_report.md | {FINAL_DOCUMENT_DIR}/merge_report.md | {report_size} |"
        )
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
        except Exception:
            # 回填失败不影响主流程
            pass

        return {
            'success': True,
            'report_path': f"{FINAL_DOCUMENT_DIR}/merge_report.md",
            'stats': {
                'total_nodes': total_nodes,
                'content_nodes': content_nodes,
                'total_words': total_words,
                'total_charts': total_charts,
                'success_charts': success_charts,
                'fallback_charts': fallback_charts,
                'failed_charts': failed_charts
            }
        }

    def _auto_collect_stats(self, workspace_path: str, export_stats: dict) -> dict:
        """
        自动汇总统计信息

        如 export_stats 不完整，从以下来源补充：
        1. final_document_file/merge_stats.json（merge-agent 生成）
        2. final_document_file/_render_stats.json（render_mermaid.py 输出，如存在）

        Args:
            workspace_path: 工作空间路径
            export_stats: 已有的统计信息（优先级最高）

        Returns:
            dict: 合并后的完整统计信息
        """
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)

        # 1. 尝试读取 merge_stats.json
        merge_stats_path = os.path.join(final_doc_dir, 'merge_stats.json')
        merge_stats = {}
        if os.path.exists(merge_stats_path):
            try:
                with open(merge_stats_path, 'r', encoding='utf-8') as f:
                    merge_stats = json.load(f)
            except Exception:
                merge_stats = {}

        # 2. 尝试读取 _render_stats.json（render_mermaid.py 输出）
        render_stats_path = os.path.join(final_doc_dir, '_render_stats.json')
        render_stats = {}
        if os.path.exists(render_stats_path):
            try:
                with open(render_stats_path, 'r', encoding='utf-8') as f:
                    render_stats = json.load(f)
            except Exception:
                render_stats = {}

        # render_mermaid.py 输出结构为 {"success":true,"result":{...}}，提取 result 嵌套层
        render_stats_data = render_stats.get('result', render_stats) if isinstance(render_stats, dict) else {}

        # 3. 合并统计信息（export_stats 优先级最高）
        result = {}

        # 基本信息：优先 export_stats，其次 merge_stats
        result['total_nodes'] = (
            export_stats.get('total_nodes') or
            merge_stats.get('total_nodes') or 0
        )
        result['content_nodes'] = (
            export_stats.get('content_nodes') or
            merge_stats.get('content_nodes') or 0
        )
        result['total_words'] = (
            export_stats.get('total_words') or
            merge_stats.get('total_words') or 0
        )

        # chapter_stats：优先 export_stats，其次 merge_stats
        result['chapter_stats'] = (
            export_stats.get('chapter_stats') or
            merge_stats.get('chapter_stats') or []
        )

        # chart_stats：优先 export_stats，其次 render_stats（渲染统计），最后 merge_stats（图表清单）
        if export_stats.get('chart_stats'):
            result['chart_stats'] = export_stats['chart_stats']
        elif render_stats_data.get('chart_stats'):
            result['chart_stats'] = render_stats_data['chart_stats']
        elif merge_stats.get('chart_inventory', {}).get('charts'):
            # 从图表清单转换为 chart_stats 格式
            charts_inv = merge_stats['chart_inventory']
            result['chart_stats'] = [
                {
                    'chart_id': c.get('chart_id', ''),
                    'title': c.get('title', ''),
                    'type': c.get('type', ''),
                    'figure_number': c.get('figure_number', ''),
                    'render_result': 'pending' if c.get('matched') else 'unmatched',
                    'handling': ''
                }
                for c in charts_inv.get('charts', [])
            ]
        else:
            result['chart_stats'] = []

        # errors：合并所有来源的异常
        all_errors = []
        for src in [export_stats.get('errors'), merge_stats.get('errors'), render_stats_data.get('errors')]:
            if src and isinstance(src, list):
                all_errors.extend(src)
        result['errors'] = all_errors

        # output_files：优先 export_stats，其次自动扫描
        result['output_files'] = export_stats.get('output_files') or {}

        # duration：汇总合并和渲染耗时（分别标注）
        merge_duration = merge_stats.get('duration', '')
        render_duration = render_stats_data.get('duration', '')
        if export_stats.get('duration'):
            result['duration'] = export_stats['duration']
        elif merge_duration or render_duration:
            parts = []
            if merge_duration:
                parts.append(f'合并 {merge_duration}')
            if render_duration:
                parts.append(f'渲染 {render_duration}')
            result['duration'] = ' + '.join(parts)
        else:
            result['duration'] = '未知'

        return result

    def _scan_final_document_files(self, workspace_path: str) -> list:
        """
        扫描 final_document_file/ 目录，获取所有产出文件信息

        Args:
            workspace_path: 工作空间路径

        Returns:
            list: 文件信息列表，每个元素含 {name, path, size}
        """
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
        images_dir = os.path.join(final_doc_dir, IMAGES_SUBDIR)
        result = []

        # merged_proposal.md
        merged_path = os.path.join(final_doc_dir, 'merged_proposal.md')
        result.append({
            'name': 'merged_proposal.md',
            'path': f"{FINAL_DOCUMENT_DIR}/merged_proposal.md",
            'size': self._get_file_size_str(merged_path)
        })

        # Word 文档（按通配符查找 .docx 文件，排除临时文件）
        import glob as glob_module
        docx_files = glob_module.glob(os.path.join(final_doc_dir, '*.docx'))
        docx_files = [f for f in docx_files if not os.path.basename(f).startswith('~$')]
        if docx_files:
            # 取最新的 docx 文件
            docx_path = max(docx_files, key=os.path.getmtime)
            docx_name = os.path.basename(docx_path)
            result.append({
                'name': '技术方案.docx',
                'path': f"{FINAL_DOCUMENT_DIR}/{docx_name}",
                'size': self._get_file_size_str(docx_path)
            })
        else:
            result.append({
                'name': '技术方案.docx',
                'path': '未生成',
                'size': '未生成'
            })

        # merge_report.md（自身，先标记为"生成中"，后续回填）
        result.append({
            'name': 'merge_report.md',
            'path': f"{FINAL_DOCUMENT_DIR}/merge_report.md",
            'size': '生成中'
        })

        # images 目录
        if os.path.isdir(images_dir):
            img_files = [
                f for f in os.listdir(images_dir)
                if os.path.isfile(os.path.join(images_dir, f)) and f.endswith('.png')
            ]
            total_size = 0
            for img in img_files:
                try:
                    total_size += os.path.getsize(os.path.join(images_dir, img))
                except Exception:
                    pass
            result.append({
                'name': '图片目录',
                'path': f"{FINAL_DOCUMENT_DIR}/{IMAGES_SUBDIR}/",
                'size': f"{len(img_files)} 个文件，{self._format_file_size(total_size)}"
            })
        else:
            result.append({
                'name': '图片目录',
                'path': f"{FINAL_DOCUMENT_DIR}/{IMAGES_SUBDIR}/",
                'size': '0 个文件'
            })

        # merged_proposal_raw.md（merge-agent 生成的中间文件）
        raw_path = os.path.join(final_doc_dir, 'merged_proposal_raw.md')
        if os.path.exists(raw_path):
            result.append({
                'name': 'merged_proposal_raw.md',
                'path': f"{FINAL_DOCUMENT_DIR}/merged_proposal_raw.md",
                'size': self._get_file_size_str(raw_path)
            })

        # merge_stats.json（merge-agent 生成的统计文件）
        stats_path = os.path.join(final_doc_dir, 'merge_stats.json')
        if os.path.exists(stats_path):
            result.append({
                'name': 'merge_stats.json',
                'path': f"{FINAL_DOCUMENT_DIR}/merge_stats.json",
                'size': self._get_file_size_str(stats_path)
            })

        return result

    # ==========================================================
    # 5. update_metadata_status：更新项目状态
    # ==========================================================

    def update_metadata_status(self, workspace_path: str, status: str = None,
                               export_file_path: str = None) -> dict:
        """
        更新 metadata.json 项目状态为「合并导出完成」

        更新字段：
        - 项目状态 → "合并导出完成"（或自定义 status）
        - 状态更新时间 → 当前时间戳
        - export_completed_at → 当前时间戳（新增字段）
        - export_file_path → Word 文档路径（新增字段，如提供）

        Args:
            workspace_path: 工作空间路径
            status: 项目状态值（默认"合并导出完成"）
            export_file_path: Word 文档路径（可选）

        Returns:
            dict: 更新结果
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'status': status or PROJECT_STATUS_EXPORT_COMPLETED,
                'error': f'工作空间不存在: {workspace_path}'
            }

        if not status:
            status = PROJECT_STATUS_EXPORT_COMPLETED

        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {
                'success': False,
                'status': status,
                'error': 'metadata.json 不存在或解析失败'
            }

        # 当前时间戳
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')

        # 更新字段
        updated_fields = []
        metadata[FIELD_PROJECT_STATUS] = status
        updated_fields.append(FIELD_PROJECT_STATUS)

        metadata[FIELD_STATUS_UPDATE_TIME] = timestamp
        updated_fields.append(FIELD_STATUS_UPDATE_TIME)

        metadata[FIELD_EXPORT_COMPLETED_AT] = timestamp
        updated_fields.append(FIELD_EXPORT_COMPLETED_AT)

        # 如未提供 export_file_path，尝试在 final_document_file 下查找 docx 文件
        if not export_file_path:
            final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
            if os.path.isdir(final_doc_dir):
                for file in os.listdir(final_doc_dir):
                    if file.endswith('.docx'):
                        export_file_path = f"{FINAL_DOCUMENT_DIR}/{file}"
                        break

        if export_file_path:
            metadata[FIELD_EXPORT_FILE_PATH] = export_file_path
            updated_fields.append(FIELD_EXPORT_FILE_PATH)

        # 保存
        if not self._save_metadata(workspace_path, metadata):
            return {
                'success': False,
                'status': status,
                'error': '保存 metadata.json 失败'
            }

        return {
            'success': True,
            'status': status,
            'updated_fields': updated_fields,
            'export_file_path': export_file_path or ''
        }

    # ==========================================================
    # 6. get_export_status：获取导出状态（用于中断恢复）
    # ==========================================================

    def get_export_status(self, workspace_path: str) -> dict:
        """
        获取导出状态（用于中断恢复）

        检查内容：
        - metadata.json 中的项目状态
        - final_document_file/ 目录是否存在
        - merged_proposal.md 是否存在
        - 技术方案.docx 是否存在
        - merge_report.md 是否存在
        - images/ 目录下是否有 PNG 文件

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 导出状态信息
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}'}
            }

        # 读取 metadata
        metadata = self._read_metadata(workspace_path)
        project_status = metadata.get(FIELD_PROJECT_STATUS, '')
        proposal_files_locked = metadata.get(FIELD_PROPOSAL_FILES_LOCKED, False)

        # 检查 final_document_file 目录
        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)
        final_doc_exists = os.path.isdir(final_doc_dir)

        # 检查 merged_proposal.md
        merged_path = os.path.join(final_doc_dir, 'merged_proposal.md')
        merged_exists = os.path.exists(merged_path) and os.path.getsize(merged_path) > 0

        # 检查 docx 文件
        docx_exists = False
        docx_filename = ''
        if final_doc_exists:
            for file in os.listdir(final_doc_dir):
                if file.endswith('.docx'):
                    docx_path = os.path.join(final_doc_dir, file)
                    if os.path.exists(docx_path) and os.path.getsize(docx_path) > 0:
                        docx_exists = True
                        docx_filename = file
                        break

        # 检查 merge_report.md
        report_path = os.path.join(final_doc_dir, 'merge_report.md')
        report_exists = os.path.exists(report_path) and os.path.getsize(report_path) > 0

        # 检查 images 目录
        images_dir = os.path.join(final_doc_dir, IMAGES_SUBDIR)
        images_count = 0
        if os.path.isdir(images_dir):
            for file in os.listdir(images_dir):
                if file.endswith('.png'):
                    images_count += 1

        # 判断中断恢复点
        # resume_from:
        # - start: 未开始（前置条件未满足）
        # - merge: 已开始但未完成合并（merged_proposal.md 不存在）
        # - render: 已合并但未完成图表渲染（images_count 为 0 但 merged_proposal 存在）
        # - convert: 已渲染但未完成 Word 转换（docx 不存在）
        # - report: 已转换但未生成报告（report 不存在）
        # - done: 全部完成
        if project_status == PROJECT_STATUS_EXPORT_COMPLETED and report_exists:
            resume_from = 'done'
        elif report_exists:
            resume_from = 'done'
        elif docx_exists:
            resume_from = 'report'
        elif merged_exists:
            if images_count > 0:
                resume_from = 'convert'
            else:
                resume_from = 'render'
        elif final_doc_exists:
            resume_from = 'merge'
        elif proposal_files_locked:
            resume_from = 'start'
        else:
            resume_from = 'start'

        export_started = final_doc_exists or merged_exists or docx_exists

        return {
            'success': True,
            'result': {
                'project_status': project_status,
                'proposal_files_locked': proposal_files_locked,
                'export_started': export_started,
                'final_document_exists': final_doc_exists,
                'merged_proposal_exists': merged_exists,
                'docx_exists': docx_exists,
                'docx_filename': docx_filename,
                'merge_report_exists': report_exists,
                'images_count': images_count,
                'resume_from': resume_from
            }
        }

    # ==========================================================
    # 7. validate_export_output：验证导出产出文件完整性
    # ==========================================================

    def validate_export_output(self, workspace_path: str) -> dict:
        """
        验证导出产出文件完整性

        验证内容：
        - merged_proposal.md 存在且非空
        - 技术方案.docx 存在且非空
        - merge_report.md 存在且非空
        - images/ 目录下的 PNG 文件数量与图表映射一致

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 验证结果
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}'}
            }

        final_doc_dir = os.path.join(workspace_path, FINAL_DOCUMENT_DIR)

        # merged_proposal.md
        merged_path = os.path.join(final_doc_dir, 'merged_proposal.md')
        merged_exists = os.path.exists(merged_path) and os.path.getsize(merged_path) > 0
        merged_size = self._get_file_size_str(merged_path) if os.path.exists(merged_path) else "不存在"

        # docx 文件
        docx_path = None
        docx_size = "不存在"
        docx_exists = False
        if os.path.isdir(final_doc_dir):
            for file in os.listdir(final_doc_dir):
                if file.endswith('.docx'):
                    candidate = os.path.join(final_doc_dir, file)
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        docx_path = candidate
                        docx_size = self._get_file_size_str(candidate)
                        docx_exists = True
                        break

        # merge_report.md
        report_path = os.path.join(final_doc_dir, 'merge_report.md')
        report_exists = os.path.exists(report_path) and os.path.getsize(report_path) > 0
        report_size = self._get_file_size_str(report_path) if os.path.exists(report_path) else "不存在"

        # images 目录
        images_dir = os.path.join(final_doc_dir, IMAGES_SUBDIR)
        actual_images = []
        if os.path.isdir(images_dir):
            for file in os.listdir(images_dir):
                if file.endswith('.png'):
                    actual_images.append(file)

        # 期望图片数量（基于图表映射）
        expected_charts = 0
        missing_images = []
        chart_mapping_result = self.generate_chart_mapping(workspace_path)
        if chart_mapping_result.get('success'):
            chart_mapping = chart_mapping_result['result']['chart_mapping']
            expected_charts = len(chart_mapping)
            for chart_id, info in chart_mapping.items():
                png_filename = info.get('png_filename', f"{chart_id}.png")
                # 检查实际图片或占位图是否存在
                png_exists = png_filename in actual_images
                placeholder_exists = f"{chart_id}_placeholder.png" in actual_images
                if not png_exists and not placeholder_exists:
                    missing_images.append(png_filename)

        success = (merged_exists and docx_exists and report_exists
                   and len(missing_images) == 0)

        return {
            'success': success,
            'result': {
                'merged_proposal': {
                    'exists': merged_exists,
                    'size': merged_size
                },
                'docx_file': {
                    'exists': docx_exists,
                    'size': docx_size,
                    'path': os.path.basename(docx_path) if docx_path else ''
                },
                'merge_report': {
                    'exists': report_exists,
                    'size': report_size
                },
                'images': {
                    'count': len(actual_images),
                    'expected': expected_charts,
                    'missing': missing_images
                }
            }
        }


# ==========================================================
# 模块级函数封装（便于 run_skill.py 通过 getattr 调用）
# ==========================================================

_skill_instance = MergeExportSkill()


def check_export_prerequisites(workspace_path: str) -> dict:
    """校验导出前置条件"""
    return _skill_instance.check_export_prerequisites(workspace_path)


def get_merge_order(workspace_path: str) -> dict:
    """获取深度优先合并顺序"""
    return _skill_instance.get_merge_order(workspace_path)


def generate_chart_mapping(workspace_path: str) -> dict:
    """生成图表映射表"""
    return _skill_instance.generate_chart_mapping(workspace_path)


def merge_proposal(workspace_path: str) -> dict:
    """主控 Agent 直接合并正文（替代 merge-agent 子智能体）"""
    return _skill_instance.merge_proposal(workspace_path)


def generate_merge_report(workspace_path: str, export_stats: dict = None) -> dict:
    """生成合并导出报告（export_stats 可选，缺失时自动汇总）"""
    return _skill_instance.generate_merge_report(workspace_path, export_stats)


def update_metadata_status(workspace_path: str, status: str = None,
                           export_file_path: str = None) -> dict:
    """更新项目状态"""
    return _skill_instance.update_metadata_status(workspace_path, status, export_file_path)


def get_export_status(workspace_path: str) -> dict:
    """获取导出状态（用于中断恢复）"""
    return _skill_instance.get_export_status(workspace_path)


def validate_export_output(workspace_path: str) -> dict:
    """验证导出产出文件完整性"""
    return _skill_instance.validate_export_output(workspace_path)


if __name__ == '__main__':
    # 命令行测试入口
    import argparse
    parser = argparse.ArgumentParser(description='Merge Export Skill 测试')
    parser.add_argument('--workspace_path', required=True, help='工作空间路径')
    parser.add_argument('--function', required=True,
                        choices=['check_export_prerequisites', 'get_merge_order',
                                 'generate_chart_mapping', 'merge_proposal',
                                 'get_export_status', 'validate_export_output'],
                        help='测试函数')
    args = parser.parse_args()

    func_map = {
        'check_export_prerequisites': check_export_prerequisites,
        'get_merge_order': get_merge_order,
        'generate_chart_mapping': generate_chart_mapping,
        'merge_proposal': merge_proposal,
        'get_export_status': get_export_status,
        'validate_export_output': validate_export_output,
    }

    result = func_map[args.function](args.workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
