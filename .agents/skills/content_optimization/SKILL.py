#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - 内容优化 Skill 执行脚本（阶段七）

功能：
1. 读取优化输入（审查报告、AI 审查结果、正文、大纲等）（read_optimization_inputs）
2. 按节点分组问题，避免写冲突（group_issues_by_node）
3. 执行二次验证，复用阶段六能力（run_revalidation）
4. 生成优化报告，追加模式（generate_optimization_report）
5. 锁定正文文件（lock_proposal_files）
6. 检查用户反馈是否涉及大纲结构变更（check_outline_structure_change）
7. 按节点分组用户反馈（group_user_feedback）
8. 更新项目状态（update_metadata_status）
9. 获取优化状态，支持中断恢复（get_optimization_status）
10. 更新优化轮次（update_optimization_round）
11. 识别失败优化任务（check_failed_optimizations）
12. 管理优化重试计数（update_optimization_retry_count）

注意：
- 优化执行（内容重写、图表修正等）由 optimizer-agent 完成，本脚本无智能逻辑
- 二次验证复用阶段六的 script_review 和 reviewer-agent，不重新实现审查逻辑
- 通过 importlib 动态加载阶段六 SKILL.py，避免 .agents 目录导入限制
"""

import os
import sys
import json
import re
import importlib.util
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

# 优化最大重试次数（单个节点）
OPTIMIZER_MAX_RETRY = 2

# 优化最大轮次（含首轮自动优化）
MAX_OPTIMIZATION_ROUNDS = 3

# 问题级别
ISSUE_LEVELS = {
    'serious': '严重问题',
    'general': '一般问题',
    'suggestion': '建议性问题'
}

# 审查维度映射（与阶段六一致）
REVIEW_DIMENSION_MAP = {
    'content_completeness': '内容完整性',
    'scoring_response': '评分点响应',
    'technical_language': '技术与语言规范',
    'word_count': '字数符合度',
    'chart': '图表正确性',
    'structure': '章节结构'
}

# 大纲结构变更关键词（用于 check_outline_structure_change）
OUTLINE_CHANGE_KEYWORDS = {
    'add': ['新增', '增加章节', '添加章节', '补充章节', '新增章节', '增加一节', '加一节'],
    'delete': ['删除', '移除', '去掉章节', '删除章节', '去掉一节', '删掉'],
    'rename': ['修改标题', '重命名', '改名', '修改章节名称', '调整标题', '改标题'],
    'move': ['移动', '调整位置', '调整顺序', '调整结构', '调整层级', '提升层级',
             '降低层级', '改为子章节', '提升为', '调整为子章节', '改为同级']
}


class ContentOptimizationSkill:
    """
    内容优化 Skill - 阶段七辅助工具

    为主控 Agent 提供优化输入读取、问题分组、二次验证调度、优化报告生成、
    文件锁定、用户反馈处理、项目状态更新、优化状态管理等能力。

    优化执行由 optimizer-agent 完成，本脚本不负责智能逻辑。
    二次验证复用阶段六的 script_review 和 reviewer-agent。
    """

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))
        self._review_skill_module = None

    # ==========================================================
    # 辅助方法
    # ==========================================================

    def _load_review_skill(self):
        """
        动态加载 review_optimization SKILL 模块（复用阶段六能力）

        通过 importlib.util 加载，绕过 .agents 目录的相对导入限制。
        加载失败返回 None，调用方需处理 None 情况。
        """
        if self._review_skill_module is not None:
            return self._review_skill_module

        review_skill_path = os.path.join(
            self.skill_root, '..', 'review_optimization', 'SKILL.py'
        )
        review_skill_path = os.path.abspath(review_skill_path)
        if not os.path.exists(review_skill_path):
            return None

        try:
            spec = importlib.util.spec_from_file_location(
                "review_optimization_skill", review_skill_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._review_skill_module = module
            return module
        except Exception:
            return None

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

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename

    def _collect_proposal_md_files(self, workspace_path: str) -> list:
        """收集 proposal_file 目录下所有正文 .md 文件（排除 outline.md 和 summary_report.md）"""
        proposal_dir = os.path.join(workspace_path, 'proposal_file')
        md_files = []
        if not os.path.isdir(proposal_dir):
            return md_files
        for root, dirs, files in os.walk(proposal_dir):
            for file in files:
                if file.endswith('.md') and file not in ('outline.md', 'summary_report.md'):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, workspace_path)
                    md_files.append({
                        'abs_path': abs_path,
                        'rel_path': rel_path,
                        'filename': file
                    })
        return md_files

    def _collect_ai_review_issues(self, workspace_path: str) -> list:
        """
        从 review_file/ai_review_*.json 文件收集 AI 审查问题

        兼容两种格式：
        1. 标准 review_results 数组格式
        2. 扩展 node_reviews 数组格式（每个节点含 issues 子数组）
        """
        review_dir = os.path.join(workspace_path, 'review_file')
        issues = []

        # AI 审查文件名后缀到 review_type 的映射
        ai_review_files = {
            'ai_review_content.json': 'content_completeness',
            'ai_review_scoring.json': 'scoring_response',
            'ai_review_language.json': 'technical_language',
        }

        if not os.path.isdir(review_dir):
            return issues

        for filename, review_type in ai_review_files.items():
            file_path = os.path.join(review_dir, filename)
            if not os.path.exists(file_path):
                continue
            try:
                if os.path.getsize(file_path) == 0:
                    continue
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if not content:
                    continue
                result = json.loads(content)

                # 格式1：标准 review_results 数组
                review_results = result.get('review_results', [])
                for issue in review_results:
                    if not isinstance(issue, dict):
                        continue
                    issue.setdefault('source', review_type)
                    issue.setdefault('dimension', review_type)
                    if 'level' not in issue:
                        issue['level'] = 'general'
                    issues.append(issue)

                # 格式2：扩展 node_reviews 数组（每个节点含 issues 子数组）
                node_reviews = result.get('node_reviews', [])
                for node_review in node_reviews:
                    if not isinstance(node_review, dict):
                        continue
                    node_id = node_review.get('node_id', '')
                    node_title = node_review.get('title', '')
                    node_issues = node_review.get('issues', [])
                    for issue in node_issues:
                        if not isinstance(issue, dict):
                            continue
                        issue.setdefault('node_id', node_id)
                        issue.setdefault('node_title', node_title)
                        issue.setdefault('source', review_type)
                        issue.setdefault('dimension', review_type)
                        if 'level' not in issue:
                            issue['level'] = 'general'
                        issues.append(issue)
            except (json.JSONDecodeError, Exception):
                # 解析失败跳过该文件
                continue

        return issues

    def _deduplicate_issues(self, issues: list) -> list:
        """
        同节点去重：相同问题描述的问题合并为一个

        去重依据：node_id + description 的相似度（简化为完全匹配）
        """
        seen = set()
        deduped = []
        for issue in issues:
            node_id = issue.get('node_id', '')
            description = issue.get('description', '')
            key = (node_id, description)
            if key not in seen:
                seen.add(key)
                deduped.append(issue)
        return deduped

    # ==========================================================
    # 1. read_optimization_inputs：读取优化输入
    # ==========================================================

    def read_optimization_inputs(self, workspace_path: str) -> dict:
        """
        读取优化输入文件，并收集审查问题列表

        读取文件列表：
        - review_file/optimization_suggestions.md（阶段六审查报告，主输入）
        - review_file/ai_review_*.json（AI 审查结果，3 个文件）
        - proposal_file/outline.json（大纲结构）
        - proposal_file/*.md（所有正文文件）
        - proposal_file/summary_report.md（阶段五撰写报告）
        - extraction_file/packages_file/package_N/07_Evaluation_Criteria.md
        - extraction_file/packages_file/package_N/09_Technical_Requirements.md
        - metadata.json（项目元数据）

        本函数同时复用阶段六的 collect_review_results 收集审查问题列表，
        并兼容 ai_review_*.json 的扩展 node_reviews 格式。

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 读取结果，含 files / missing_files / issues / metadata 等
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
            'review_file/optimization_suggestions.md',
            'review_file/ai_review_content.json',
            'review_file/ai_review_scoring.json',
            'review_file/ai_review_language.json',
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
        md_files = self._collect_proposal_md_files(workspace_path)
        if not md_files:
            missing_files.append('proposal_file/*.md (正文文件)')
        else:
            for md in md_files:
                existing_files.append(md['rel_path'])

        # 收集审查问题列表
        issues = []

        # 方式1：复用阶段六的 collect_review_results
        review_module = self._load_review_skill()
        if review_module is not None:
            try:
                collect_result = review_module.collect_review_results(workspace_path)
                if collect_result.get('success'):
                    review_issues = collect_result.get('review_results', [])
                    issues.extend(review_issues)
            except Exception:
                pass

        # 方式2：直接解析 ai_review_*.json（兼容 node_reviews 扩展格式）
        # collect_review_results 仅识别 review_results 字段，扩展格式需单独解析
        ai_issues = self._collect_ai_review_issues(workspace_path)
        # 合并去重（避免与方式1重复）
        existing_keys = set(
            (i.get('node_id', ''), i.get('description', '')) for i in issues
        )
        for issue in ai_issues:
            key = (issue.get('node_id', ''), issue.get('description', ''))
            if key not in existing_keys:
                issues.append(issue)
                existing_keys.add(key)

        # 整理 metadata 关键字段
        metadata_brief = {
            '预期总字数': metadata.get('预期总字数', ''),
            '采购方式': metadata.get('采购方式', ''),
            '当前需撰写标段': metadata.get('当前需撰写标段', ''),
            '项目状态': metadata.get('项目状态', ''),
            'optimization_round': metadata.get('optimization_round', 0),
            'proposal_files_locked': metadata.get('proposal_files_locked', False)
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
                'md_files': [md['rel_path'] for md in md_files],
                'issues': issues,
                'issues_count': len(issues)
            }
        }

    # ==========================================================
    # 2. group_issues_by_node：按节点分组问题
    # ==========================================================

    def group_issues_by_node(self, issues: list = None, workspace_path: str = None) -> dict:
        """
        按节点分组问题，避免写冲突，并按批次划分

        分组算法：
        1. 按 node_id 分组
        2. 同节点去重（相同问题描述合并）
        3. 按批次划分：
           - 含严重问题的节点 → batch_1_serious
           - 仅含一般问题的节点 → batch_2_general
           - 仅含建议性问题的节点 → batch_3_suggestion

        Args:
            issues: 审查问题列表（可选，未提供时从 workspace_path 读取）
            workspace_path: 工作空间路径（issues 为 None 时使用）

        Returns:
            dict: 分组结果，含 batch_1_serious / batch_2_general / batch_3_suggestion
        """
        # 如果未提供 issues，则从工作空间读取
        if issues is None:
            if workspace_path is None:
                return {
                    'success': False,
                    'error': '必须提供 issues 或 workspace_path 参数'
                }
            read_result = self.read_optimization_inputs(workspace_path)
            result_data = read_result.get('result', {})
            # 即使部分文件缺失（success=false），只要收集到 issues 即可继续
            # 但如果 result 本身不存在（工作空间不存在等严重错误），则报错
            if not result_data:
                return {
                    'success': False,
                    'error': f'读取优化输入失败: {read_result.get("error", "未知错误")}'
                }
            issues = result_data.get('issues', [])
            # 记录缺失文件信息（供调用方参考，不阻断流程）
            missing_files = result_data.get('missing_files', [])

        if not issues:
            return {
                'success': True,
                'grouped': {
                    'batch_1_serious': [],
                    'batch_2_general': [],
                    'batch_3_suggestion': []
                },
                'summary': {
                    'total_nodes': 0,
                    'serious_nodes': 0,
                    'general_nodes': 0,
                    'suggestion_nodes': 0,
                    'total_issues': 0
                },
                'note': '无审查问题，无需优化'
            }

        # 按 node_id 分组
        grouped_by_node = {}
        for issue in issues:
            node_id = issue.get('node_id', '')
            if not node_id:
                # 无 node_id 的问题归入 unknown 节点
                node_id = 'unknown'
            if node_id not in grouped_by_node:
                grouped_by_node[node_id] = {
                    'node_id': node_id,
                    'node_title': issue.get('node_title', ''),
                    'issues': []
                }
            grouped_by_node[node_id]['issues'].append(issue)

        # 同节点去重
        for node_id, node_data in grouped_by_node.items():
            node_data['issues'] = self._deduplicate_issues(node_data['issues'])

        # 按批次划分
        batch_1_serious = []   # 含严重问题的节点
        batch_2_general = []   # 仅含一般问题的节点
        batch_3_suggestion = []  # 仅含建议性问题的节点

        for node_id, node_data in grouped_by_node.items():
            levels = set()
            for issue in node_data['issues']:
                level = issue.get('level', 'suggestion').lower()
                levels.add(level)

            if 'serious' in levels:
                batch_1_serious.append(node_data)
            elif 'general' in levels:
                batch_2_general.append(node_data)
            else:
                batch_3_suggestion.append(node_data)

        # 按节点 ID 排序，保证顺序稳定
        batch_1_serious.sort(key=lambda x: x['node_id'])
        batch_2_general.sort(key=lambda x: x['node_id'])
        batch_3_suggestion.sort(key=lambda x: x['node_id'])

        total_issues = sum(
            len(n['issues']) for n in
            batch_1_serious + batch_2_general + batch_3_suggestion
        )

        return {
            'success': True,
            'grouped': {
                'batch_1_serious': batch_1_serious,
                'batch_2_general': batch_2_general,
                'batch_3_suggestion': batch_3_suggestion
            },
            'summary': {
                'total_nodes': len(batch_1_serious) + len(batch_2_general) + len(batch_3_suggestion),
                'serious_nodes': len(batch_1_serious),
                'general_nodes': len(batch_2_general),
                'suggestion_nodes': len(batch_3_suggestion),
                'total_issues': total_issues
            }
        }

    # ==========================================================
    # 3. run_revalidation：执行二次验证（复用阶段六能力）
    # ==========================================================

    def run_revalidation(self, workspace_path: str, round: int = 1,
                         target_node_ids: list = None) -> dict:
        """
        执行二次验证，复用阶段六的脚本审查和 AI 审查调度能力

        实现方式：
        1. 脚本审查：调用阶段六的 script_review 函数
        2. AI 审查：调用阶段六的 plan_ai_review_tasks 规划任务，
           主控 Agent 据此调度 reviewer-agent 执行

        Args:
            workspace_path: 工作空间路径
            round: 优化轮次（1、2、3），用于在报告中标示
            target_node_ids: 可选，仅验证指定节点（用户反馈循环时使用）

        Returns:
            dict: 验证结果，含 script_results / ai_tasks / round
        """
        review_module = self._load_review_skill()
        if review_module is None:
            return {
                'success': False,
                'error': '无法加载阶段六 review_optimization SKILL 模块，二次验证不可用',
                'round': round,
                'script_results': None,
                'ai_tasks': []
            }

        # 1. 脚本审查（直接调用阶段六的函数）
        try:
            script_results = review_module.script_review(workspace_path)
        except Exception as e:
            return {
                'success': False,
                'error': f'脚本审查失败: {str(e)}',
                'round': round,
                'script_results': None,
                'ai_tasks': []
            }

        # 如指定了 target_node_ids，过滤脚本审查结果
        if target_node_ids and script_results.get('success'):
            filtered_issues = [
                issue for issue in script_results.get('review_results', [])
                if issue.get('node_id') in target_node_ids
            ]
            script_results['review_results'] = filtered_issues
            script_results['summary']['total_issues'] = len(filtered_issues)

        # 2. AI 审查任务规划（主控 Agent 据此调度 reviewer-agent）
        try:
            ai_plan = review_module.plan_ai_review_tasks(workspace_path)
            ai_tasks = ai_plan.get('recommended_tasks', [])
            ai_plan_detail = ai_plan.get('plan', {})
        except Exception:
            ai_tasks = []
            ai_plan_detail = {}

        # 3. 检查 AI 审查任务完成情况（中断恢复）
        try:
            ai_status = review_module.get_ai_review_status(workspace_path)
            ai_task_status = ai_status.get('task_status', {})
        except Exception:
            ai_task_status = {}

        return {
            'success': True,
            'round': round,
            'revalidation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'script_results': script_results,
            'ai_tasks': ai_tasks,
            'ai_plan_detail': ai_plan_detail,
            'ai_task_status': ai_task_status,
            'target_node_ids': target_node_ids,
            'note': (
                '主控 Agent 需根据 ai_tasks 调度 reviewer-agent 执行 AI 审查，'
                '完成后可再次调用本函数或 collect_review_results 收集结果'
            )
        }

    # ==========================================================
    # 4. generate_optimization_report：生成优化报告（追加模式）
    # ==========================================================

    def generate_optimization_report(self, workspace_path: str, round: int = 1,
                                     optimization_records: list = None) -> dict:
        """
        生成优化完成报告 optimization_report.md（追加模式）

        报告内容：
        - 优化完成时间、优化轮次
        - 优化概览（总问题数、已修复数、未修复数、新增问题数）
        - 优化执行记录（按节点列表，含修改前后对比摘要）
        - 二次验证结果（3 维度脚本审查 + 3 维度 AI 审查）
        - 未修复问题清单（需用户关注）

        追加模式：每轮优化追加一个章节，便于追溯所有优化历史。

        Args:
            workspace_path: 工作空间路径
            round: 优化轮次
            optimization_records: 优化执行记录列表（可选，由主控 Agent 提供）

        Returns:
            dict: 报告生成结果
        """
        review_dir = os.path.join(workspace_path, 'review_file')
        report_path = os.path.join(review_dir, 'optimization_report.md')

        try:
            os.makedirs(review_dir, exist_ok=True)
        except Exception as e:
            return {
                'success': False,
                'report_path': '',
                'error': f'创建 review_file 目录失败: {str(e)}'
            }

        # 收集当前问题情况
        read_result = self.read_optimization_inputs(workspace_path)
        current_issues = read_result.get('result', {}).get('issues', [])

        # 问题分级统计
        serious_count = len([i for i in current_issues if i.get('level', '').lower() == 'serious'])
        general_count = len([i for i in current_issues if i.get('level', '').lower() == 'general'])
        suggestion_count = len([i for i in current_issues if i.get('level', '').lower() == 'suggestion'])

        # 二次验证结果（脚本审查）
        script_summary = {'total_issues': 0, 'word_count_issues': 0, 'chart_issues': 0, 'structure_issues': 0}
        try:
            review_module = self._load_review_skill()
            if review_module is not None:
                script_result = review_module.script_review(workspace_path)
                if script_result.get('success'):
                    script_summary = script_result.get('summary', script_summary)
        except Exception:
            pass

        # 构建本轮报告内容
        round_label = '第一轮优化（自动优化）' if round == 1 else f'第{round}轮优化（用户反馈优化）'

        report_lines = []
        # 如果文件不存在或为空，添加总标题
        if not os.path.exists(report_path) or os.path.getsize(report_path) == 0:
            report_lines.append('# 内容优化报告')
            report_lines.append('')
            report_lines.append(f'**报告创建时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
            report_lines.append('')
            report_lines.append('---')
            report_lines.append('')

        report_lines.append(f'## {round_label}')
        report_lines.append('')
        report_lines.append(f'**优化完成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        report_lines.append(f'**优化轮次**：第 {round} 轮')
        report_lines.append('')

        # 优化概览
        report_lines.append('### 一、优化概览')
        report_lines.append('')
        report_lines.append(f'- 当前总问题数：{len(current_issues)} 个（严重 {serious_count} / 一般 {general_count} / 建议 {suggestion_count}）')
        report_lines.append(f'- 脚本审查问题数：{script_summary.get("total_issues", 0)} 个'
                            f'（字数 {script_summary.get("word_count_issues", 0)} / '
                            f'图表 {script_summary.get("chart_issues", 0)} / '
                            f'结构 {script_summary.get("structure_issues", 0)}）')
        report_lines.append('')

        # 优化执行记录
        report_lines.append('### 二、优化执行记录')
        report_lines.append('')
        if optimization_records:
            report_lines.append('| 节点ID | 节点标题 | 优化方式 | 修改内容摘要 |')
            report_lines.append('|--------|----------|----------|--------------|')
            for record in optimization_records:
                node_id = record.get('node_id', '')
                node_title = record.get('node_title', '')
                opt_method = record.get('method', '')
                summary = record.get('summary', '')
                report_lines.append(f'| {node_id} | {node_title} | {opt_method} | {summary} |')
            report_lines.append('')
        else:
            report_lines.append('（主控 Agent 未提供优化执行记录）')
            report_lines.append('')

        # 二次验证结果
        report_lines.append('### 三、二次验证结果')
        report_lines.append('')
        report_lines.append('#### 脚本审查（3 维度）')
        report_lines.append('')
        report_lines.append('| 审查维度 | 问题数 |')
        report_lines.append('|----------|--------|')
        report_lines.append(f'| 字数符合度 | {script_summary.get("word_count_issues", 0)} |')
        report_lines.append(f'| 图表正确性 | {script_summary.get("chart_issues", 0)} |')
        report_lines.append(f'| 章节结构 | {script_summary.get("structure_issues", 0)} |')
        report_lines.append('')

        # AI 审查结果（从 ai_review_*.json 读取）
        report_lines.append('#### AI 审查（3 维度）')
        report_lines.append('')
        ai_review_files = {
            '内容完整性': 'ai_review_content.json',
            '评分点响应': 'ai_review_scoring.json',
            '技术与语言规范': 'ai_review_language.json'
        }
        report_lines.append('| 审查维度 | 问题数 | 文件状态 |')
        report_lines.append('|----------|--------|----------|')
        for dim_name, filename in ai_review_files.items():
            file_path = os.path.join(review_dir, filename)
            issue_count = 0
            status = '未生成'
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        result = json.load(f)
                    # 兼容两种格式
                    if 'review_results' in result:
                        issue_count = len(result.get('review_results', []))
                    elif 'node_reviews' in result:
                        for nv in result.get('node_reviews', []):
                            issue_count += len(nv.get('issues', []))
                    status = '已生成'
                except Exception:
                    status = '格式错误'
            report_lines.append(f'| {dim_name} | {issue_count} | {status} |')
        report_lines.append('')

        # 未修复问题清单
        report_lines.append('### 四、当前问题清单')
        report_lines.append('')
        if current_issues:
            report_lines.append('| 节点ID | 节点标题 | 问题描述 | 问题级别 | 审查维度 |')
            report_lines.append('|--------|----------|----------|----------|----------|')
            # 按级别排序：严重 → 一般 → 建议
            sorted_issues = sorted(
                current_issues,
                key=lambda x: {'serious': 0, 'general': 1, 'suggestion': 2}.get(
                    x.get('level', 'suggestion').lower(), 3
                )
            )
            for issue in sorted_issues[:50]:  # 限制最多显示 50 条，避免报告过长
                node_id = issue.get('node_id', '')
                node_title = issue.get('node_title', '')
                description = issue.get('description', '')[:80]  # 截断长描述
                level = ISSUE_LEVELS.get(issue.get('level', '').lower(), issue.get('level', ''))
                dimension = REVIEW_DIMENSION_MAP.get(
                    issue.get('dimension', ''), issue.get('dimension', '')
                )
                report_lines.append(f'| {node_id} | {node_title} | {description} | {level} | {dimension} |')
            if len(current_issues) > 50:
                report_lines.append(f'| ... | ... |（共 {len(current_issues)} 条，仅显示前 50 条）| ... | ... |')
            report_lines.append('')
        else:
            report_lines.append('无未修复问题')
            report_lines.append('')

        report_lines.append('---')
        report_lines.append('')

        # 追加写入文件
        try:
            # 读取现有内容（追加模式）
            existing_content = ''
            if os.path.exists(report_path) and os.path.getsize(report_path) > 0:
                with open(report_path, 'r', encoding='utf-8') as f:
                    existing_content = f.read()

            new_content = '\n'.join(report_lines)
            # 如果已有内容，追加；否则新建
            if existing_content:
                # 检查是否已包含该轮次的章节（避免重复追加）
                round_header = f'## {round_label}'
                if round_header in existing_content:
                    # 替换该轮次章节
                    # 简化处理：直接追加，主控 Agent 应避免重复调用
                    pass
                full_content = existing_content.rstrip() + '\n\n' + new_content
            else:
                full_content = new_content

            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
        except Exception as e:
            return {
                'success': False,
                'report_path': '',
                'error': f'写入 optimization_report.md 失败: {str(e)}'
            }

        return {
            'success': True,
            'report_path': report_path,
            'round': round,
            'stats': {
                'total_issues': len(current_issues),
                'serious_count': serious_count,
                'general_count': general_count,
                'suggestion_count': suggestion_count,
                'script_issues': script_summary.get('total_issues', 0)
            }
        }

    # ==========================================================
    # 5. lock_proposal_files：锁定正文文件
    # ==========================================================

    def lock_proposal_files(self, workspace_path: str) -> dict:
        """
        锁定所有正文 .md 文件

        锁定机制：
        - 在 metadata.json 中添加 proposal_files_locked: true 字段
        - 在 metadata.json 中添加 lock_time 字段（锁定时间）
        - 锁定后，optimizer-agent 和后续阶段应拒绝修改正文 .md 文件
        - 阶段八（合并导出）会读取此字段判断是否可执行

        注意：锁定是逻辑层面的（通过 metadata.json 标记），
              不是文件系统层面的（不修改文件权限）。

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 锁定结果
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        # 检查是否已锁定
        if metadata.get('proposal_files_locked', False):
            return {
                'success': True,
                'result': {
                    'locked_files': [],
                    'lock_time': metadata.get('lock_time', ''),
                    'locked': True,
                    'note': '文件已处于锁定状态'
                }
            }

        # 收集所有正文 .md 文件
        md_files = self._collect_proposal_md_files(workspace_path)
        locked_files = [md['rel_path'] for md in md_files]
        lock_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 更新 metadata.json
        metadata['proposal_files_locked'] = True
        metadata['lock_time'] = lock_time
        metadata['状态更新时间'] = lock_time

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'result': {
                    'locked_files': locked_files,
                    'lock_time': lock_time,
                    'locked': True,
                    'locked_count': len(locked_files)
                }
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 6. check_outline_structure_change：检查大纲结构变更
    # ==========================================================

    def check_outline_structure_change(self, user_feedback: str = '',
                                       workspace_path: str = None) -> dict:
        """
        检查用户反馈是否涉及大纲结构变更

        判断依据（关键词识别）：
        - 用户要求新增/删除章节
        - 用户要求修改章节标题
        - 用户要求调整章节层级
        - 用户要求移动章节位置

        注意：本函数仅做关键词识别，复杂判断由主控 Agent 通过语义理解完成。

        Args:
            user_feedback: 用户反馈内容（自然语言）
            workspace_path: 工作空间路径（可选，用于读取大纲节点列表辅助判断）

        Returns:
            dict: 检查结果，含 involves_change / change_details / keywords_matched
        """
        if not user_feedback:
            return {
                'success': False,
                'error': 'user_feedback 参数不能为空'
            }

        feedback_lower = user_feedback.lower()
        change_details = []
        keywords_matched = []

        for change_type, keywords in OUTLINE_CHANGE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in user_feedback or keyword.lower() in feedback_lower:
                    keywords_matched.append(keyword)
                    change_details.append({
                        'type': change_type,
                        'keyword': keyword,
                        'description': f'用户反馈中检测到关键词「{keyword}」，可能涉及大纲{self._change_type_desc(change_type)}'
                    })

        # 如提供 workspace_path，尝试匹配节点信息
        matched_nodes = []
        if workspace_path:
            outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
            if os.path.exists(outline_path):
                try:
                    with open(outline_path, 'r', encoding='utf-8') as f:
                        outline = json.load(f)
                    # 收集所有节点
                    all_nodes = []
                    self._collect_all_nodes(outline, all_nodes)
                    # 在用户反馈中查找节点标题
                    for node in all_nodes:
                        title = node.get('title', '')
                        node_id = node.get('node_id', '')
                        if title and title in user_feedback:
                            matched_nodes.append({
                                'node_id': node_id,
                                'node_title': title
                            })
                except Exception:
                    pass

        involves_change = len(change_details) > 0

        return {
            'success': True,
            'involves_change': involves_change,
            'change_details': change_details,
            'keywords_matched': keywords_matched,
            'matched_nodes': matched_nodes,
            'note': (
                '本结果基于关键词识别，主控 Agent 应结合语义理解做最终判断'
                if involves_change else
                '未检测到结构变更关键词，主控 Agent 可直接整理为优化任务'
            )
        }

    def _change_type_desc(self, change_type: str) -> str:
        """变更类型描述映射"""
        return {
            'add': '新增章节',
            'delete': '删除章节',
            'rename': '修改标题',
            'move': '调整结构/位置'
        }.get(change_type, '结构变更')

    def _collect_all_nodes(self, node: dict, all_nodes: list):
        """递归收集所有节点（含非叶子节点）"""
        if not isinstance(node, dict):
            return
        all_nodes.append({
            'node_id': node.get('node_id', ''),
            'title': node.get('title', ''),
            'level': node.get('level', 1)
        })
        for child in node.get('children', []):
            self._collect_all_nodes(child, all_nodes)

    # ==========================================================
    # 7. group_user_feedback：按节点分组用户反馈
    # ==========================================================

    def group_user_feedback(self, user_feedback: str = '',
                            workspace_path: str = None) -> dict:
        """
        将用户反馈按节点分组

        分组逻辑：
        1. 如提供 workspace_path，读取 outline.json 获取节点列表
        2. 在用户反馈中匹配节点标题或 node_id
        3. 按 node_id 分组反馈内容
        4. 未明确指向节点的反馈归为"整体反馈"

        Args:
            user_feedback: 用户反馈内容（自然语言）
            workspace_path: 工作空间路径（用于读取大纲节点列表）

        Returns:
            dict: 分组后的反馈字典
        """
        if not user_feedback:
            return {
                'success': False,
                'error': 'user_feedback 参数不能为空'
            }

        grouped_feedback = {}
        overall_feedback = []

        # 简单分句处理
        # 按换行、句号、分号切分
        sentences = re.split(r'[。\n；;！!？?]', user_feedback)
        sentences = [s.strip() for s in sentences if s.strip()]

        # 如提供 workspace_path，读取大纲节点
        nodes_info = []
        if workspace_path:
            outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
            if os.path.exists(outline_path):
                try:
                    with open(outline_path, 'r', encoding='utf-8') as f:
                        outline = json.load(f)
                    all_nodes = []
                    self._collect_all_nodes(outline, all_nodes)
                    nodes_info = all_nodes
                except Exception:
                    pass

        # 对每个句子，尝试匹配节点
        for sentence in sentences:
            matched = False
            for node in nodes_info:
                title = node.get('title', '')
                node_id = node.get('node_id', '')
                if title and title in sentence:
                    if node_id not in grouped_feedback:
                        grouped_feedback[node_id] = {
                            'node_id': node_id,
                            'node_title': title,
                            'feedback_items': []
                        }
                    grouped_feedback[node_id]['feedback_items'].append(sentence)
                    matched = True
                    break  # 一个句子只匹配一个节点
            if not matched:
                overall_feedback.append(sentence)

        return {
            'success': True,
            'grouped_feedback': list(grouped_feedback.values()),
            'overall_feedback': overall_feedback,
            'total_feedback_items': len(sentences),
            'matched_nodes': len(grouped_feedback),
            'unmatched_items': len(overall_feedback)
        }

    # ==========================================================
    # 8. update_metadata_status：更新项目状态
    # ==========================================================

    def update_metadata_status(self, workspace_path: str,
                               status: str = '自动优化完成') -> dict:
        """
        更新 metadata.json 的「项目状态」字段，并更新「状态更新时间」和优化状态

        状态值：
        - 内容审查完成（阶段六结束）
        - 自动优化完成（阶段 7A 结束）
        - 审查优化全部完成（阶段 7B 结束，文件已锁定）

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

        # 同步更新优化状态
        updated_fields = ['项目状态', '状态更新时间']

        if status == '自动优化完成':
            metadata['optimization_status'] = 'auto_completed'
            updated_fields.append('optimization_status')
        elif status == '审查优化全部完成':
            metadata['optimization_status'] = 'completed'
            updated_fields.append('optimization_status')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'status': status,
                'updated_fields': updated_fields
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 9. get_optimization_status：获取优化状态（用于中断恢复）
    # ==========================================================

    def get_optimization_status(self, workspace_path: str) -> dict:
        """
        获取优化状态，支持中断恢复

        metadata.json 扩展字段：
        - optimization_round: 当前优化轮次（0=未开始, 1=第一轮, 2=第二轮, 3=第三轮）
        - optimization_status: pending/in_progress/auto_completed/user_reviewing/completed
        - optimization_start_time: 优化开始时间
        - optimization_completed_nodes: 已优化的节点列表
        - optimization_failed_nodes: 优化失败的节点列表
        - optimization_retry_counts: 重试计数 {node_id: count}
        - proposal_files_locked: 正文文件是否锁定
        - lock_time: 锁定时间
        - user_feedback_history: 用户反馈历史

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 优化状态信息
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {
                'success': False,
                'error': 'metadata.json 不存在或读取失败'
            }

        return {
            'success': True,
            'optimization_status': metadata.get('optimization_status', 'pending'),
            'optimization_round': metadata.get('optimization_round', 0),
            'optimization_start_time': metadata.get('optimization_start_time', ''),
            'optimization_completed_nodes': metadata.get('optimization_completed_nodes', []),
            'optimization_failed_nodes': metadata.get('optimization_failed_nodes', []),
            'optimization_retry_counts': metadata.get('optimization_retry_counts', {}),
            'proposal_files_locked': metadata.get('proposal_files_locked', False),
            'lock_time': metadata.get('lock_time', ''),
            'user_feedback_history': metadata.get('user_feedback_history', []),
            'project_status': metadata.get('项目状态', '')
        }

    # ==========================================================
    # 10. update_optimization_round：更新优化轮次
    # ==========================================================

    def update_optimization_round(self, workspace_path: str, round: int = 1) -> dict:
        """
        更新优化轮次

        每轮优化开始时调用本函数：
        - 更新 optimization_round 字段
        - 如为第一轮，设置 optimization_status 为 in_progress 并记录开始时间
        - 如为后续轮次（用户反馈循环），保持 optimization_status 为 in_progress

        Args:
            workspace_path: 工作空间路径
            round: 优化轮次（1、2、3）

        Returns:
            dict: 更新结果
        """
        if round < 1 or round > MAX_OPTIMIZATION_ROUNDS:
            return {
                'success': False,
                'error': f'优化轮次超出范围（1-{MAX_OPTIMIZATION_ROUNDS}）: {round}'
            }

        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        metadata['optimization_round'] = round
        metadata['optimization_status'] = 'in_progress'
        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 第一轮优化记录开始时间
        if round == 1 and not metadata.get('optimization_start_time'):
            metadata['optimization_start_time'] = metadata['状态更新时间']

        # 初始化已完成/失败节点列表（如不存在）
        if 'optimization_completed_nodes' not in metadata:
            metadata['optimization_completed_nodes'] = []
        if 'optimization_failed_nodes' not in metadata:
            metadata['optimization_failed_nodes'] = []
        if 'optimization_retry_counts' not in metadata:
            metadata['optimization_retry_counts'] = {}

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'round': round,
                'optimization_status': metadata['optimization_status'],
                'max_rounds': MAX_OPTIMIZATION_ROUNDS
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 11. check_failed_optimizations：识别失败优化任务
    # ==========================================================

    def check_failed_optimizations(self, workspace_path: str) -> dict:
        """
        识别失败的优化任务（用于中断恢复和重试编排）

        识别依据：
        1. metadata.json 中 optimization_failed_nodes 列表的节点
        2. 对比 optimization_completed_nodes，识别未完成的节点
        3. 重试次数未超过 OPTIMIZER_MAX_RETRY 的节点为可重试

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 失败优化任务识别结果
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {
                'success': False,
                'error': 'metadata.json 不存在或读取失败'
            }

        failed_nodes_raw = metadata.get('optimization_failed_nodes', [])
        retry_counts = metadata.get('optimization_retry_counts', {})

        failed_nodes = []
        retryable_nodes = []
        exhausted_nodes = []

        for node_id in failed_nodes_raw:
            retry_count = retry_counts.get(node_id, 0)
            can_retry = retry_count < OPTIMIZER_MAX_RETRY
            node_info = {
                'node_id': node_id,
                'retry_count': retry_count,
                'can_retry': can_retry,
                'max_retry': OPTIMIZER_MAX_RETRY
            }
            failed_nodes.append(node_info)
            if can_retry:
                retryable_nodes.append(node_id)
            else:
                exhausted_nodes.append(node_id)

        return {
            'success': True,
            'failed_nodes': failed_nodes,
            'retryable_nodes': retryable_nodes,
            'exhausted_nodes': exhausted_nodes,
            'summary': {
                'failed_count': len(failed_nodes),
                'retryable_count': len(retryable_nodes),
                'exhausted_count': len(exhausted_nodes)
            }
        }

    # ==========================================================
    # 12. update_optimization_retry_count：管理优化重试计数
    # ==========================================================

    def update_optimization_retry_count(self, workspace_path: str, node_id: str,
                                        increment: int = 1) -> dict:
        """
        更新优化任务的重试计数

        当 optimizer-agent 完成一次重试后调用本函数：
        - 如果重试成功，主控 Agent 应将节点从 optimization_failed_nodes 移除并加入 optimization_completed_nodes
        - 如果重试失败，调用本函数增加重试计数

        当 retry_count >= OPTIMIZER_MAX_RETRY 时，节点状态变更为 exhausted，需人工介入。

        Args:
            workspace_path: 工作空间路径
            node_id: 节点 ID
            increment: 增量（默认 1）

        Returns:
            dict: 更新结果
        """
        if not node_id:
            return {'success': False, 'error': 'node_id 参数不能为空'}

        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        retry_counts = metadata.get('optimization_retry_counts', {})
        retry_counts[node_id] = retry_counts.get(node_id, 0) + increment
        metadata['optimization_retry_counts'] = retry_counts

        current_count = retry_counts[node_id]
        status = 'exhausted' if current_count >= OPTIMIZER_MAX_RETRY else 'retry'

        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'node_id': node_id,
                'retry_count': current_count,
                'status': status,
                'max_retry': OPTIMIZER_MAX_RETRY
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}


# ==========================================================
# 便捷函数（供主控 Agent 直接调用 / 供 run_skill.py 调用）
# ==========================================================

def read_optimization_inputs(workspace_path: str) -> dict:
    """读取优化输入（审查报告、AI 审查结果、正文、大纲等）"""
    skill = ContentOptimizationSkill()
    return skill.read_optimization_inputs(workspace_path)


def group_issues_by_node(issues: list = None, workspace_path: str = None) -> dict:
    """按节点分组问题，避免写冲突"""
    skill = ContentOptimizationSkill()
    return skill.group_issues_by_node(issues, workspace_path)


def run_revalidation(workspace_path: str, round: int = 1,
                     target_node_ids: list = None) -> dict:
    """执行二次验证（复用阶段六能力）"""
    skill = ContentOptimizationSkill()
    return skill.run_revalidation(workspace_path, round, target_node_ids)


def generate_optimization_report(workspace_path: str, round: int = 1,
                                 optimization_records: list = None) -> dict:
    """生成优化完成报告（追加模式）"""
    skill = ContentOptimizationSkill()
    return skill.generate_optimization_report(workspace_path, round, optimization_records)


def lock_proposal_files(workspace_path: str) -> dict:
    """锁定所有正文 .md 文件"""
    skill = ContentOptimizationSkill()
    return skill.lock_proposal_files(workspace_path)


def check_outline_structure_change(user_feedback: str = '',
                                   workspace_path: str = None) -> dict:
    """检查用户反馈是否涉及大纲结构变更"""
    skill = ContentOptimizationSkill()
    return skill.check_outline_structure_change(user_feedback, workspace_path)


def group_user_feedback(user_feedback: str = '',
                        workspace_path: str = None) -> dict:
    """按节点分组用户反馈"""
    skill = ContentOptimizationSkill()
    return skill.group_user_feedback(user_feedback, workspace_path)


def update_metadata_status(workspace_path: str, status: str = '自动优化完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = ContentOptimizationSkill()
    return skill.update_metadata_status(workspace_path, status)


def get_optimization_status(workspace_path: str) -> dict:
    """获取优化状态（用于中断恢复）"""
    skill = ContentOptimizationSkill()
    return skill.get_optimization_status(workspace_path)


def update_optimization_round(workspace_path: str, round: int = 1) -> dict:
    """更新优化轮次"""
    skill = ContentOptimizationSkill()
    return skill.update_optimization_round(workspace_path, round)


def check_failed_optimizations(workspace_path: str) -> dict:
    """识别失败的优化任务"""
    skill = ContentOptimizationSkill()
    return skill.check_failed_optimizations(workspace_path)


def update_optimization_retry_count(workspace_path: str, node_id: str,
                                    increment: int = 1) -> dict:
    """更新优化任务重试计数（达到上限则标记为 exhausted 需人工介入）"""
    skill = ContentOptimizationSkill()
    return skill.update_optimization_retry_count(workspace_path, node_id, increment)
