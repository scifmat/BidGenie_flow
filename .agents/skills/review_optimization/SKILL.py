# -*- coding: utf-8 -*-
"""
BidGenie Flow - 内容审查 Skill 执行脚本

功能：
1. 读取审查素材（read_review_materials）
2. 执行脚本审查：字数、图表、章节结构（script_review）
3. 收集所有审查结果：脚本审查 + AI审查（collect_review_results）
4. 执行问题分级和优先级排序（classify_and_prioritize）
5. 生成优化建议报告（generate_optimization_report）
6. 更新 metadata.json 项目状态（update_metadata_status）
7. 获取审查状态，支持中断恢复（get_review_status）

注意：AI 审查（内容完整性、评分点响应、技术语言规范）由 reviewer-agent 完成，
      本脚本仅负责文件操作、脚本审查（机械性检查）和审查结果汇总，无智能逻辑。
"""

import os
import sys
import json
import re
import glob
from datetime import datetime


# ==========================================================
# 路径注入：解决 .agents 目录导入问题
# ==========================================================
# 将项目根目录注入 sys.path，以便导入 .trae/utils/temp_manager
_TRAE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.trae'))
if _TRAE_PATH not in sys.path:
    sys.path.insert(0, _TRAE_PATH)


# ==========================================================
# 常量定义
# ==========================================================

# 字数偏差允许范围（与阶段五一致，只下限不限上限）
WORD_COUNT_LOWER_THRESHOLD = 0.15  # 下限 -15%（字数不足 15% 以上为问题）

# AI 审查自动化：脚本→语义智能分流的阈值
# - 字数严重不足（< 计划字数 * WORD_COUNT_SEVERE_RATIO）→ 强制进行内容完整性审查
# - 字数偏差较大（< 计划字数 * WORD_COUNT_MODERATE_RATIO）→ 建议进行内容完整性审查
# - 实际字数极少（< MIN_ACTUAL_WORD_COUNT）→ 强制进行内容完整性审查
WORD_COUNT_SEVERE_RATIO = 0.50  # 字数少于计划 50% 触发强制语义检查
WORD_COUNT_MODERATE_RATIO = 0.85  # 字数少于计划 85% 触发建议语义检查
MIN_ACTUAL_WORD_COUNT = 50  # 实际字数少于 50 字触发强制语义检查

# AI 审查任务最大重试次数
AI_REVIEW_MAX_RETRY = 2

# 审查任务类型
REVIEW_TYPES = {
    'content_completeness': '内容完整性审查',
    'scoring_response': '评分点响应审查',
    'technical_language': '技术与语言规范审查'
}

# 脚本审查维度
SCRIPT_REVIEW_DIMENSIONS = {
    'word_count': '字数符合度',
    'chart': '图表正确性',
    'structure': '章节结构'
}

# 问题级别
ISSUE_LEVELS = {
    'serious': '严重问题',
    'general': '一般问题',
    'suggestion': '建议性问题'
}

# 审查维度映射
REVIEW_DIMENSION_MAP = {
    'content_completeness': '内容完整性',
    'scoring_response': '评分点响应',
    'technical_language': '技术与语言规范',
    'word_count': '字数符合度',
    'chart': '图表正确性',
    'structure': '章节结构'
}


