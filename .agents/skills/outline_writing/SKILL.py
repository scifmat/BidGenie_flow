# -*- coding: utf-8 -*-
"""
BidGenie Flow - 大纲编写 Skill 执行脚本

功能：
1. 校验输入文件存在性（read_input_files）
2. 验证 outline.json 结构完整性（validate_outline_structure）
3. 根据 outline.json 生成 outline.md（generate_outline_md）
4. 根据 outline.json 生成 proposal_file 目录结构（generate_directory_structure）
5. 更新 metadata.json 项目状态（update_metadata_status）

注意：outline.json 由 outline-agent 使用 Write 工具直接创建，本脚本不负责生成。
      本脚本仅负责文件操作和校验，无智能逻辑。
"""

import os
import sys
import json
from datetime import datetime


# ==========================================================
# 路径注入：解决 .agents 目录导入问题
# ==========================================================
# 将项目根目录注入 sys.path，以便导入 .trae/utils/temp_manager
_TRAE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.trae'))
if _TRAE_PATH not in sys.path:
    sys.path.insert(0, _TRAE_PATH)


# 校验的输入文件清单（相对路径）
COMMON_FILES = [
    'extraction_file/common_file/01_Basic_Information.md',
    'extraction_file/common_file/02_Eligibility_Review.md',
    'extraction_file/common_file/04_Compilation_Requirements.md',
    'extraction_file/common_file/05_Substantive_Response.md',
]

PACKAGE_FILES = [
    'extraction_file/packages_file/package_{N}/06_Procurement_Content.md',
    'extraction_file/packages_file/package_{N}/07_Evaluation_Criteria.md',
    'extraction_file/packages_file/package_{N}/08_Business_Requirements.md',
    'extraction_file/packages_file/package_{N}/09_Technical_Requirements.md',
]

# 字数范围约束
MIN_WORD_COUNT = 100
MAX_WORD_COUNT = 8000
DEFAULT_WORD_COUNT = 2000


class OutlineWritingSkill:
    """
    大纲编写 Skill - 阶段四辅助工具

    为主控 Agent 提供输入文件校验、大纲结构校验、outline.md 生成、
    目录结构生成、项目状态更新等能力。
    outline.json 由 outline-agent 直接创建，本脚本不负责生成。
    """

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))

    # ==========================================================
    # 1. read_input_files：校验输入文件存在性
    # ==========================================================

    def read_input_files(self, workspace_path: str, package: str) -> dict:
        """
        校验所有输入文件存在性（不读取提取文件内容，仅 metadata.json 读取关键字段）

        Args:
            workspace_path: 工作空间路径
            package: 标段编号（如 "1"、"2"）

        Returns:
            dict: 校验结果
        """
        if not os.path.isdir(workspace_path):
            return {
                'success': False,
                'result': {'error': f'工作空间不存在: {workspace_path}', 'missing_files': [], 'empty_files': []}
            }

        # 构建待校验文件清单
        target_files = []
        for rel_path in COMMON_FILES:
            target_files.append(rel_path)
        for rel_path in PACKAGE_FILES:
            target_files.append(rel_path.replace('{N}', package))

        # 加入 metadata.json 和 Supplementary_info.md
        target_files.append('metadata.json')
        target_files.append('Supplementary_info.md')

        existing_files = []
        missing_files = []
        empty_files = []

        for rel_path in target_files:
            abs_path = os.path.join(workspace_path, rel_path)
            if not os.path.exists(abs_path):
                missing_files.append(rel_path)
            elif os.path.getsize(abs_path) == 0:
                empty_files.append(rel_path)
            else:
                existing_files.append(rel_path)

        # 读取 metadata.json 关键字段
        metadata = {}
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    raw_metadata = json.load(f)
                metadata = {
                    '预期总字数': raw_metadata.get('预期总字数', ''),
                    '采购方式': raw_metadata.get('采购方式', ''),
                    '当前需撰写标段': raw_metadata.get('当前需撰写标段', ''),
                }
            except Exception as e:
                metadata = {'error': f'读取 metadata.json 失败: {str(e)}'}

        success = len(missing_files) == 0 and len(empty_files) == 0
        return {
            'success': success,
            'result': {
                'files': existing_files,
                'missing_files': missing_files,
                'empty_files': empty_files,
                'metadata': metadata
            }
        }

    # ==========================================================
    # 2. validate_outline_structure：验证 outline.json 结构完整性
    # ==========================================================

    def validate_outline_structure(self, workspace_path: str) -> dict:
        """
        验证 outline.json 结构完整性

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 校验结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'valid': False,
                'errors': [f'outline.json 不存在: {outline_path}'],
                'warnings': [],
                'stats': {}
            }

        # 1. JSON 格式有效性
        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except json.JSONDecodeError as e:
            # 提供详细的 JSON 语法错误信息，包括位置和问题描述
            error_detail = []
            if e.lineno:
                error_detail.append(f'行号: {e.lineno}')
            if e.colno:
                error_detail.append(f'列号: {e.colno}')
            if e.msg:
                error_detail.append(f'错误描述: {e.msg}')
            if e.doc:
                # 显示错误位置附近的代码片段
                lines = e.doc.split('\n')
                if e.lineno and 0 < e.lineno <= len(lines):
                    context_line = lines[e.lineno - 1].strip()
                    if context_line:
                        error_detail.append(f'错误行内容: "{context_line}"')
            
            error_msg = f'outline.json JSON 语法错误: {e}\n'
            if error_detail:
                error_msg += '详细信息:\n  ' + '\n  '.join(error_detail)
            
            return {
                'success': False,
                'valid': False,
                'errors': [error_msg],
                'warnings': [],
                'stats': {}
            }
        except Exception as e:
            return {
                'success': False,
                'valid': False,
                'errors': [f'读取 outline.json 失败: {str(e)}'],
                'warnings': [],
                'stats': {}
            }

        errors = []
        warnings = []

        # 收集所有节点信息
        all_nodes = []
        node_ids = []
        leaf_nodes = []
        total_word_count = 0
        total_charts = 0

        def collect_nodes(node, parent_level=None, parent_id=None):
            """递归收集节点信息"""
            nonlocal total_word_count, total_charts
            if not isinstance(node, dict):
                errors.append(f'节点格式错误（非对象）: parent_id={parent_id}')
                return

            title = node.get('title', '')
            level = node.get('level')
            node_id = node.get('node_id', '')
            write_content = node.get('write_content')
            children = node.get('children', [])

            all_nodes.append(node)
            if node_id:
                node_ids.append(node_id)

            # 2. 层级关系正确性
            if level is None or not isinstance(level, int):
                errors.append(f'节点 [{node_id}] level 缺失或非整数')
            else:
                if level < 1 or level > 5:
                    errors.append(f'节点 [{node_id}] level={level} 超出范围（1~5）')
                if parent_level is not None and level != parent_level + 1:
                    errors.append(
                        f'节点 [{node_id}] level={level} 与父节点 level={parent_level} 关系不正确'
                    )

            # 3. node_id 必填
            if not node_id:
                errors.append(f'节点 [title={title}] 缺少 node_id')

            # 4. write_content 必填
            if write_content is None:
                errors.append(f'节点 [{node_id}] 缺少 write_content 字段')
                write_content = False  # 容错继续

            # 5. write_content 与 children 一致性
            if write_content is False:
                if not children:
                    if level and level > 1:
                        warnings.append(
                            f'节点 [{node_id}] write_content=false 但无 children（非叶子节点应有子节点）'
                        )
            else:  # write_content is True
                if children:
                    errors.append(
                        f'节点 [{node_id}] write_content=true 但存在 children（叶子节点不应有子节点）'
                    )
                # 收集叶子节点统计
                leaf_nodes.append(node)
                word_count = node.get('word_count')
                if word_count is not None:
                    total_word_count += word_count
                # 图表统计
                if node.get('generate_chart'):
                    # chart_count 字段为可选：缺失时从 charts 数组长度推导，不报错
                    # 仅当字段显式存在且与 charts 数组长度不一致时，记为警告（非错误）
                    has_explicit_chart_count = 'chart_count' in node
                    chart_count = node.get('chart_count', 0)
                    charts = node.get('charts', [])
                    total_charts += len(charts)
                    # 6. chart_count 与 charts 数组长度一致性（仅显式存在时校验，且降为警告）
                    if has_explicit_chart_count and chart_count != len(charts):
                        warnings.append(
                            f'节点 [{node_id}] chart_count={chart_count} 与 charts 数组长度={len(charts)} 不一致（建议省略 chart_count 字段，由 charts 数组长度自动推导）'
                        )
                    # 校验每个图表的 chart_id 格式
                    for idx, chart in enumerate(charts):
                        if not isinstance(chart, dict):
                            errors.append(f'节点 [{node_id}] charts[{idx}] 格式错误（非对象）')
                            continue
                        chart_id = chart.get('chart_id', '')
                        if not chart_id:
                            errors.append(f'节点 [{node_id}] charts[{idx}] 缺少 chart_id')
                        # chart_id 格式：<node_id>_c<序号>
                        expected_prefix = f'{node_id}_c'
                        if not chart_id.startswith(expected_prefix):
                            warnings.append(
                                f'节点 [{node_id}] charts[{idx}] chart_id={chart_id} 不符合命名规则（应为 {expected_prefix}<序号>）'
                            )
                        if not chart.get('chart_title'):
                            warnings.append(f'节点 [{node_id}] charts[{idx}] 缺少 chart_title')
                        if not chart.get('chart_type'):
                            warnings.append(f'节点 [{node_id}] charts[{idx}] 缺少 chart_type')

            # 7. word_count 范围校验（仅叶子节点）
            if write_content is True:
                word_count = node.get('word_count')
                if word_count is None:
                    warnings.append(f'节点 [{node_id}] 缺少 word_count 字段，将使用默认值 {DEFAULT_WORD_COUNT}')
                elif not isinstance(word_count, int):
                    warnings.append(f'节点 [{node_id}] word_count 非整数: {word_count}')
                elif word_count < MIN_WORD_COUNT or word_count > MAX_WORD_COUNT:
                    warnings.append(
                        f'节点 [{node_id}] word_count={word_count} 超出常规范围（{MIN_WORD_COUNT}~{MAX_WORD_COUNT}），'
                        f'请确认是否为极端情况'
                    )

            # 8. content_range 必填
            if not node.get('content_range'):
                if level and level > 1:
                    warnings.append(f'节点 [{node_id}] 缺少 content_range 字段')

            # 递归处理子节点
            for child in children:
                collect_nodes(child, level, node_id)

        # 从根节点开始遍历
        collect_nodes(outline)

        # 9. node_id 唯一性
        duplicate_ids = [nid for nid in node_ids if node_ids.count(nid) > 1]
        if duplicate_ids:
            unique_duplicates = list(set(duplicate_ids))
            errors.append(f'node_id 重复: {unique_duplicates}')

        # 10. 根节点校验
        if not outline.get('node_id') == '1':
            warnings.append(f'根节点 node_id 应为 "1"，当前为 "{outline.get("node_id")}"')
        if outline.get('level') != 1:
            warnings.append(f'根节点 level 应为 1，当前为 {outline.get("level")}')
        if outline.get('write_content') is not False:
            errors.append('根节点 write_content 必须为 false')

        # 11. 字数分配合理性
        expected_word_count = 0
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                expected_str = metadata.get('预期总字数', '0')
                expected_word_count = int(expected_str) if str(expected_str).isdigit() else 0
            except Exception:
                pass

        if expected_word_count > 0 and total_word_count < expected_word_count:
            errors.append(
                f'叶子节点总字数 {total_word_count} 小于预期总字数 {expected_word_count}'
            )

        stats = {
            'total_nodes': len(all_nodes),
            'leaf_nodes': len(leaf_nodes),
            'total_word_count': total_word_count,
            'expected_word_count': expected_word_count,
            'chart_count': total_charts
        }

        valid = len(errors) == 0
        return {
            'success': True,
            'valid': valid,
            'errors': errors,
            'warnings': warnings,
            'stats': stats
        }

    # ==========================================================
    # 3. generate_outline_md：根据 outline.json 生成 outline.md
    # ==========================================================

    def generate_outline_md(self, workspace_path: str) -> dict:
        """
        根据 outline.json 生成人类可读的 Markdown 格式大纲

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 生成结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        outline_md_path = os.path.join(workspace_path, 'proposal_file', 'outline.md')

        if not os.path.exists(outline_path):
            return {
                'success': False,
                'outline_md_path': '',
                'error': f'outline.json 不存在: {outline_path}'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'outline_md_path': '',
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 生成 Markdown 内容
        lines = []
        leaf_count = 0
        total_word_count = 0
        chart_total = 0

        def render_node(node):
            nonlocal leaf_count, total_word_count, chart_total
            if not isinstance(node, dict):
                return

            title = node.get('title', '')
            level = node.get('level', 1)
            node_id = node.get('node_id', '')
            content_range = node.get('content_range', '')
            write_content = node.get('write_content', False)
            children = node.get('children', [])

            # 输出标题行
            heading_prefix = '#' * level
            lines.append(f'{heading_prefix} {title}')

            # 输出元数据行
            meta_parts = [f'节点ID：{node_id}']
            if content_range:
                meta_parts.append(f'内容范围：{content_range}')
            meta_parts.append(f'撰写正文：{"是" if write_content else "否"}')

            if write_content:
                content_plan = node.get('content_plan', '')
                word_count = node.get('word_count', 0)
                generate_chart = node.get('generate_chart', False)

                if content_plan:
                    meta_parts.append(f'内容规划：{content_plan}')
                if word_count:
                    meta_parts.append(f'正文字数：{word_count}')
                meta_parts.append(f'生成图表：{"是" if generate_chart else "否"}')

                if generate_chart:
                    charts = node.get('charts', [])
                    chart_count = node.get('chart_count', len(charts))
                    meta_parts.append(f'图表数量：{chart_count}')

                lines.append(f' - （{"、".join(meta_parts)}）')

                # 输出图表明细
                if generate_chart and charts:
                    for idx, chart in enumerate(charts, 1):
                        chart_title = chart.get('chart_title', '')
                        chart_type = chart.get('chart_type', '')
                        lines.append(f' - 图表{idx}：{chart_title}（{chart_type}）')

                # 统计
                leaf_count += 1
                if isinstance(word_count, int):
                    total_word_count += word_count
                if generate_chart:
                    chart_total += len(charts)
            else:
                lines.append(f' - （{"、".join(meta_parts)}）')

            # 递归处理子节点
            for child in children:
                render_node(child)

        render_node(outline)

        # 写入文件
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(outline_md_path), exist_ok=True)
            with open(outline_md_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        except Exception as e:
            return {
                'success': False,
                'outline_md_path': '',
                'error': f'写入 outline.md 失败: {str(e)}'
            }

        return {
            'success': True,
            'outline_md_path': outline_md_path,
            'stats': {
                'leaf_nodes': leaf_count,
                'total_word_count': total_word_count,
                'chart_count': chart_total
            }
        }

    # ==========================================================
    # 4. generate_directory_structure：生成 proposal_file 目录结构
    # ==========================================================

    def _sanitize_filename(self, filename: str) -> str:
        """
        清理文件名中的非法字符，确保文件名在 Windows/Linux 系统中有效
        
        Args:
            filename: 原始文件名
            
        Returns:
            str: 清理后的文件名
        """
        illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename

    def generate_directory_structure(self, workspace_path: str) -> dict:
        """
        根据 outline.json 生成 proposal_file 目录结构

        生成包含层级关系的目录文件夹结构，在对应目录文件夹内存放.md文件：
        - 目录文件夹命名格式："{node_id}_{title}"（例如"1_1_整体项目理解"）
        - .md文件命名格式："{node_id}_{title}.md"（例如"1_1_1_需求分析.md"）
        - .md文件内容：自动添加对应层级标题（例如"### 需求分析"）

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 生成结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        proposal_dir = os.path.join(workspace_path, 'proposal_file')

        if not os.path.exists(outline_path):
            return {
                'success': False,
                'proposal_dir': proposal_dir,
                'created_files': [],
                'created_dirs': [],
                'total_nodes': 0,
                'error': f'outline.json 不存在: {outline_path}'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'proposal_dir': proposal_dir,
                'created_files': [],
                'created_dirs': [],
                'total_nodes': 0,
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 创建根目录
        os.makedirs(proposal_dir, exist_ok=True)
        created_files = []
        created_dirs = []

        def create_node_structure(node, parent_path: str):
            """递归创建目录结构和文件"""
            if not isinstance(node, dict):
                return

            node_id = node.get('node_id', '')
            title = node.get('title', '')
            level = node.get('level', 1)
            write_content = node.get('write_content', False)
            children = node.get('children', [])

            # 清理标题，用于文件名
            sanitized_title = self._sanitize_filename(title)

            # 构建当前节点的目录路径（仅用于非叶子节点）
            node_dir_path = parent_path
            if node_id != '1' and sanitized_title:
                node_dir_name = f'{node_id}_{sanitized_title}'
                node_dir_path = os.path.join(parent_path, node_dir_name)

            # 创建目录（仅非叶子节点创建目录）
            if node_id != '1' and not write_content:  # 根节点和叶子节点不创建目录
                try:
                    os.makedirs(node_dir_path, exist_ok=True)
                    created_dirs.append(node_dir_path)
                except Exception:
                    pass

            # 如果是叶子节点（write_content=true），创建.md文件
            if write_content and node_id and sanitized_title:
                # 文件命名格式：{node_id}_{title}.md
                file_name = f'{node_id}_{sanitized_title}.md'
                # 文件直接放在父目录下
                file_path = os.path.join(parent_path, file_name)

                # 仅在文件不存在时创建（避免覆盖已有内容）
                if not os.path.exists(file_path):
                    try:
                        # 生成标题内容：标题层级与大纲中的层级对应
                        heading_prefix = '#' * level
                        content = f'{heading_prefix} {title}\n'
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        created_files.append(file_path)
                    except Exception:
                        pass

            # 递归处理子节点
            # 子节点的父路径是当前节点的目录路径
            for child in children:
                if node_id == '1':
                    # 根节点的子节点直接在proposal_dir下创建
                    create_node_structure(child, proposal_dir)
                elif write_content:
                    # 叶子节点不应该有子节点，容错处理
                    create_node_structure(child, parent_path)
                else:
                    # 非叶子节点的子节点在当前节点目录下创建
                    create_node_structure(child, node_dir_path)

        # 从根节点开始创建结构
        create_node_structure(outline, proposal_dir)

        return {
            'success': True,
            'proposal_dir': proposal_dir,
            'created_files': created_files,
            'created_dirs': created_dirs,
            'total_nodes': len(created_files)
        }

    # ==========================================================
    # 5. update_metadata_status：更新 metadata.json 项目状态
    # ==========================================================

    def update_metadata_status(self, workspace_path: str, status: str = '大纲确认完成') -> dict:
        """
        更新 metadata.json 的项目状态字段，并更新状态更新时间

        Args:
            workspace_path: 工作空间路径
            status: 项目状态值

        Returns:
            dict: 更新结果
        """
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {}
            metadata['项目状态'] = status
            metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            return {
                'success': True,
                'status': status,
                'updated_fields': ['项目状态', '状态更新时间']
            }
        except Exception as e:
            return {'success': False, 'error': f'更新 metadata.json 失败: {str(e)}'}


# ==========================================================
# 便捷函数（供主控 Agent 直接调用）
# ==========================================================

def read_input_files(workspace_path: str, package: str) -> dict:
    """校验所有输入文件存在性"""
    skill = OutlineWritingSkill()
    return skill.read_input_files(workspace_path, package)


def validate_outline_structure(workspace_path: str) -> dict:
    """验证 outline.json 结构完整性"""
    skill = OutlineWritingSkill()
    return skill.validate_outline_structure(workspace_path)


def generate_outline_md(workspace_path: str) -> dict:
    """根据 outline.json 生成 outline.md"""
    skill = OutlineWritingSkill()
    return skill.generate_outline_md(workspace_path)


def generate_directory_structure(workspace_path: str) -> dict:
    """根据 outline.json 生成 proposal_file 目录结构"""
    skill = OutlineWritingSkill()
    return skill.generate_directory_structure(workspace_path)


def update_metadata_status(workspace_path: str, status: str = '大纲确认完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = OutlineWritingSkill()
    return skill.update_metadata_status(workspace_path, status)


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