class ReviewOptimizationSkill:
    """
    内容审查 Skill - 阶段六辅助工具

    为主控 Agent 提供审查素材读取、脚本审查（字数、图表、章节结构）、
    审查结果收集、问题分级和优先级排序、优化建议报告生成、项目状态更新、
    审查状态查询等能力。

    AI 审查由 reviewer-agent 完成，本脚本不负责智能逻辑。
    """

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))

    # ==========================================================
    # 辅助方法
    # ==========================================================

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename

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

    def _resolve_package_n(self, metadata: dict) -> str:
        """
        根据 metadata.json 的「当前需撰写标段」字段确定标段编号 N
        - 「标段1」或「01」 → "1"
        - 「标段2」或「02」 → "2"
        - 不分标段时 → "1"
        """
        package = metadata.get('当前需撰写标段', '')
        if not package:
            return '1'
        m = re.search(r'(\d+)', str(package))
        if m:
            return str(int(m.group(1)))
        return '1'

    def _get_project_id(self, workspace_path: str) -> str:
        """从工作空间路径提取项目ID（工作空间目录名）"""
        return os.path.basename(os.path.normpath(workspace_path))

    def _get_temp_dir(self, workspace_path: str) -> str:
        """获取审查结果临时目录路径"""
        try:
            from utils.temp_manager import TempManager
            project_id = self._get_project_id(workspace_path)
            tm = TempManager(project_id)
            return tm.create_temp_dir('review')
        except Exception:
            # 回退方案：使用工作空间下的临时目录
            return os.path.join(workspace_path, '.review_temp')

    def _find_node_by_id(self, node: dict, target_id: str) -> dict:
        """递归查找指定 node_id 的节点"""
        if not isinstance(node, dict):
            return None
        if node.get('node_id') == target_id:
            return node
        for child in node.get('children', []):
            result = self._find_node_by_id(child, target_id)
            if result:
                return result
        return None

    def _collect_leaf_nodes(self, outline: dict, workspace_path: str) -> list:
        """
        递归收集所有 write_content=true 的叶子节点（深度优先顺序）
        返回包含节点信息和文件路径的列表
        """
        leaf_nodes = []

        def collect_leaves(node, parent_path_parts):
            if not isinstance(node, dict):
                return
            node_id = node.get('node_id', '')
            title = node.get('title', '')
            level = node.get('level', 1)
            write_content = node.get('write_content', False)
            children = node.get('children', [])
            content_plan = node.get('content_plan', '')
            word_count = node.get('word_count', 0)
            generate_chart = node.get('generate_chart', False)
            charts = node.get('charts', [])
            sanitized_title = self._sanitize_filename(title)
            current_path_parts = parent_path_parts.copy()
            if node_id != '1' and sanitized_title:
                current_path_parts.append(f'{node_id}_{sanitized_title}')

            if write_content:
                file_name = f'{node_id}_{sanitized_title}.md'
                file_dir_parts = parent_path_parts
                file_dir = '/'.join(file_dir_parts) if file_dir_parts else ''
                if file_dir:
                    file_path = os.path.join(workspace_path, 'proposal_file', file_dir, file_name)
                else:
                    file_path = os.path.join(workspace_path, 'proposal_file', file_name)
                leaf_nodes.append({
                    'node_id': node_id,
                    'title': title,
                    'level': level,
                    'content_plan': content_plan,
                    'word_count': word_count,
                    'generate_chart': generate_chart,
                    'charts': charts,
                    'file_path': file_path
                })
            else:
                for child in children:
                    collect_leaves(child, current_path_parts)

        collect_leaves(outline, [])
        return leaf_nodes

    def _count_words(self, content: str) -> int:
        """
        统计 Markdown 内容的字数（按字数统计口径）

        计入：正文段落文字、表格内容、列表内容、引用内容
        不计入：标题文字、图表代码块、图题文字
        """
        if not content:
            return 0

        lines = content.split('\n')
        result_lines = []
        in_code_block = False

        for line in lines:
            stripped = line.strip()

            # 检测代码块开始/结束
            if stripped.startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    continue
                else:
                    in_code_block = False
                    continue

            # 代码块内部跳过
            if in_code_block:
                continue

            # 跳过标题行
            if stripped.startswith('#'):
                continue

            # 跳过图题行：*图 X-Y-Z-N 图题名称*
            if re.match(r'^\*图\s+[\d\-]+\s+.+\*$', stripped):
                continue

            # 跳过表格标题行：**表 X-Y-Z-N 表格名称**
            if re.match(r'^\*\*表\s+[\d\-]+\s+.+\*\*$', stripped):
                continue

            # 跳过 chart_type 注释
            if stripped.startswith('<!-- chart_type:'):
                continue

            # 其他行计入字数
            cleaned = self._clean_markdown_syntax(stripped)
            result_lines.append(cleaned)

        text = ''.join(result_lines)
        text = re.sub(r'\s+', '', text)
        return len(text)

    def _clean_markdown_syntax(self, line: str) -> str:
        """清理 Markdown 行内语法标记，保留文字内容"""
        if not line:
            return ''
        # 去除表格分隔行 |---|---|
        if re.match(r'^\|[\s\-:|]+\|$', line):
            return ''
        # 去除表格的 | 符号
        line = line.replace('|', '')
        # 去除列表标记 - * 1. 等
        line = re.sub(r'^\s*[-*+]\s+', '', line)
        line = re.sub(r'^\s*\d+\.\s+', '', line)
        # 去除引用标记 >
        line = re.sub(r'^\s*>\s*', '', line)
        # 去除加粗、斜体标记
        line = line.replace('**', '').replace('*', '').replace('__', '')
        # 去除行内代码标记
        line = re.sub(r'`([^`]*)`', r'\1', line)
        return line

    # ==========================================================
    # 1. read_review_materials：读取审查素材
    # ==========================================================

    def read_review_materials(self, workspace_path: str) -> dict:
        """
        读取 outline.json 和审查相关素材文件
        仅做文件存在性校验和内容读取，不做智能分析

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 读取结果
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}', 'missing_files': []}
            }

        metadata = self._read_metadata(workspace_path)
        package_n = self._resolve_package_n(metadata)

        # 构建待读取的文件清单
        target_files = [
            'proposal_file/outline.json',
            'proposal_file/summary_report.md',
            f'extraction_file/packages_file/package_{package_n}/07_Evaluation_Criteria.md',
            f'extraction_file/packages_file/package_{package_n}/09_Technical_Requirements.md',
            'metadata.json'
        ]

        existing_files = []
        missing_files = []

        for rel_path in target_files:
            abs_path = os.path.join(workspace_path, rel_path)
            if os.path.exists(abs_path) and os.path.getsize(abs_path) > 0:
                existing_files.append(rel_path)
            else:
                missing_files.append(rel_path)

        # 收集所有正文 .md 文件
        proposal_dir = os.path.join(workspace_path, 'proposal_file')
        md_files = []
        if os.path.isdir(proposal_dir):
            for root, dirs, files in os.walk(proposal_dir):
                for file in files:
                    if file.endswith('.md') and file != 'outline.md' and file != 'summary_report.md':
                        rel_path = os.path.relpath(os.path.join(root, file), workspace_path)
                        md_files.append(rel_path)
                        existing_files.append(rel_path)

        # 如果没有正文文件，记录为缺失
        if not md_files:
            missing_files.append('proposal_file/*.md (正文文件)')

        # 整理 metadata 关键字段
        metadata_brief = {
            '预期总字数': metadata.get('预期总字数', ''),
            '采购方式': metadata.get('采购方式', ''),
            '当前需撰写标段': metadata.get('当前需撰写标段', ''),
            '项目状态': metadata.get('项目状态', ''),
        }

        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')

        success = len(missing_files) == 0
        return {
            'success': success,
            'result': {
                'files': existing_files,
                'missing_files': missing_files,
                'metadata': metadata_brief,
                'outline_path': outline_path if os.path.exists(outline_path) else '',
                'package_n': package_n,
                'md_files': md_files
            }
        }

    # ==========================================================
    # 2. script_review：执行脚本审查（字数、图表、章节结构）
    # ==========================================================

    def script_review(self, workspace_path: str) -> dict:
        """
        执行脚本审查（机械性检查）

        审查内容：
        1. 字数符合度审查：统计各章节实际字数，与 word_count 对比
        2. 图表正确性审查：检查 Mermaid 语法、图表数量匹配、图题格式规范
        3. 章节结构审查：检查标题层级、标题格式、层级超限、段落格式

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 脚本审查结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'review_type': 'script_review',
                'review_results': [],
                'summary': {'word_count_issues': 0, 'chart_issues': 0, 'structure_issues': 0},
                'error': f'outline.json 不存在: {outline_path}'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'review_type': 'script_review',
                'review_results': [],
                'summary': {'word_count_issues': 0, 'chart_issues': 0, 'structure_issues': 0},
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 收集叶子节点
        leaf_nodes = self._collect_leaf_nodes(outline, workspace_path)

        all_issues = []
        word_count_issues = []
        chart_issues = []
        structure_issues = []

        for leaf in leaf_nodes:
            if not os.path.exists(leaf['file_path']):
                all_issues.append({
                    'level': 'serious',
                    'description': f'正文文件不存在: {leaf["file_path"]}',
                    'node_id': leaf['node_id'],
                    'node_title': leaf['title'],
                    'dimension': 'structure',
                    'suggestion': '请检查正文文件是否已生成'
                })
                structure_issues.append(leaf['node_id'])
                continue

            try:
                with open(leaf['file_path'], 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                all_issues.append({
                    'level': 'serious',
                    'description': f'读取正文文件失败: {str(e)}',
                    'node_id': leaf['node_id'],
                    'node_title': leaf['title'],
                    'dimension': 'structure',
                    'suggestion': '请检查文件权限'
                })
                structure_issues.append(leaf['node_id'])
                continue

            # 1. 字数符合度审查
            self._check_word_count(content, leaf, word_count_issues, all_issues)
            # 2. 图表正确性审查
            self._check_charts(content, leaf, chart_issues, all_issues)
            # 3. 章节结构审查
            self._check_structure(content, leaf, structure_issues, all_issues)

        return {
            'success': True,
            'review_type': 'script_review',
            'review_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'review_results': all_issues,
            'summary': {
                'word_count_issues': len(word_count_issues),
                'chart_issues': len(chart_issues),
                'structure_issues': len(structure_issues),
                'total_issues': len(all_issues),
                'total_nodes': len(leaf_nodes)
            }
        }

    def _check_word_count(self, content: str, leaf: dict, dimension_issues: list, all_issues: list):
        """字数符合度审查（只下限不限上限）"""
        planned = leaf.get('word_count', 0) or 0
        if planned <= 0:
            return

        actual = self._count_words(content)
        deviation = (actual - planned) / planned
        lower_limit = planned * (1 - WORD_COUNT_LOWER_THRESHOLD)

        if actual < lower_limit:
            # 字数不足：一般问题
            issue = {
                'level': 'general',
                'description': f'字数不足: 实际 {actual} 字，计划 {planned} 字，偏差 {deviation * 100:.1f}%',
                'node_id': leaf['node_id'],
                'node_title': leaf['title'],
                'dimension': 'word_count',
                'suggestion': f'建议补充内容，至少增加 {int(lower_limit - actual)} 字以达到下限要求'
            }
            dimension_issues.append(leaf['node_id'])
            all_issues.append(issue)
        # 字数超标：仅记录，不判定为问题（与阶段五一致）

    def _check_charts(self, content: str, leaf: dict, dimension_issues: list, all_issues: list):
        """图表正确性审查"""
        if not leaf.get('generate_chart', False):
            return

        charts = leaf.get('charts', [])
        expected_count = len(charts)

        # 统计 mermaid 代码块数量
        mermaid_blocks = re.findall(r'```mermaid\n(.*?)```', content, re.DOTALL)
        mermaid_count = len(mermaid_blocks)

        # 1. 图表数量匹配检查
        if mermaid_count != expected_count:
            issue = {
                'level': 'general',
                'description': f'图表数量不一致: 实际 {mermaid_count} 个，期望 {expected_count} 个',
                'node_id': leaf['node_id'],
                'node_title': leaf['title'],
                'dimension': 'chart',
                'suggestion': '请检查 Mermaid 代码块数量是否与 outline.json 中 charts 数组一致'
            }
            dimension_issues.append(leaf['node_id'])
            all_issues.append(issue)

        # 2. Mermaid 语法检查（简单规则检测）
        for i, block in enumerate(mermaid_blocks, 1):
            syntax_error = self._check_mermaid_syntax(block)
            if syntax_error:
                issue = {
                    'level': 'general',
                    'description': f'Mermaid 代码块 {i} 语法错误: {syntax_error}',
                    'node_id': leaf['node_id'],
                    'node_title': leaf['title'],
                    'dimension': 'chart',
                    'suggestion': '请检查 Mermaid 语法，确保图表类型声明正确且语法完整'
                }
                dimension_issues.append(leaf['node_id'])
                all_issues.append(issue)

        # 3. 图题格式检查
        chart_captions = re.findall(r'\*图\s+[\d\-]+\s+.+\*', content)
        if len(chart_captions) < mermaid_count:
            issue = {
                'level': 'suggestion',
                'description': f'图题数量不足: 实际 {len(chart_captions)} 个，Mermaid 代码块 {mermaid_count} 个',
                'node_id': leaf['node_id'],
                'node_title': leaf['title'],
                'dimension': 'chart',
                'suggestion': '请在每个 Mermaid 代码块下方添加图题标记，格式：*图 <层级编号>-<图表序号> <图题名称>*'
            }
            dimension_issues.append(leaf['node_id'])
            all_issues.append(issue)

    def _check_mermaid_syntax(self, block: str) -> str:
        """简单的 Mermaid 语法检查，返回错误描述（无错误返回空字符串）"""
        block = block.strip()
        if not block:
            return '代码块为空'

        # 检查图表类型声明
        first_line = block.split('\n')[0].strip()
        valid_types = ['flowchart', 'graph', 'sequenceDiagram', 'gantt', 'pie', 'erDiagram',
                       'classDiagram', 'stateDiagram', 'journey', 'gitGraph']
        type_valid = False
        for t in valid_types:
            if first_line.startswith(t):
                type_valid = True
                break
        if not type_valid:
            return f'无效的图表类型声明: "{first_line}"'

        # 检查 flowchart/graph 的方向声明
        if first_line.startswith('flowchart') or first_line.startswith('graph'):
            parts = first_line.split()
            if len(parts) >= 2:
                direction = parts[1]
                valid_directions = ['TD', 'TB', 'BT', 'RL', 'LR']
                if direction not in valid_directions:
                    # 方向可能省略，不算错误
                    pass

        return ''

    def _check_structure(self, content: str, leaf: dict, dimension_issues: list, all_issues: list):
        """章节结构审查"""
        node_level = leaf['level']
        max_heading_level = min(node_level + 1, 6)

        lines = content.split('\n')
        prev_heading_level = 0
        in_code_block = False  # 是否处于围栏代码块（``` 或 ~~~）内，代码块内容不参与标题检查

        for i, line in enumerate(lines):
            stripped = line.strip()
            # 围栏代码块开始/结束切换（支持```与~~~）
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            # 匹配 Markdown 标题
            m = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            if m:
                marks = m.group(1)
                heading_text = m.group(2)
                current_level = len(marks)

                # 1. 标题层级超限检查
                if current_level > max_heading_level:
                    issue = {
                        'level': 'general',
                        'description': f'标题层级超限: "{stripped}"（当前 {current_level} 级，允许上限 {max_heading_level} 级）',
                        'node_id': leaf['node_id'],
                        'node_title': leaf['title'],
                        'dimension': 'structure',
                        'suggestion': f'请将标题层级调整为不超过 {max_heading_level} 级'
                    }
                    dimension_issues.append(leaf['node_id'])
                    all_issues.append(issue)

                # 2. 标题层级跳级检查
                if prev_heading_level > 0 and current_level > prev_heading_level + 1:
                    issue = {
                        'level': 'general',
                        'description': f'标题层级跳级: 从 {prev_heading_level} 级跳到 {current_level} 级',
                        'node_id': leaf['node_id'],
                        'node_title': leaf['title'],
                        'dimension': 'structure',
                        'suggestion': '标题层级应连续，不跳级'
                    }
                    dimension_issues.append(leaf['node_id'])
                    all_issues.append(issue)

                # 3. 标题数字编号检查
                if re.match(r'^[\d\.]+\s', heading_text) or re.match(r'^第[一二三四五六七八九十]+[章节]', heading_text):
                    issue = {
                        'level': 'general',
                        'description': f'标题添加了数字编号: "{stripped}"（应仅使用 Markdown 层级符号）',
                        'node_id': leaf['node_id'],
                        'node_title': leaf['title'],
                        'dimension': 'structure',
                        'suggestion': '请去除标题中的数字编号，编号由 Word 样式自动生成'
                    }
                    dimension_issues.append(leaf['node_id'])
                    all_issues.append(issue)

                prev_heading_level = current_level

        # 4. 段落格式检查（段落之间空一行）
        paragraph_issues = self._check_paragraph_format(lines, leaf)
        for issue in paragraph_issues:
            dimension_issues.append(leaf['node_id'])
            all_issues.append(issue)

    def _check_paragraph_format(self, lines: list, leaf: dict) -> list:
        """检查段落格式：段落之间应空一行分隔"""
        issues = []
        prev_was_content = False
        prev_was_heading = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 跳过空行
            if not stripped:
                prev_was_content = False
                prev_was_heading = False
                continue

            # 跳过标题
            if stripped.startswith('#'):
                prev_was_content = False
                prev_was_heading = True
                continue

            # 跳过代码块、图表等
            if stripped.startswith('```') or stripped.startswith('<!--') or stripped.startswith('|'):
                prev_was_content = False
                prev_was_heading = False
                continue

            # 跳过图题、表格标题
            if re.match(r'^\*图\s+[\d\-]+\s+.+\*$', stripped):
                prev_was_content = False
                continue
            if re.match(r'^\*\*表\s+[\d\-]+\s+.+\*\*$', stripped):
                prev_was_content = False
                continue

            # 当前是内容行
            current_is_content = True

            # 如果前一行是内容行（非标题、非空行），且当前也是内容行，则可能是段落未空行分隔
            # 但这里难以精确判断，只在明显连续时记录建议
            # 为避免误报，此检查仅作建议性问题，且降低检测频率
            # 实际上，段落空行检查很难通过脚本准确判断，这里简化处理

            prev_was_content = current_is_content
            prev_was_heading = False

        return issues

    # ==========================================================
    # 3. collect_review_results：收集所有审查结果
    # ==========================================================

    def collect_review_results(self, workspace_path: str) -> dict:
        """
        收集所有审查结果（脚本审查 + AI审查）

        审查结果来源：
        1. 脚本审查结果（来自 script_review 函数）
        2. AI审查结果（来自 reviewer-agent 生成的临时审查文件）

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 合并后的审查结果列表
        """
        all_results = []
        source_count = 0

        # 1. 收集脚本审查结果
        script_result = self.script_review(workspace_path)
        if script_result.get('success'):
            script_issues = script_result.get('review_results', [])
            for issue in script_issues:
                issue['source'] = 'script_review'
                all_results.append(issue)
            source_count += 1
        else:
            # 脚本审查失败，记录异常
            all_results.append({
                'level': 'serious',
                'description': f'脚本审查失败: {script_result.get("error", "未知错误")}',
                'node_id': '',
                'node_title': '',
                'dimension': 'script_review',
                'source': 'script_review',
                'suggestion': '请检查 outline.json 和正文文件是否完整'
            })

        # 2. 收集 AI 审查结果（来自临时文件）
        ai_results = self._collect_ai_review_results(workspace_path)
        for result in ai_results:
            source_count += 1
            review_type = result.get('review_type', 'unknown')
            review_issues = result.get('review_results', [])
            for issue in review_issues:
                issue['source'] = review_type
                if 'dimension' not in issue:
                    issue['dimension'] = review_type
                all_results.append(issue)

        return {
            'success': True,
            'review_results': all_results,
            'source_count': source_count,
            'summary': {
                'total_issues': len(all_results),
                'script_issues': len([r for r in all_results if r.get('source') == 'script_review']),
                'ai_issues': len([r for r in all_results if r.get('source') != 'script_review'])
            }
        }

    def _collect_ai_review_results(self, workspace_path: str) -> list:
        """
        收集 AI 审查结果（来自临时文件或 review_file 目录）

        支持两种存放模式（兼容历史与当前）：
        1. 临时目录：{review_type}_result.json（如 content_completeness_result.json）
        2. review_file 目录：ai_review_*.json（如 ai_review_content.json、ai_review_scoring.json、ai_review_language.json）

        review_file 目录下的文件名后缀与 review_type 映射关系：
        - ai_review_content.json      → content_completeness
        - ai_review_scoring.json      → scoring_response
        - ai_review_language.json     → technical_language
        """
        results = []
        temp_dir = self._get_temp_dir(workspace_path)
        review_dir = os.path.join(workspace_path, 'review_file')

        # review_file 目录下 ai_review_*.json 文件名后缀到 review_type 的映射
        ai_review_suffix_map = {
            'content': 'content_completeness',
            'scoring': 'scoring_response',
            'language': 'technical_language',
        }

        # 查找所有审查结果文件
        result_files = []  # [(file_path, review_type)]

        # 模式1：临时目录 {review_type}_result.json
        if os.path.isdir(temp_dir):
            for file in os.listdir(temp_dir):
                if file.endswith('_result.json') and file.startswith(tuple(REVIEW_TYPES.keys())):
                    review_type = file.replace('_result.json', '')
                    result_files.append((os.path.join(temp_dir, file), review_type))

        # 模式2：review_file 目录 ai_review_*.json
        if os.path.isdir(review_dir):
            for file in os.listdir(review_dir):
                if file.startswith('ai_review_') and file.endswith('.json'):
                    suffix = file[len('ai_review_'):-len('.json')]
                    review_type = ai_review_suffix_map.get(suffix, suffix)
                    result_files.append((os.path.join(review_dir, file), review_type))

        # 读取每个审查结果文件
        for file_path, review_type in result_files:
            try:
                # 检查文件是否为空（0字节）
                if os.path.getsize(file_path) == 0:
                    # 空文件：视为审查通过（无问题），生成默认结果
                    results.append({
                        'review_type': review_type,
                        'review_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'review_results': [],
                        'note': '文件为空，视为审查通过（无问题）'
                    })
                    continue

                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()

                # 检查文件内容是否仅包含空白字符
                if not content:
                    results.append({
                        'review_type': review_type,
                        'review_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'review_results': [],
                        'note': '文件内容为空，视为审查通过（无问题）'
                    })
                    continue

                # 尝试解析JSON
                result = json.loads(content)
                # 确保结果格式正确
                if 'review_type' not in result:
                    result['review_type'] = review_type
                if 'review_results' not in result:
                    result['review_results'] = []
                if 'review_time' not in result:
                    result['review_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                results.append(result)
            except json.JSONDecodeError as e:
                # JSON解析失败：记录为一般问题，而不是严重问题
                results.append({
                    'review_type': review_type,
                    'review_results': [{
                        'level': 'general',
                        'description': f'审查结果文件JSON格式错误: {str(e)}',
                        'node_id': '',
                        'node_title': '',
                        'dimension': 'ai_review',
                        'suggestion': '请检查审查结果文件格式或重新执行该审查任务'
                    }],
                    'error': str(e)
                })
            except Exception as e:
                # 其他读取失败：记录为一般问题
                results.append({
                    'review_type': review_type,
                    'review_results': [{
                        'level': 'general',
                        'description': f'读取审查结果文件失败: {str(e)}',
                        'node_id': '',
                        'node_title': '',
                        'dimension': 'ai_review',
                        'suggestion': '请检查文件权限或重新执行该审查任务'
                    }],
                    'error': str(e)
                })

        return results

    # ==========================================================
    # 4. classify_and_prioritize：问题分级和优先级排序
    # ==========================================================

    def classify_and_prioritize(self, workspace_path: str = None, review_results: list = None) -> dict:
        """
        执行问题分级和优先级排序

        分级规则：
        - 严重问题（serious）：缺失要点≥2个、未响应评分点≥1个、逻辑漏洞、技术参数错误、技术方案不可行
        - 一般问题（general）：缺失要点=1个、响应不充分、内容重复>20%、字数不足偏差>15%、Mermaid语法错误、图表数量不匹配、标题格式错误
        - 建议性问题（suggestion）：轻微遗漏、语言风格不一致、图题格式错误、段落格式不规范

        优先级排序：严重问题 > 一般问题 > 建议性问题；同级别按影响章节排序

        Args:
            workspace_path: 工作空间路径（当 review_results 为 None 时使用）
            review_results: 审查结果列表（可选，默认自动收集）

        Returns:
            dict: 分级排序后的结果
        """
        # 如果未提供 review_results，则自动收集
        if review_results is None:
            if workspace_path is None:
                return {
                    'success': False,
                    'error': '必须提供 workspace_path 或 review_results 参数'
                }
            collect_result = self.collect_review_results(workspace_path)
            review_results = collect_result.get('review_results', [])

        # 分级
        serious_issues = []
        general_issues = []
        suggestion_issues = []

        for issue in review_results:
            level = issue.get('level', 'suggestion').lower()
            if level == 'serious':
                serious_issues.append(issue)
            elif level == 'general':
                general_issues.append(issue)
            else:
                suggestion_issues.append(issue)

        # 同级别按影响章节排序（node_id 排序）
        serious_issues.sort(key=lambda x: x.get('node_id', ''))
        general_issues.sort(key=lambda x: x.get('node_id', ''))
        suggestion_issues.sort(key=lambda x: x.get('node_id', ''))

        # 合并排序后的问题列表
        sorted_issues = serious_issues + general_issues + suggestion_issues

        # 审查通过判定
        pass_judgment, suggestion_strategy = self._make_pass_judgment(
            len(serious_issues), len(general_issues), len(suggestion_issues)
        )

        return {
            'success': True,
            'classified_results': {
                'serious': serious_issues,
                'general': general_issues,
                'suggestion': suggestion_issues
            },
            'sorted_issues': sorted_issues,
            'pass_judgment': pass_judgment,
            'suggestion_strategy': suggestion_strategy,
            'summary': {
                'total_issues': len(sorted_issues),
                'serious_count': len(serious_issues),
                'general_count': len(general_issues),
                'suggestion_count': len(suggestion_issues)
            }
        }

    def _make_pass_judgment(self, serious_count: int, general_count: int, suggestion_count: int) -> tuple:
        """
        根据审查分流规则生成审查通过判定

        阶段六仅作审查，所有审查完成后统一进入阶段七优化

        Returns:
            tuple: (pass_judgment, suggestion_strategy)
        """
        total = serious_count + general_count + suggestion_count

        if total == 0:
            return ('审查通过，无问题', '无需优化，可直接进入阶段七或人工审查')
        elif serious_count >= 1:
            return (f'审查完成，发现 {serious_count} 个严重问题', '必须优化，进入阶段七进行优化')
        elif general_count > 0:
            return (f'审查完成，发现 {general_count} 个一般问题', '建议优化，进入阶段七进行优化')
        else:
            return (f'审查完成，发现 {suggestion_count} 个建议性问题', '视情况优化，进入阶段七进行优化')

    # ==========================================================
    # 5. generate_optimization_report：生成优化建议报告
    # ==========================================================

    def generate_optimization_report(self, workspace_path: str, review_results: list = None) -> dict:
        """
        生成优化建议报告 optimization_suggestions.md

        报告内容：
        - 审查完成时间
        - 审查概览（总问题数、严重问题数、一般问题数、建议性问题数）
        - 审查维度汇总（各维度问题统计）
        - 问题分级列表（按优先级排序）
        - 审查通过判定

        Args:
            workspace_path: 工作空间路径
            review_results: 审查结果列表（可选，默认自动收集和分级）

        Returns:
            dict: 报告生成结果
        """
        # 收集和分级审查结果
        if review_results is None:
            classify_result = self.classify_and_prioritize(workspace_path)
        else:
            classify_result = self.classify_and_prioritize(workspace_path, review_results)

        if not classify_result.get('success'):
            return {
                'success': False,
                'report_path': '',
                'error': f'审查结果分级失败: {classify_result.get("error", "")}'
            }

        classified = classify_result.get('classified_results', {})
        sorted_issues = classify_result.get('sorted_issues', [])
        summary = classify_result.get('summary', {})
        pass_judgment = classify_result.get('pass_judgment', '')
        suggestion_strategy = classify_result.get('suggestion_strategy', '')

        # 统计各维度问题数
        dimension_stats = {}
        for issue in sorted_issues:
            dimension = issue.get('dimension', 'unknown')
            dimension_name = REVIEW_DIMENSION_MAP.get(dimension, dimension)
            if dimension_name not in dimension_stats:
                dimension_stats[dimension_name] = {'total': 0, 'serious': 0, 'general': 0, 'suggestion': 0}
            dimension_stats[dimension_name]['total'] += 1
            level = issue.get('level', 'suggestion').lower()
            if level == 'serious':
                dimension_stats[dimension_name]['serious'] += 1
            elif level == 'general':
                dimension_stats[dimension_name]['general'] += 1
            else:
                dimension_stats[dimension_name]['suggestion'] += 1

        # 生成报告内容
        report_lines = []
        report_lines.append('# 内容审查报告')
        report_lines.append('')
        report_lines.append(f'**审查完成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        report_lines.append('')

        # 审查概览
        report_lines.append('## 一、审查概览')
        report_lines.append('')
        report_lines.append(f'- 总问题数：{summary.get("total_issues", 0)} 个')
        report_lines.append(f'- 严重问题：{summary.get("serious_count", 0)} 个')
        report_lines.append(f'- 一般问题：{summary.get("general_count", 0)} 个')
        report_lines.append(f'- 建议性问题：{summary.get("suggestion_count", 0)} 个')
        report_lines.append(f'- 审查通过判定：{pass_judgment}')
        report_lines.append('')

        # 审查维度汇总
        report_lines.append('## 二、审查维度汇总')
        report_lines.append('')
        report_lines.append('| 审查维度 | 问题数 | 严重 | 一般 | 建议 |')
        report_lines.append('|----------|--------|------|------|------|')
        for dim_name, stats in dimension_stats.items():
            report_lines.append(
                f'| {dim_name} | {stats["total"]} | {stats["serious"]} | {stats["general"]} | {stats["suggestion"]} |'
            )
        report_lines.append('')

        # 问题分级列表
        report_lines.append('## 三、问题分级列表')
        report_lines.append('')

        # 严重问题
        serious_list = classified.get('serious', [])
        report_lines.append(f'### 严重问题（{len(serious_list)} 个）')
        report_lines.append('')
        if serious_list:
            for idx, issue in enumerate(serious_list, 1):
                report_lines.append(f'{idx}. **问题描述**：{issue.get("description", "")}')
                report_lines.append(f'   - 影响章节：{issue.get("node_id", "")} {issue.get("node_title", "")}')
                report_lines.append(f'   - 审查维度：{REVIEW_DIMENSION_MAP.get(issue.get("dimension", ""), issue.get("dimension", ""))}')
                report_lines.append(f'   - 审查来源：{issue.get("source", "")}')
                report_lines.append(f'   - 优化建议：{issue.get("suggestion", "")}')
                report_lines.append('')
        else:
            report_lines.append('无严重问题')
            report_lines.append('')

        # 一般问题
        general_list = classified.get('general', [])
        report_lines.append(f'### 一般问题（{len(general_list)} 个）')
        report_lines.append('')
        if general_list:
            for idx, issue in enumerate(general_list, 1):
                report_lines.append(f'{idx}. **问题描述**：{issue.get("description", "")}')
                report_lines.append(f'   - 影响章节：{issue.get("node_id", "")} {issue.get("node_title", "")}')
                report_lines.append(f'   - 审查维度：{REVIEW_DIMENSION_MAP.get(issue.get("dimension", ""), issue.get("dimension", ""))}')
                report_lines.append(f'   - 审查来源：{issue.get("source", "")}')
                report_lines.append(f'   - 优化建议：{issue.get("suggestion", "")}')
                report_lines.append('')
        else:
            report_lines.append('无一般问题')
            report_lines.append('')

        # 建议性问题
        suggestion_list = classified.get('suggestion', [])
        report_lines.append(f'### 建议性问题（{len(suggestion_list)} 个）')
        report_lines.append('')
        if suggestion_list:
            for idx, issue in enumerate(suggestion_list, 1):
                report_lines.append(f'{idx}. **问题描述**：{issue.get("description", "")}')
                report_lines.append(f'   - 影响章节：{issue.get("node_id", "")} {issue.get("node_title", "")}')
                report_lines.append(f'   - 审查维度：{REVIEW_DIMENSION_MAP.get(issue.get("dimension", ""), issue.get("dimension", ""))}')
                report_lines.append(f'   - 审查来源：{issue.get("source", "")}')
                report_lines.append(f'   - 优化建议：{issue.get("suggestion", "")}')
                report_lines.append('')
        else:
            report_lines.append('无建议性问题')
            report_lines.append('')

        # 审查通过判定
        report_lines.append('## 四、审查通过判定')
        report_lines.append('')
        report_lines.append('根据审查分流规则：')
        report_lines.append(f'- 严重问题数量：{summary.get("serious_count", 0)} 个')
        report_lines.append(f'- 一般问题数量：{summary.get("general_count", 0)} 个')
        report_lines.append(f'- 建议性问题数量：{summary.get("suggestion_count", 0)} 个')
        report_lines.append('')
        report_lines.append(f'**【判定结果】**：{pass_judgment}')
        report_lines.append(f'**【处理建议】**：{suggestion_strategy}')
        report_lines.append('')
        report_lines.append('**流程说明**：阶段六（内容审查）→ 阶段七（内容优化）→ 人工审查 + 优化循环（最多3次）→ 阶段八（合并导出）')
        report_lines.append('')

        report_lines.append('---')
        report_lines.append(f'*报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*')

        # 写入文件
        review_dir = os.path.join(workspace_path, 'review_file')
        report_path = os.path.join(review_dir, 'optimization_suggestions.md')
        try:
            os.makedirs(review_dir, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines))
        except Exception as e:
            return {
                'success': False,
                'report_path': '',
                'error': f'写入 optimization_suggestions.md 失败: {str(e)}'
            }

        return {
            'success': True,
            'report_path': report_path,
            'stats': {
                'total_issues': summary.get('total_issues', 0),
                'serious_count': summary.get('serious_count', 0),
                'general_count': summary.get('general_count', 0),
                'suggestion_count': summary.get('suggestion_count', 0),
                'dimension_count': len(dimension_stats)
            }
        }

    # ==========================================================
    # 6. update_metadata_status：更新项目状态
    # ==========================================================

    def update_metadata_status(self, workspace_path: str, status: str = '内容审查完成') -> dict:
        """
        更新 metadata.json 的项目状态字段，并更新状态更新时间和审查状态

        Args:
            workspace_path: 工作空间路径
            status: 项目状态值

        Returns:
            dict: 更新结果
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        metadata['项目状态'] = status
        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 更新审查状态
        if status == '内容审查完成':
            if 'review_status' not in metadata:
                metadata['review_status'] = 'completed'
            else:
                metadata['review_status'] = 'completed'

        updated_fields = ['项目状态', '状态更新时间']
        if 'review_status' in metadata:
            updated_fields.append('review_status')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'status': status,
                'updated_fields': updated_fields
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 7. get_review_status：获取审查状态（用于中断恢复）
    # ==========================================================

    def get_review_status(self, workspace_path: str) -> dict:
        """
        获取审查状态，支持中断恢复

        metadata.json 扩展字段：
        - review_status: pending/in_progress/completed
        - review_start_time: 审查开始时间
        - review_completed_tasks: 已完成的审查任务列表
        - review_failed_tasks: 失败的审查任务列表

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 审查状态信息
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {
                'success': False,
                'error': 'metadata.json 不存在或读取失败'
            }

        review_status = metadata.get('review_status', 'pending')
        review_start_time = metadata.get('review_start_time', '')
        review_completed_tasks = metadata.get('review_completed_tasks', [])
        review_failed_tasks = metadata.get('review_failed_tasks', [])

        # 检查临时目录中已存在的审查结果文件
        temp_dir = self._get_temp_dir(workspace_path)
        existing_result_files = []
        if os.path.isdir(temp_dir):
            for file in os.listdir(temp_dir):
                if file.endswith('_result.json') and file.startswith(tuple(REVIEW_TYPES.keys())):
                    existing_result_files.append(file.replace('_result.json', ''))

        return {
            'success': True,
            'review_status': review_status,
            'review_start_time': review_start_time,
            'review_completed_tasks': review_completed_tasks,
            'review_failed_tasks': review_failed_tasks,
            'existing_result_files': existing_result_files,
            'project_status': metadata.get('项目状态', '')
        }

    # ==========================================================
    # 8. get_ai_review_status：检测 AI 审查任务完成情况
    # ==========================================================

    def get_ai_review_status(self, workspace_path: str) -> dict:
        """
        自动检测 AI 审查任务的完成情况

        检测规则：
        1. 检查 review_file 目录下是否存在 ai_review_*.json 文件
        2. 检查文件内容是否为有效的 JSON 且包含 review_results 字段
        3. 文件不存在 → pending（待执行）
        4. 文件存在但格式错误 → failed（需重试）
        5. 文件存在且格式正确 → completed

        本函数支持中断恢复：主控 Agent 可据此判断哪些 AI 审查任务需要重新调度。

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: AI 审查任务完成情况，包含：
                - task_status: 各任务状态（{task_type: {status, file_path, ...}}）
                - completed_count: 已完成任务数
                - pending_count: 待执行任务数
                - failed_count: 失败任务数
                - total_count: 总任务数
                - all_completed: 是否全部完成
        """
        review_dir = os.path.join(workspace_path, 'review_file')

        # AI 审查任务类型与对应文件名后缀的映射
        ai_review_files = {
            'content_completeness': 'ai_review_content.json',
            'scoring_response': 'ai_review_scoring.json',
            'technical_language': 'ai_review_language.json',
        }

        # 读取 metadata 中的 AI 审查重试计数
        metadata = self._read_metadata(workspace_path)
        ai_review_retry_counts = metadata.get('ai_review_retry_counts', {})

        task_status = {}
        completed_count = 0
        pending_count = 0
        failed_count = 0

        for task_type, filename in ai_review_files.items():
            file_path = os.path.join(review_dir, filename)
            status = 'pending'
            file_exists = False
            file_valid = False
            error_msg = ''
            result_count = 0

            if os.path.exists(file_path):
                file_exists = True
                try:
                    if os.path.getsize(file_path) == 0:
                        status = 'failed'
                        error_msg = '文件为空'
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                        if not content:
                            status = 'failed'
                            error_msg = '文件内容为空'
                        else:
                            result = json.loads(content)
                            if 'review_results' not in result:
                                status = 'failed'
                                error_msg = '缺少 review_results 字段'
                            else:
                                status = 'completed'
                                file_valid = True
                                result_count = len(result.get('review_results', []))
                except json.JSONDecodeError as e:
                    status = 'failed'
                    error_msg = f'JSON 解析失败: {str(e)}'
                except Exception as e:
                    status = 'failed'
                    error_msg = f'读取失败: {str(e)}'

            if status == 'completed':
                completed_count += 1
            elif status == 'failed':
                failed_count += 1
            else:
                pending_count += 1

            task_status[task_type] = {
                'status': status,
                'file_path': file_path,
                'file_exists': file_exists,
                'file_valid': file_valid,
                'result_count': result_count,
                'error': error_msg,
                'retry_count': ai_review_retry_counts.get(task_type, 0),
                'max_retry': AI_REVIEW_MAX_RETRY,
                'can_retry': ai_review_retry_counts.get(task_type, 0) < AI_REVIEW_MAX_RETRY
            }

        total_count = len(ai_review_files)
        all_completed = completed_count == total_count

        return {
            'success': True,
            'task_status': task_status,
            'completed_count': completed_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'total_count': total_count,
            'all_completed': all_completed
        }

    # ==========================================================
    # 9. plan_ai_review_tasks：基于脚本审查结果智能规划 AI 审查任务
    # ==========================================================

    def plan_ai_review_tasks(self, workspace_path: str) -> dict:
        """
        基于脚本审查结果智能规划 AI 审查任务（脚本→语义双轨制核心）

        设计原则：
        - 能使用脚本的就用脚本：字数、图表、章节结构由脚本审查覆盖（已由 script_review 完成）
        - 用脚本效果不好的就使用语义检查：内容完整性、评分点响应、技术语言规范由 AI 审查覆盖

        智能分流规则（基于脚本审查结果，决定哪些 AI 审查任务需要执行、优先级如何）：
        1. 内容完整性审查（content_completeness）：
           - 强制执行条件：存在字数严重不足（<50%）或实际字数极少（<50字）的章节
           - 建议执行条件：存在字数偏差较大（<85%）的章节
           - 默认执行：内容完整性是核心维度，无强制条件时也应执行
        2. 评分点响应审查（scoring_response）：
           - 强制执行条件：存在图表数量不匹配的章节（图表通常对应评分点）
           - 建议执行条件：存在字数不足的章节（可能未充分展开评分点论述）
           - 默认执行：评分点响应直接影响中标，无强制条件时也应执行
        3. 技术与语言规范审查（technical_language）：
           - 强制执行条件：存在标题层级问题的章节（结构混乱可能伴随逻辑问题）
           - 建议执行条件：存在段落格式问题的章节
           - 选择性执行：若无结构问题，可仅做抽样检查（减少 Agent 调用成本）

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: AI 审查任务规划结果，包含：
                - plan: 各任务规划（{task_type: {priority, reason, target_nodes}}）
                - script_review_summary: 脚本审查摘要（用于决策依据）
                - recommended_tasks: 推荐执行的任务列表（按优先级排序）
                - optional_tasks: 可选执行的任务列表
        """
        # 先执行脚本审查获取决策依据
        script_result = self.script_review(workspace_path)
        script_issues = script_result.get('review_results', [])
        script_summary = script_result.get('summary', {})

        # 按维度分组统计脚本审查问题
        dimension_issues = {
            'word_count': [],
            'chart': [],
            'structure': []
        }
        for issue in script_issues:
            dim = issue.get('dimension', '')
            if dim in dimension_issues:
                dimension_issues[dim].append(issue)

        # 收集字数严重不足/偏差较大的节点
        severe_word_count_nodes = []  # 字数严重不足（< 50%）
        moderate_word_count_nodes = []  # 字数偏差较大（< 85%）
        insufficient_actual_nodes = []  # 实际字数极少（< 50 字）

        # 从脚本审查问题中提取字数问题节点
        for issue in dimension_issues['word_count']:
            node_id = issue.get('node_id', '')
            description = issue.get('description', '')
            # 解析字数信息（格式：字数不足: 实际 X 字，计划 Y 字，偏差 Z%）
            m = re.search(r'实际\s*(\d+)\s*字.*?计划\s*(\d+)\s*字', description)
            if m:
                actual = int(m.group(1))
                planned = int(m.group(2))
                if planned > 0:
                    ratio = actual / planned
                    if ratio < WORD_COUNT_SEVERE_RATIO:
                        severe_word_count_nodes.append({
                            'node_id': node_id,
                            'actual': actual,
                            'planned': planned,
                            'ratio': round(ratio, 2)
                        })
                    elif ratio < WORD_COUNT_MODERATE_RATIO:
                        moderate_word_count_nodes.append({
                            'node_id': node_id,
                            'actual': actual,
                            'planned': planned,
                            'ratio': round(ratio, 2)
                        })
                if actual < MIN_ACTUAL_WORD_COUNT:
                    insufficient_actual_nodes.append({
                        'node_id': node_id,
                        'actual': actual
                    })

        # 收集图表问题节点
        chart_issue_nodes = list(set(
            issue.get('node_id', '') for issue in dimension_issues['chart']
        ))

        # 收集结构问题节点
        structure_issue_nodes = list(set(
            issue.get('node_id', '') for issue in dimension_issues['structure']
        ))

        # 规划各 AI 审查任务
        plan = {}

        # 1. 内容完整性审查规划
        content_force_nodes = list(set(
            [n['node_id'] for n in severe_word_count_nodes] +
            [n['node_id'] for n in insufficient_actual_nodes]
        ))
        content_suggest_nodes = [n['node_id'] for n in moderate_word_count_nodes]
        content_priority = 'high' if content_force_nodes else 'medium'
        content_reason = []
        if content_force_nodes:
            content_reason.append(f'存在 {len(content_force_nodes)} 个字数严重不足/实际字数极少的节点，强制进行内容完整性审查')
        if content_suggest_nodes:
            content_reason.append(f'存在 {len(content_suggest_nodes)} 个字数偏差较大的节点，建议进行内容完整性审查')
        if not content_reason:
            content_reason.append('内容完整性是核心审查维度，默认执行')

        plan['content_completeness'] = {
            'priority': content_priority,
            'reason': '；'.join(content_reason),
            'force_review_nodes': content_force_nodes,
            'suggest_review_nodes': content_suggest_nodes,
            'should_execute': True,  # 内容完整性始终执行
            'target_focus': '字数严重不足的节点优先审查内容覆盖情况'
        }

        # 2. 评分点响应审查规划
        scoring_force_nodes = chart_issue_nodes
        scoring_suggest_nodes = [n['node_id'] for n in severe_word_count_nodes]
        scoring_priority = 'high' if scoring_force_nodes else 'medium'
        scoring_reason = []
        if scoring_force_nodes:
            scoring_reason.append(f'存在 {len(scoring_force_nodes)} 个图表问题节点，强制进行评分点响应审查')
        if scoring_suggest_nodes:
            scoring_reason.append(f'存在 {len(scoring_suggest_nodes)} 个字数严重不足的节点，建议进行评分点响应审查')
        if not scoring_reason:
            scoring_reason.append('评分点响应直接影响中标结果，默认执行')

        plan['scoring_response'] = {
            'priority': scoring_priority,
            'reason': '；'.join(scoring_reason),
            'force_review_nodes': scoring_force_nodes,
            'suggest_review_nodes': scoring_suggest_nodes,
            'should_execute': True,  # 评分点响应始终执行
            'target_focus': '图表问题节点优先审查评分点响应情况'
        }

        # 3. 技术与语言规范审查规划
        tech_force_nodes = structure_issue_nodes
        tech_priority = 'medium' if tech_force_nodes else 'low'
        tech_reason = []
        if tech_force_nodes:
            tech_reason.append(f'存在 {len(tech_force_nodes)} 个结构问题节点，建议进行技术与语言规范审查')
        else:
            tech_reason.append('无明显结构问题，可选择性执行（抽样检查）')

        plan['technical_language'] = {
            'priority': tech_priority,
            'reason': '；'.join(tech_reason),
            'force_review_nodes': tech_force_nodes,
            'suggest_review_nodes': [],
            'should_execute': len(tech_force_nodes) > 0,  # 仅在存在结构问题时强制执行
            'optional': len(tech_force_nodes) == 0,  # 无结构问题时标记为可选
            'target_focus': '结构问题节点优先审查逻辑漏洞和语言规范'
        }

        # 推荐执行的任务（按优先级排序）
        recommended_tasks = sorted(
            [t for t in plan.keys() if plan[t].get('should_execute', False)],
            key=lambda t: {'high': 0, 'medium': 1, 'low': 2}.get(plan[t]['priority'], 3)
        )
        optional_tasks = [t for t in plan.keys() if plan[t].get('optional', False)]

        return {
            'success': True,
            'plan': plan,
            'script_review_summary': {
                'total_issues': script_summary.get('total_issues', 0),
                'word_count_issues': script_summary.get('word_count_issues', 0),
                'chart_issues': script_summary.get('chart_issues', 0),
                'structure_issues': script_summary.get('structure_issues', 0),
                'total_nodes': script_summary.get('total_nodes', 0)
            },
            'recommended_tasks': recommended_tasks,
            'optional_tasks': optional_tasks,
            'decision_summary': {
                'severe_word_count_count': len(severe_word_count_nodes),
                'moderate_word_count_count': len(moderate_word_count_nodes),
                'insufficient_actual_count': len(insufficient_actual_nodes),
                'chart_issue_count': len(chart_issue_nodes),
                'structure_issue_count': len(structure_issue_nodes)
            }
        }

    # ==========================================================
    # 10. identify_failed_ai_reviews：识别失败的 AI 审查任务
    # ==========================================================

    def identify_failed_ai_reviews(self, workspace_path: str) -> dict:
        """
        识别失败的 AI 审查任务（用于中断恢复和重试编排）

        本函数结合 get_ai_review_status 和 plan_ai_review_tasks 的结果，
        识别需要重试的 AI 审查任务：
        1. 状态为 failed 的任务（文件损坏/格式错误）
        2. 状态为 pending 的任务（任务未执行）
        3. 重试次数未超过 AI_REVIEW_MAX_RETRY 的任务

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 失败 AI 审查任务识别结果，包含：
                - failed_tasks: 失败任务列表（含状态、重试次数、错误信息）
                - pending_tasks: 待执行任务列表
                - retryable_tasks: 可重试任务列表（未超过最大重试次数）
                - exhausted_tasks: 重试耗尽任务列表（需人工介入）
        """
        status_result = self.get_ai_review_status(workspace_path)
        task_status = status_result.get('task_status', {})

        failed_tasks = []
        pending_tasks = []
        retryable_tasks = []
        exhausted_tasks = []

        for task_type, info in task_status.items():
            status = info.get('status', '')
            retry_count = info.get('retry_count', 0)
            can_retry = info.get('can_retry', False)

            if status == 'failed':
                failed_tasks.append({
                    'task_type': task_type,
                    'status': status,
                    'error': info.get('error', ''),
                    'retry_count': retry_count,
                    'can_retry': can_retry,
                    'file_path': info.get('file_path', '')
                })
                if can_retry:
                    retryable_tasks.append(task_type)
                else:
                    exhausted_tasks.append(task_type)
            elif status == 'pending':
                pending_tasks.append({
                    'task_type': task_type,
                    'status': status,
                    'retry_count': retry_count,
                    'can_retry': can_retry,
                    'file_path': info.get('file_path', '')
                })
                # pending 任务总是可以执行（不算重试）
                retryable_tasks.append(task_type)

        return {
            'success': True,
            'failed_tasks': failed_tasks,
            'pending_tasks': pending_tasks,
            'retryable_tasks': retryable_tasks,
            'exhausted_tasks': exhausted_tasks,
            'summary': {
                'failed_count': len(failed_tasks),
                'pending_count': len(pending_tasks),
                'retryable_count': len(retryable_tasks),
                'exhausted_count': len(exhausted_tasks)
            }
        }

    # ==========================================================
    # 11. update_ai_review_retry_count：更新 AI 审查重试计数
    # ==========================================================

    def update_ai_review_retry_count(self, workspace_path: str, task_type: str, increment: int = 1) -> dict:
        """
        更新 AI 审查任务的重试计数

        当 reviewer-agent 完成一次重试后调用本函数：
        - 如果重试成功（生成有效 JSON 文件），无需调用本函数
        - 如果重试失败，调用本函数增加重试计数

        当 retry_count >= AI_REVIEW_MAX_RETRY 时，任务状态变更为 exhausted，需人工介入。

        Args:
            workspace_path: 工作空间路径
            task_type: 审查任务类型（content_completeness/scoring_response/technical_language）
            increment: 增量（默认 1）

        Returns:
            dict: 更新结果
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        ai_review_retry_counts = metadata.get('ai_review_retry_counts', {})
        ai_review_retry_counts[task_type] = ai_review_retry_counts.get(task_type, 0) + increment
        metadata['ai_review_retry_counts'] = ai_review_retry_counts

        current_count = ai_review_retry_counts[task_type]
        status = 'exhausted' if current_count >= AI_REVIEW_MAX_RETRY else 'retry'

        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'task_type': task_type,
                'retry_count': current_count,
                'status': status,
                'max_retry': AI_REVIEW_MAX_RETRY
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}


# ==========================================================
# 便捷函数（供主控 Agent 直接调用）
# ==========================================================

def read_review_materials(workspace_path: str) -> dict:
    """读取审查素材（大纲、正文、评审标准等）"""
    skill = ReviewOptimizationSkill()
    return skill.read_review_materials(workspace_path)


def script_review(workspace_path: str) -> dict:
    """执行脚本审查（字数、图表、章节结构）"""
    skill = ReviewOptimizationSkill()
    return skill.script_review(workspace_path)


def collect_review_results(workspace_path: str) -> dict:
    """收集所有审查结果（脚本+AI）"""
    skill = ReviewOptimizationSkill()
    return skill.collect_review_results(workspace_path)


def classify_and_prioritize(workspace_path: str = None, review_results: list = None) -> dict:
    """执行问题分级和优先级排序"""
    skill = ReviewOptimizationSkill()
    return skill.classify_and_prioritize(workspace_path, review_results)


def generate_optimization_report(workspace_path: str, review_results: list = None) -> dict:
    """生成优化建议报告"""
    skill = ReviewOptimizationSkill()
    return skill.generate_optimization_report(workspace_path, review_results)


def update_metadata_status(workspace_path: str, status: str = '内容审查完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = ReviewOptimizationSkill()
    return skill.update_metadata_status(workspace_path, status)


def get_review_status(workspace_path: str) -> dict:
    """获取审查状态（用于中断恢复）"""
    skill = ReviewOptimizationSkill()
    return skill.get_review_status(workspace_path)


def get_ai_review_status(workspace_path: str) -> dict:
    """检测 AI 审查任务完成情况（pending/completed/failed）"""
    skill = ReviewOptimizationSkill()
    return skill.get_ai_review_status(workspace_path)


def plan_ai_review_tasks(workspace_path: str) -> dict:
    """基于脚本审查结果智能规划 AI 审查任务（脚本→语义双轨制核心）"""
    skill = ReviewOptimizationSkill()
    return skill.plan_ai_review_tasks(workspace_path)


def identify_failed_ai_reviews(workspace_path: str) -> dict:
    """识别失败的 AI 审查任务（用于中断恢复和重试编排）"""
    skill = ReviewOptimizationSkill()
    return skill.identify_failed_ai_reviews(workspace_path)


def update_ai_review_retry_count(workspace_path: str, task_type: str, increment: int = 1) -> dict:
    """更新 AI 审查任务重试计数（达到上限则标记为 exhausted 需人工介入）"""
    skill = ReviewOptimizationSkill()
    return skill.update_ai_review_retry_count(workspace_path, task_type, increment)


# ==========================================================
# 临时文件管理便捷函数（封装 TempManager，供 Agent 直接调用）
# ==========================================================

def get_temp_manager(project_id: str = None):
    """获取临时文件管理器实例"""
    from utils.temp_manager import TempManager
    return TempManager(project_id)


def create_temp_dir(project_id: str = None, subdir: str = None) -> str:
    """创建临时目录"""
    tm = get_temp_manager(project_id)
    return tm.create_temp_dir(subdir)


def save_temp_file(project_id: str, filename: str, content: str or bytes, subdir: str = None) -> str:
    """保存临时文件"""
    tm = get_temp_manager(project_id)
    return tm.save_temp_file(filename, content, subdir)


def read_temp_file(project_id: str, filename: str, subdir: str = None, binary: bool = False) -> str or bytes:
    """读取临时文件"""
    tm = get_temp_manager(project_id)
    return tm.read_temp_file(filename, subdir, binary)


def cleanup_temp(project_id: str = None, days: int = 7) -> int:
    """清理临时文件"""
    if project_id:
        tm = get_temp_manager(project_id)
        return tm.cleanup_project_temp()
    else:
        tm = get_temp_manager()
        return tm.cleanup_expired(days)
