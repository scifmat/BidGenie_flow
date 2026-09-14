# -*- coding: utf-8 -*-
"""
BidGenie Flow - 正文撰写 Skill 执行脚本

功能：
1. 读取大纲和所有撰写素材（read_outline_and_materials）
2. 根据 outline.json 构建撰写任务队列，处理依赖关系（build_task_queue）
3. 统计各章节字数，校验偏差（word_count_statistics）
4. 执行质量自查（quality_self_check）
5. 生成撰写完成报告（generate_summary_report）
6. 更新 metadata.json 项目状态（update_metadata_status）
7. 获取已完成节点列表（get_completed_nodes）
8. 更新已完成节点列表（update_completed_nodes）

注意：正文 .md 文件由 writer-agent 使用 Write 工具直接创建，本脚本不负责生成。
      本脚本仅负责文件操作、任务队列管理、字数统计、质量检查等机械操作，无智能逻辑。
"""

import os
import sys
import json
import re
from datetime import datetime


# ==========================================================
# 路径注入：解决 .agents 目录导入问题
# ==========================================================
# 将项目根目录注入 sys.path，以便导入 .trae/utils/temp_manager
_TRAE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.trae'))
if _TRAE_PATH not in sys.path:
    sys.path.insert(0, _TRAE_PATH)


# 字数偏差允许范围
# 策略变更：只下限不限上限
# - 字数不足（低于下限 -WORD_COUNT_LOWER_THRESHOLD）：标记为不合格，需补充
# - 字数超标（超过上限）：不限制，仅作记录（不再判为不合格）
WORD_COUNT_LOWER_THRESHOLD = 0.15  # 下限 -15%（字数不足 15% 以上为不合格）
WORD_COUNT_UPPER_THRESHOLD = None  # 上限不限制（None 表示不限制）

# 内容完整性覆盖率阈值
# 策略变更：降低关键词匹配阈值，引入语义检查兜底机制
CONTENT_COVERAGE_THRESHOLD = 0.50  # 50%（关键词匹配低于此阈值才告警）
# 触发语义检查的关键词覆盖率阈值（低于此值时建议主控 Agent 进行语义检查）
SEMANTIC_CHECK_TRIGGER_THRESHOLD = 0.80  # 80%（关键词覆盖率 50%-80% 时建议语义检查）

# 单节点字数范围
MIN_WORD_COUNT = 100
MAX_WORD_COUNT = 8000

# 最大并行 writer-agent 数量
MAX_PARALLEL_AGENTS = 3

# 检查点恢复：失败节点识别阈值
# - 文件不存在 → 标记为 failed
# - 文件存在但实际字数 < 计划字数 * FAILED_NODE_WORD_RATIO_THRESHOLD → 标记为 failed（严重不足）
# - 文件存在但实际字数 < MIN_FAILED_WORD_COUNT → 标记为 failed（绝对字数过少）
FAILED_NODE_WORD_RATIO_THRESHOLD = 0.50  # 字数少于计划 50% 视为失败节点
MIN_FAILED_WORD_COUNT = 50  # 实际字数少于 50 字视为失败节点

# 检查点恢复：最大重试次数
MAX_RETRY_COUNT = 2  # 失败节点最多重试 2 次，超过则需人工介入

# 正文撰写阶段需要读取的素材文件（相对路径模板）
COMMON_FILES_TO_READ = [
    'extraction_file/common_file/01_Basic_Information.md',
]

PACKAGE_FILES_TO_READ = [
    'extraction_file/packages_file/package_{N}/06_Procurement_Content.md',
    'extraction_file/packages_file/package_{N}/07_Evaluation_Criteria.md',
    'extraction_file/packages_file/package_{N}/08_Business_Requirements.md',
    'extraction_file/packages_file/package_{N}/09_Technical_Requirements.md',
]


class TechnicalWritingSkill:
    """
    正文撰写 Skill - 阶段五辅助工具

    为主控 Agent 提供大纲与素材读取、任务队列构建、字数统计、质量自查、
    撰写完成报告生成、项目状态更新、检查点管理等能力。
    正文 .md 文件由 writer-agent 直接创建，本脚本不负责生成。
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
        # 匹配 "标段1"、"标段 1"、"01"、"1" 等格式
        m = re.search(r'(\d+)', str(package))
        if m:
            return str(int(m.group(1)))
        return '1'

    # ==========================================================
    # 1. read_outline_and_materials：读取大纲和素材
    # ==========================================================

    def read_outline_and_materials(self, workspace_path: str) -> dict:
        """
        读取 outline.json 和对技术方案撰写有用的素材文件
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
        target_files = []
        # outline.json
        target_files.append('proposal_file/outline.json')
        # 公共信息文件
        for rel_path in COMMON_FILES_TO_READ:
            target_files.append(rel_path)
        # 标段专属文件
        for rel_path in PACKAGE_FILES_TO_READ:
            target_files.append(rel_path.replace('{N}', package_n))
        # 补充信息与元数据
        target_files.append('Supplementary_info.md')
        target_files.append('metadata.json')

        existing_files = []
        missing_files = []

        for rel_path in target_files:
            abs_path = os.path.join(workspace_path, rel_path)
            if os.path.exists(abs_path) and os.path.getsize(abs_path) > 0:
                existing_files.append(rel_path)
            else:
                missing_files.append(rel_path)

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
                'package_n': package_n
            }
        }

    # ==========================================================
    # 2. build_task_queue：构建撰写任务队列
    # ==========================================================

    def build_task_queue(self, workspace_path: str) -> dict:
        """
        根据 outline.json 构建撰写任务队列，处理依赖关系

        - 从 outline.json 中递归提取所有 write_content=true 的节点
        - 检查节点是否存在 depends_on 字段：
            存在: 使用拓扑排序算法生成执行顺序
            不存在: 默认按大纲深度优先遍历顺序执行（同级节点可并行）
        - 标记可并行执行的节点组
        - 检查点恢复：跳过已完成的节点
        - 失败节点自动识别：扫描文件状态自动将"文件缺失"或"字数严重不足"的节点加入 failed_nodes
        - 失败节点重试编排：将 failed_nodes 中的节点优先排在任务队列最前，便于主控 Agent 优先重试

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 任务队列构建结果，新增字段：
                - retry_tasks: 失败重试任务列表（优先执行）
                - new_tasks: 全新待执行任务列表
                - failed_detection: 失败节点自动检测报告
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'task_queue': [],
                'parallel_groups': [],
                'total_tasks': 0,
                'skipped_tasks': [],
                'error': f'outline.json 不存在: {outline_path}'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'task_queue': [],
                'parallel_groups': [],
                'total_tasks': 0,
                'skipped_tasks': [],
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 递归提取所有 write_content=true 的叶子节点（深度优先顺序）
        leaf_nodes = []

        def collect_leaf_nodes(node, parent_path_parts):
            """递归收集叶子节点，同时记录路径用于构造 file_path"""
            if not isinstance(node, dict):
                return
            node_id = node.get('node_id', '')
            title = node.get('title', '')
            level = node.get('level', 1)
            write_content = node.get('write_content', False)
            children = node.get('children', [])

            sanitized_title = self._sanitize_filename(title)

            # 构造当前节点的路径部分
            # 根节点不参与目录命名
            current_path_parts = parent_path_parts.copy()
            if node_id != '1' and sanitized_title:
                current_path_parts.append(f'{node_id}_{sanitized_title}')

            if write_content:
                # 叶子节点：构造 .md 文件路径
                # 文件名: {node_id}_{title}.md，放在父目录下
                file_name = f'{node_id}_{sanitized_title}.md'
                # 路径: proposal_file/<父目录链>/<file_name>
                if current_path_parts:
                    # 当前节点本身也是路径一部分，但叶子节点不创建目录
                    # 所以文件放在 current_path_parts[:-1] 对应的目录下
                    # 但 current_path_parts 最后一个就是 {node_id}_{title}
                    # 实际上叶子节点的文件放在其父节点目录下
                    # 重新审视：父目录是 parent_path_parts，文件名是 {node_id}_{title}.md
                    file_dir_parts = parent_path_parts
                else:
                    file_dir_parts = []
                file_dir = '/'.join(file_dir_parts) if file_dir_parts else ''
                if file_dir:
                    file_path = f'proposal_file/{file_dir}/{file_name}'
                else:
                    file_path = f'proposal_file/{file_name}'

                task = {
                    'node_id': node_id,
                    'title': title,
                    'level': level,
                    'word_count': node.get('word_count', 2000),
                    'content_plan': node.get('content_plan', ''),
                    'generate_chart': node.get('generate_chart', False),
                    'charts': node.get('charts', []),
                    'depends_on': node.get('depends_on', []),
                    'file_path': file_path,
                    'status': 'pending'
                }
                leaf_nodes.append(task)
            else:
                # 非叶子节点：继续递归子节点
                for child in children:
                    collect_leaf_nodes(child, current_path_parts)

        # 从根节点开始，根节点不参与目录命名
        collect_leaf_nodes(outline, [])

        # 检查点恢复：先自动识别失败节点（扫描文件状态）
        failed_detection = self.identify_failed_nodes(workspace_path)

        # 获取已完成和失败的节点列表（已包含自动识别的结果）
        completed_nodes_result = self.get_completed_nodes(workspace_path)
        completed_nodes = set(completed_nodes_result.get('completed_nodes', []))
        failed_nodes = set(completed_nodes_result.get('failed_nodes', []))

        # 获取失败节点重试计数（用于判断是否超过最大重试次数）
        retry_counts = completed_nodes_result.get('retry_counts', {})

        # 分离待执行任务与跳过的任务
        pending_tasks = []
        skipped_tasks = []
        retry_tasks = []  # 重试任务（优先执行）
        new_tasks = []  # 全新任务
        exhausted_tasks = []  # 重试次数耗尽的任务（需人工介入）

        for task in leaf_nodes:
            node_id = task['node_id']
            if node_id in completed_nodes:
                task['status'] = 'completed'
                skipped_tasks.append(node_id)
            elif node_id in failed_nodes:
                # 失败的节点：检查重试次数
                retry_count = retry_counts.get(node_id, 0)
                if retry_count >= MAX_RETRY_COUNT:
                    # 重试次数耗尽，标记为 exhausted，不加入待执行队列
                    task['status'] = 'exhausted'
                    task['retry_count'] = retry_count
                    exhausted_tasks.append(task)
                else:
                    # 仍可重试：加入重试任务列表（优先执行）
                    task['status'] = 'retry'
                    task['retry_count'] = retry_count
                    retry_tasks.append(task)
                    pending_tasks.append(task)
            else:
                # 全新任务
                task['status'] = 'pending'
                new_tasks.append(task)
                pending_tasks.append(task)

        # 检查是否存在 depends_on 字段
        # 注意：依赖关系有效性验证（被依赖节点必须存在于当前待执行任务或已完成任务中）
        all_node_ids = set(task['node_id'] for task in leaf_nodes)  # 所有叶子节点 ID
        valid_pending_ids = set(task['node_id'] for task in pending_tasks)  # 待执行任务 ID
        invalid_depends = []  # 记录无效依赖关系

        for task in pending_tasks:
            depends_on = task.get('depends_on', [])
            for dep_id in depends_on:
                if dep_id not in all_node_ids:
                    # 被依赖的节点在大纲中不存在
                    invalid_depends.append({
                        'node_id': task['node_id'],
                        'invalid_depends_on': dep_id,
                        'reason': '被依赖节点在大纲中不存在'
                    })

        # 如果存在无效依赖关系，记录但不阻塞流程（仅过滤掉无效依赖）
        if invalid_depends:
            # 过滤掉无效的依赖关系
            for task in pending_tasks:
                depends_on = task.get('depends_on', [])
                task['depends_on'] = [
                    dep_id for dep_id in depends_on
                    if dep_id in all_node_ids
                ]

        # 检测循环依赖
        cycle_detected = self._detect_cycle(pending_tasks)
        if cycle_detected:
            # 发现循环依赖，回退到深度优先顺序执行
            has_dependencies = False
            task_queue = self._reorder_with_retry_first(pending_tasks, retry_tasks)
            parallel_groups = self._group_parallel_tasks_dfs(task_queue)
        else:
            # 检查是否存在有效的 depends_on 字段
            has_dependencies = any(
                task.get('depends_on') for task in pending_tasks
            )

            if has_dependencies:
                # 使用拓扑排序（重试任务优先）
                task_queue, parallel_groups = self._topological_sort_with_retry(pending_tasks, retry_tasks)
            else:
                # 无依赖：按深度优先顺序，同级节点可并行（重试任务优先）
                task_queue = self._reorder_with_retry_first(pending_tasks, retry_tasks)
                parallel_groups = self._group_parallel_tasks_dfs(task_queue)

        return {
            'success': True,
            'task_queue': task_queue,
            'parallel_groups': parallel_groups,
            'total_tasks': len(pending_tasks),
            'skipped_tasks': skipped_tasks,
            'has_dependencies': has_dependencies,
            'invalid_depends': invalid_depends,  # 无效依赖关系列表
            'cycle_detected': cycle_detected,  # 是否检测到循环依赖
            'sort_strategy': 'topological' if has_dependencies and not cycle_detected else 'dfs',
            # 新增字段：失败节点重试编排
            'retry_tasks': [t['node_id'] for t in retry_tasks],  # 重试任务 node_id 列表
            'new_tasks': [t['node_id'] for t in new_tasks],  # 全新任务 node_id 列表
            'exhausted_tasks': [t['node_id'] for t in exhausted_tasks],  # 重试耗尽任务
            'failed_detection': failed_detection,  # 失败节点自动检测报告
            'retry_summary': {
                'retry_count': len(retry_tasks),
                'new_count': len(new_tasks),
                'exhausted_count': len(exhausted_tasks),
                'max_retry': MAX_RETRY_COUNT
            }
        }

    def _reorder_with_retry_first(self, pending_tasks: list, retry_tasks: list) -> list:
        """
        重排序任务队列：重试任务优先，新任务在后

        Args:
            pending_tasks: 所有待执行任务（包含重试任务和新任务）
            retry_tasks: 重试任务列表（用于识别哪些是重试任务）

        Returns:
            list: 重排序后的任务列表
        """
        retry_ids = set(t['node_id'] for t in retry_tasks)
        retry_list = []
        new_list = []
        for task in pending_tasks:
            if task['node_id'] in retry_ids:
                retry_list.append(task)
            else:
                new_list.append(task)
        return retry_list + new_list

    def _topological_sort_with_retry(self, tasks: list, retry_tasks: list) -> tuple:
        """
        拓扑排序（重试优先版）：重试任务在同批次中优先排序

        Args:
            tasks: 所有待执行任务
            retry_tasks: 重试任务列表

        Returns:
            tuple: (排序后的任务队列, 可并行执行的节点分组)
        """
        # 先用标准拓扑排序得到分组
        sorted_queue, parallel_groups = self._topological_sort(tasks)

        # 在每个并行组内，将重试任务排在前面
        retry_ids = set(t['node_id'] for t in retry_tasks)
        reordered_groups = []
        for group in parallel_groups:
            retry_in_group = [nid for nid in group if nid in retry_ids]
            new_in_group = [nid for nid in group if nid not in retry_ids]
            reordered_groups.append(retry_in_group + new_in_group)

        # 重新构造任务队列（基于重排序后的分组）
        task_map = {task['node_id']: task for task in tasks}
        reordered_queue = []
        for group in reordered_groups:
            for nid in group:
                if nid in task_map:
                    reordered_queue.append(task_map[nid])

        # 补全可能遗漏的节点（循环依赖残留）
        queued_ids = set(t['node_id'] for t in reordered_queue)
        for task in sorted_queue:
            if task['node_id'] not in queued_ids:
                reordered_queue.append(task)
                if not reordered_groups or task['node_id'] not in reordered_groups[-1]:
                    reordered_groups.append([task['node_id']])

        return reordered_queue, reordered_groups

    def _topological_sort(self, tasks: list) -> tuple:
        """
        拓扑排序：确保依赖节点先于被依赖节点执行

        Args:
            tasks: 待排序的任务列表

        Returns:
            tuple: (排序后的任务队列, 可并行执行的节点分组)
        """
        # 构建入度表和邻接表
        task_map = {task['node_id']: task for task in tasks}
        in_degree = {task['node_id']: 0 for task in tasks}
        adjacency = {task['node_id']: [] for task in tasks}

        # 仅考虑当前待执行任务集合内的依赖关系
        pending_ids = set(task_map.keys())
        for task in tasks:
            for depend_id in task.get('depends_on', []):
                if depend_id in pending_ids:
                    in_degree[task['node_id']] += 1
                    adjacency[depend_id].append(task['node_id'])

        # 拓扑排序（BFS），同批次入度为0的节点可并行
        result = []
        parallel_groups = []
        queue = [nid for nid in pending_ids if in_degree[nid] == 0]
        # 按节点 ID 排序，保证稳定性
        queue.sort()

        while queue:
            # 当前批次的所有节点均可并行执行
            current_batch = list(queue)
            parallel_groups.append(current_batch)
            result.extend(task_map[nid] for nid in current_batch)
            next_queue = []
            for nid in current_batch:
                for neighbor in adjacency[nid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            next_queue.sort()
            queue = next_queue

        # 处理可能存在的循环依赖（未在 result 中的节点）
        for nid in pending_ids:
            if nid not in [t['node_id'] for t in result]:
                result.append(task_map[nid])
                if not parallel_groups or nid not in parallel_groups[-1]:
                    parallel_groups.append([nid])

        return result, parallel_groups

    def _detect_cycle(self, tasks: list) -> bool:
        """
        检测任务列表中是否存在循环依赖

        使用 DFS 三色标记法：
        - 白色（未访问）：节点未被访问
        - 灰色（访问中）：节点正在被访问（在当前 DFS 路径上）
        - 黑色（已访问）：节点及其所有后代都已访问完毕

        如果在 DFS 过程中遇到灰色节点，则存在循环依赖。

        Args:
            tasks: 任务列表

        Returns:
            bool: True 表示存在循环依赖，False 表示无循环依赖
        """
        # 构建依赖图
        task_map = {task['node_id']: task for task in tasks}
        pending_ids = set(task_map.keys())

        # 颜色：0=白色（未访问），1=灰色（访问中），2=黑色（已访问）
        color = {nid: 0 for nid in pending_ids}

        def dfs(node_id, path):
            """DFS 遍历，检测循环"""
            color[node_id] = 1  # 标记为灰色（访问中）
            path.append(node_id)

            task = task_map.get(node_id)
            if task:
                for dep_id in task.get('depends_on', []):
                    if dep_id not in pending_ids:
                        # 被依赖节点不在当前待执行集合中（可能已完成），跳过
                        continue
                    if color[dep_id] == 1:
                        # 遇到灰色节点，存在循环依赖
                        return True
                    elif color[dep_id] == 0:
                        # 白色节点，继续 DFS
                        if dfs(dep_id, path):
                            return True

            color[node_id] = 2  # 标记为黑色（已访问）
            path.pop()
            return False

        # 对所有白色节点进行 DFS
        for nid in pending_ids:
            if color[nid] == 0:
                if dfs(nid, []):
                    return True

        return False

    def _group_parallel_tasks_dfs(self, tasks: list) -> list:
        """
        无依赖时，按深度优先顺序分组同级可并行节点

        策略：按 node_id 的父节点路径分组，同一父节点下的叶子节点可并行

        Args:
            tasks: 任务列表（已按 DFS 顺序）

        Returns:
            list: 可并行执行的节点分组
        """
        if not tasks:
            return []

        # 按"父节点ID"分组（node_id 去掉最后一段）
        def get_parent_id(node_id: str) -> str:
            parts = node_id.split('_')
            if len(parts) <= 1:
                return ''
            return '_'.join(parts[:-1])

        groups = {}
        order = []
        for task in tasks:
            parent = get_parent_id(task['node_id'])
            if parent not in groups:
                groups[parent] = []
                order.append(parent)
            groups[parent].append(task['node_id'])

        # 每个父节点下的叶子节点作为一个并行组
        parallel_groups = [groups[p] for p in order]
        return parallel_groups

    # ==========================================================
    # 3. word_count_statistics：统计各章节字数
    # ==========================================================

    def word_count_statistics(self, workspace_path: str) -> dict:
        """
        统计各章节字数，校验偏差

        统计口径：
        - 计入：正文段落文字、表格内容、列表内容、引用内容
        - 不计入：标题文字、图表代码块、图题文字

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 字数统计结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'statistics': [],
                'summary': {},
                'error': f'outline.json 不存在: {outline_path}'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'statistics': [],
                'summary': {},
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 收集所有叶子节点信息
        leaf_nodes = []

        def collect_leaves(node, parent_path_parts):
            if not isinstance(node, dict):
                return
            node_id = node.get('node_id', '')
            title = node.get('title', '')
            write_content = node.get('write_content', False)
            children = node.get('children', [])
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
                    'word_count_planned': node.get('word_count', 0),
                    'file_path': file_path
                })
            else:
                for child in children:
                    collect_leaves(child, current_path_parts)

        collect_leaves(outline, [])

        # 统计每个文件的实际字数
        statistics = []
        total_actual = 0
        total_planned = 0
        qualified_count = 0
        warning_count = 0
        over_count_count = 0  # 字数超标但仅记录的章节数
        insufficient_count = 0  # 字数不足需补充的章节数

        for leaf in leaf_nodes:
            planned = leaf['word_count_planned'] or 0
            actual = 0
            file_exists = os.path.exists(leaf['file_path'])

            if file_exists:
                try:
                    with open(leaf['file_path'], 'r', encoding='utf-8') as f:
                        content = f.read()
                    actual = self._count_words(content)
                except Exception:
                    actual = 0

            total_actual += actual
            total_planned += planned

            # 计算偏差
            if planned > 0:
                deviation = (actual - planned) / planned
            else:
                deviation = 0.0

            # 字数判定策略：只下限不限上限
            # - 字数不足（actual < planned * (1 - WORD_COUNT_LOWER_THRESHOLD)）：不合格，需补充
            # - 字数超标（actual > planned * (1 + WORD_COUNT_LOWER_THRESHOLD)）：合格，仅记录为 over_count
            # - 字数在 [planned * (1 - lower), planned * (1 + lower)] 范围内：合格
            lower_limit = planned * (1 - WORD_COUNT_LOWER_THRESHOLD)
            upper_record_limit = planned * (1 + WORD_COUNT_LOWER_THRESHOLD)  # 超过此值记录为 over_count

            if actual < lower_limit:
                # 字数不足：不合格，需补充
                is_qualified = False
                status_label = 'insufficient'  # 字数不足
                insufficient_count += 1
                warning_count += 1
            elif actual > upper_record_limit:
                # 字数超标：合格，仅记录为 over_count（不限制）
                is_qualified = True
                status_label = 'over_count'  # 字数超标（仅记录）
                over_count_count += 1
                qualified_count += 1
            else:
                # 字数在合理范围内
                is_qualified = True
                status_label = 'qualified'
                qualified_count += 1

            statistics.append({
                'node_id': leaf['node_id'],
                'title': leaf['title'],
                'planned': planned,
                'actual': actual,
                'deviation': round(deviation * 100, 2),  # 百分比
                'qualified': is_qualified,
                'status_label': status_label,  # qualified/insufficient/over_count
                'file_exists': file_exists,
                'file_path': leaf['file_path']
            })

        return {
            'success': True,
            'statistics': statistics,
            'summary': {
                'total_actual': total_actual,
                'total_planned': total_planned,
                'qualified_count': qualified_count,
                'warning_count': warning_count,
                'insufficient_count': insufficient_count,  # 字数不足需补充的章节数
                'over_count_count': over_count_count,  # 字数超标仅记录的章节数
                'total_sections': len(statistics),
                'strategy': 'lower_limit_only',  # 标识当前策略：只下限不限上限
            }
        }

    def _count_words(self, content: str) -> int:
        """
        统计 Markdown 内容的字数（按字数统计口径）

        计入：正文段落文字、表格内容、列表内容、引用内容
        不计入：标题文字、图表代码块（```mermaid ... ```）、图题文字（*图 X-Y-Z-N ...*）

        Args:
            content: Markdown 文本内容

        Returns:
            int: 字数
        """
        if not content:
            return 0

        lines = content.split('\n')
        result_lines = []
        in_code_block = False
        in_mermaid_block = False

        for line in lines:
            stripped = line.strip()

            # 检测代码块开始/结束
            if stripped.startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    # mermaid 代码块特殊处理
                    if 'mermaid' in stripped.lower():
                        in_mermaid_block = True
                    # 非 mermaid 的普通代码块内容计入字数（表格内容规则）
                    # 但为简化处理，代码块整体不计入（与 mermaid 一致）
                    continue
                else:
                    # 代码块结束
                    in_code_block = False
                    in_mermaid_block = False
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

            # 其他行计入字数（包括段落、表格行、列表行、引用行）
            # 去除 Markdown 语法标记，统计实际文字
            cleaned = self._clean_markdown_syntax(stripped)
            result_lines.append(cleaned)

        # 合并并统计字符数
        # 中文按字符计，英文单词按词计（简化处理：统一按字符计，去除空白）
        text = ''.join(result_lines)
        # 去除所有空白字符
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
    # 4. quality_self_check：质量自查
    # ==========================================================

    def quality_self_check(self, workspace_path: str) -> dict:
        """
        执行质量自查

        检查内容：
        1. 标题层级检查：标题层级连续、不超过大纲节点层级一级、不添加数字编号
        2. 格式规范检查：段落格式、图表代码块格式、图题标记、表格标题格式
        3. 内容完整性检查：正文是否覆盖 content_plan 中的所有要点
        4. 图表规范检查：Mermaid 代码块语法、图表数量与 charts 数组长度一致

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 自查结果
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'passed': False,
                'checks': {},
                'issues': [f'outline.json 不存在: {outline_path}']
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'passed': False,
                'checks': {},
                'issues': [f'读取 outline.json 失败: {str(e)}']
            }

        # 收集叶子节点
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
                    'generate_chart': generate_chart,
                    'charts': charts,
                    'file_path': file_path
                })
            else:
                for child in children:
                    collect_leaves(child, current_path_parts)

        collect_leaves(outline, [])

        all_issues = []
        heading_level_issues = []
        format_issues = []
        content_issues = []
        chart_issues = []

        for leaf in leaf_nodes:
            if not os.path.exists(leaf['file_path']):
                all_issues.append(f'[{leaf["node_id"]}] 正文文件不存在: {leaf["file_path"]}')
                content_issues.append(f'[{leaf["node_id"]}] 正文文件不存在')
                continue

            try:
                with open(leaf['file_path'], 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                all_issues.append(f'[{leaf["node_id"]}] 读取正文文件失败: {str(e)}')
                continue

            # 1. 标题层级检查
            self._check_heading_level(content, leaf, heading_level_issues)
            # 2. 格式规范检查
            self._check_format(content, leaf, format_issues)
            # 3. 内容完整性检查
            self._check_content_completeness(content, leaf, content_issues)
            # 4. 图表规范检查
            self._check_charts(content, leaf, chart_issues)

        all_issues = heading_level_issues + format_issues + content_issues + chart_issues

        heading_passed = len(heading_level_issues) == 0
        format_passed = len(format_issues) == 0
        content_passed = len(content_issues) == 0
        chart_passed = len(chart_issues) == 0

        return {
            'success': True,
            'passed': len(all_issues) == 0,
            'checks': {
                'heading_level': {
                    'passed': heading_passed,
                    'issue_count': len(heading_level_issues),
                    'issues': heading_level_issues
                },
                'format': {
                    'passed': format_passed,
                    'issue_count': len(format_issues),
                    'issues': format_issues
                },
                'content_completeness': {
                    'passed': content_passed,
                    'issue_count': len(content_issues),
                    'issues': content_issues
                },
                'chart': {
                    'passed': chart_passed,
                    'issue_count': len(chart_issues),
                    'issues': chart_issues
                }
            },
            'issues': all_issues
        }

    def _check_heading_level(self, content: str, leaf: dict, issues: list):
        """检查标题层级"""
        node_level = leaf['level']
        # 允许的标题层级上限 = 大纲节点层级 + 1
        max_heading_level = min(node_level + 1, 6)
        # 对应的 Markdown 标题符号数
        max_heading_marks = '#' * max_heading_level

        lines = content.split('\n')
        prev_heading_level = 0
        in_code_block = False  # 是否处于围栏代码块（``` 或 ~~~）内，代码块内容不参与标题检查

        for line in lines:
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

                # 检查层级是否超限
                if current_level > max_heading_level:
                    issues.append(
                        f'[{leaf["node_id"]}] 标题层级超限: "{stripped}" '
                        f'（当前 {current_level} 级，大纲节点 {node_level} 级，允许上限 {max_heading_level} 级）'
                    )

                # 检查层级是否连续（不跳级）
                if prev_heading_level > 0 and current_level > prev_heading_level + 1:
                    issues.append(
                        f'[{leaf["node_id"]}] 标题层级跳级: 从 {prev_heading_level} 级跳到 {current_level} 级'
                    )

                # 检查是否添加了数字编号（如 "1.1 xxx"、"第一章 xxx"）
                if re.match(r'^[\d\.]+\s', heading_text) or re.match(r'^第[一二三四五六七八九十]+[章节]', heading_text):
                    issues.append(
                        f'[{leaf["node_id"]}] 标题添加了数字编号: "{stripped}"（应仅使用 Markdown 层级符号）'
                    )

                prev_heading_level = current_level

    def _check_format(self, content: str, leaf: dict, issues: list):
        """检查格式规范"""
        lines = content.split('\n')

        # 检查 mermaid 代码块格式
        in_mermaid = False
        mermaid_block_count = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('```mermaid'):
                in_mermaid = True
                mermaid_block_count += 1
                # 检查代码块前是否有 chart_type 注释
                if i > 0 and not lines[i - 1].strip().startswith('<!-- chart_type:'):
                    issues.append(
                        f'[{leaf["node_id"]}] Mermaid 代码块前缺少 chart_type 注释（第 {i + 1} 行）'
                    )
            elif stripped.startswith('```') and in_mermaid:
                in_mermaid = False
                # 检查代码块后是否有图题（跳过空行查找）
                caption_found = False
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if not next_line:
                        # 空行，继续查找
                        continue
                    if re.match(r'^\*图\s+[\d\-]+\s+.+\*$', next_line):
                        caption_found = True
                    # 无论是否匹配，找到第一个非空行即停止
                    break
                if not caption_found:
                    issues.append(
                        f'[{leaf["node_id"]}] Mermaid 代码块后缺少图题标记（第 {i + 2} 行附近）'
                    )

        # 检查表格标题格式
        for i, line in enumerate(lines):
            stripped = line.strip()
            # 表格行（| 开头）
            if stripped.startswith('|') and i > 0:
                prev_line = lines[i - 1].strip()
                # 如果是表格的第一行（表头），检查上方是否有表格标题
                if prev_line and not prev_line.startswith('|') and not prev_line.startswith('**表'):
                    # 进一步检查：这是否真的是表头（下一行是分隔行）
                    if i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip()):
                        issues.append(
                            f'[{leaf["node_id"]}] 表格缺少标题（第 {i + 1} 行，应使用 **表 X-Y-Z-N 表格名称** 格式）'
                        )

    def _check_content_completeness(self, content: str, leaf: dict, issues: list):
        """
        检查内容完整性：正文是否覆盖 content_plan 中的所有要点

        优化策略（2026-07-27）：
        1. 降低关键词匹配阈值（从 80% 降至 50%），减少误判
        2. 引入语义检查兜底机制：关键词覆盖率在 50%-80% 之间时，建议主控 Agent 进行语义检查
        3. 优化关键词提取：去除停用词，提取核心关键词（长度 >= 2 的词）
        4. 改进匹配逻辑：使用子串包含匹配，更宽松
        """
        content_plan = leaf.get('content_plan', '')
        if not content_plan:
            return

        # 解析 content_plan 中的要点（格式：1. xxx；2. xxx；3. xxx）
        points = re.split(r'[；;]', content_plan)
        points = [p.strip() for p in points if p.strip()]

        if not points:
            return

        # 中文停用词列表（用于过滤无意义的关键词）
        stopwords = {
            '的', '了', '在', '是', '和', '与', '及', '或', '等', '中', '上', '下',
            '对', '为', '以', '及', '其', '之', '也', '而', '且', '并', '但',
            '一个', '一种', '方面', '内容', '进行', '通过', '根据', '按照',
            '包括', '包含', '涉及', '相关', '主要', '基本', '一般', '具体',
        }

        # 提取每个要点的关键词（去掉序号前缀）
        point_keywords = []
        for point in points:
            # 去除 "1. " 等序号前缀
            cleaned = re.sub(r'^\d+\.\s*', '', point)
            # 提取关键词（中文词组 + 英文单词）
            raw_keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', cleaned)
            # 过滤停用词和长度过短的词
            keywords = [
                kw for kw in raw_keywords
                if kw not in stopwords and len(kw) >= 2
            ]
            if keywords:
                point_keywords.append({
                    'original': cleaned,
                    'keywords': keywords,
                    'all_keywords': raw_keywords  # 保留所有关键词用于宽松匹配
                })

        # 检查每个要点是否在正文中有所体现
        missing_points = []
        partial_points = []  # 部分匹配的要点（用于语义检查建议）
        for point_info in point_keywords:
            keywords = point_info['keywords']
            all_keywords = point_info['all_keywords']

            # 精确匹配：检查核心关键词（长度 >= 2）是否在正文中出现
            matched_count = 0
            for kw in keywords:
                if kw in content:
                    matched_count += 1

            # 宽松匹配：如果核心关键词都没匹配到，尝试用所有关键词（含短词）
            if matched_count == 0:
                for kw in all_keywords:
                    if kw in content:
                        matched_count += 1
                        break  # 宽松匹配只算一次

            if matched_count == 0:
                missing_points.append(point_info['original'])
            elif matched_count < len(keywords) * 0.5:
                # 部分匹配（匹配率 < 50%）
                partial_points.append(point_info['original'])

        # 计算覆盖率
        total_points = len(point_keywords)
        covered_points = total_points - len(missing_points)
        coverage = covered_points / total_points if total_points > 0 else 1.0

        # 分级处理
        if coverage < CONTENT_COVERAGE_THRESHOLD:
            # 覆盖率低于阈值（50%）：直接判定为问题
            issues.append(
                f'[{leaf["node_id"]}] 内容完整性不足: 关键词覆盖率 {coverage * 100:.1f}% '
                f'（要求 ≥ {CONTENT_COVERAGE_THRESHOLD * 100}%），缺失要点: {missing_points}'
            )
        elif coverage < SEMANTIC_CHECK_TRIGGER_THRESHOLD:
            # 覆盖率在 50%-80% 之间：建议主控 Agent 进行语义检查
            issues.append(
                f'[{leaf["node_id"]}] 关键词覆盖率 {coverage * 100:.1f}%（介于 50%-80%），'
                f'建议主控 Agent 进行语义检查确认内容完整性。'
                f'部分匹配要点: {partial_points}，缺失要点: {missing_points}'
            )
        # else: 覆盖率 >= 80%，认为通过，不报告问题

    def _check_charts(self, content: str, leaf: dict, issues: list):
        """检查图表规范"""
        if not leaf.get('generate_chart', False):
            return

        charts = leaf.get('charts', [])
        expected_count = len(charts)

        # 统计 mermaid 代码块数量
        mermaid_count = len(re.findall(r'```mermaid', content))

        if mermaid_count != expected_count:
            issues.append(
                f'[{leaf["node_id"]}] 图表数量不一致: 实际 {mermaid_count} 个，期望 {expected_count} 个'
            )

        # 检查每个图表的图题是否完整
        chart_captions = re.findall(r'\*图\s+[\d\-]+\s+.+\*', content)
        if len(chart_captions) < mermaid_count:
            issues.append(
                f'[{leaf["node_id"]}] 图题数量不足: 实际 {len(chart_captions)} 个，'
                f'Mermaid 代码块 {mermaid_count} 个'
            )

    # ==========================================================
    # 5. generate_summary_report：生成撰写完成报告
    # ==========================================================

    def generate_summary_report(self, workspace_path: str) -> dict:
        """
        生成撰写完成报告

        报告内容包括：完成时间、章节统计、字数统计、图表生成统计、自查结果汇总

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 报告生成结果
        """
        # 收集各项统计数据
        word_count_result = self.word_count_statistics(workspace_path)
        quality_result = self.quality_self_check(workspace_path)
        completed_result = self.get_completed_nodes(workspace_path)

        completed_nodes = completed_result.get('completed_nodes', [])
        failed_nodes = completed_result.get('failed_nodes', [])

        # 自动更新检查点：根据字数统计结果，将文件存在且字数合格的节点标记为完成
        # 这是为了弥补主控Agent在writer-agent完成后未调用update_completed_nodes的问题
        statistics = word_count_result.get('statistics', [])
        for stat in statistics:
            node_id = stat['node_id']
            file_exists = stat.get('file_exists', False)
            is_qualified = stat.get('qualified', False)
            status_label = stat.get('status_label', '')
            
            # 文件存在且字数合格（包括over_count，因为只下限不限上限），标记为完成
            if file_exists and (is_qualified or status_label == 'over_count'):
                if node_id not in completed_nodes:
                    completed_nodes.append(node_id)
                if node_id in failed_nodes:
                    failed_nodes.remove(node_id)
        
        # 保存更新后的检查点
        metadata = self._read_metadata(workspace_path)
        if metadata:
            metadata['completed_nodes'] = completed_nodes
            metadata['failed_nodes'] = failed_nodes
            self._save_metadata(workspace_path, metadata)

        statistics = word_count_result.get('statistics', [])
        summary = word_count_result.get('summary', {})

        checks = quality_result.get('checks', {})

        # 统计图表生成情况
        total_charts = 0
        generated_charts = 0
        failed_charts = 0
        for stat in statistics:
            # 从 outline 中获取该节点的图表数量
            node_id = stat['node_id']
            outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
            try:
                with open(outline_path, 'r', encoding='utf-8') as f:
                    outline = json.load(f)
                node_info = self._find_node_by_id(outline, node_id)
                if node_info and node_info.get('generate_chart'):
                    charts = node_info.get('charts', [])
                    total_charts += len(charts)
                    if stat.get('file_exists'):
                        generated_charts += len(charts)
                    else:
                        failed_charts += len(charts)
            except Exception:
                pass

        # 生成报告内容
        report_lines = []
        report_lines.append('# 正文撰写完成报告')
        report_lines.append('')
        report_lines.append(f'**完成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        report_lines.append('')

        # 章节统计
        report_lines.append('## 一、章节统计')
        report_lines.append('')
        report_lines.append(f'| 项目 | 数量 |')
        report_lines.append(f'|------|------|')
        report_lines.append(f'| 总节点数 | {len(statistics)} |')
        report_lines.append(f'| 已完成数 | {len(completed_nodes)} |')
        report_lines.append(f'| 失败数 | {len(failed_nodes)} |')
        report_lines.append(f'| 跳过数（检查点恢复） | {len(completed_nodes)} |')
        report_lines.append('')

        if failed_nodes:
            report_lines.append(f'**失败节点**：{", ".join(failed_nodes)}')
            report_lines.append('')

        # 字数统计
        report_lines.append('## 二、字数统计')
        report_lines.append('')
        report_lines.append(f'| 项目 | 数值 |')
        report_lines.append(f'|------|------|')
        report_lines.append(f'| 实际总字数 | {summary.get("total_actual", 0)} |')
        report_lines.append(f'| 计划总字数 | {summary.get("total_planned", 0)} |')
        report_lines.append(f'| 合格章节数 | {summary.get("qualified_count", 0)} |')
        report_lines.append(f'| 字数不足章节数 | {summary.get("insufficient_count", 0)} |')
        report_lines.append(f'| 字数超标章节数（仅记录） | {summary.get("over_count_count", 0)} |')
        report_lines.append(f'| 警告章节数 | {summary.get("warning_count", 0)} |')
        report_lines.append(f'| 策略 | 只下限不限上限 |')
        report_lines.append('')

        # 各章节字数详情
        report_lines.append('### 各章节字数详情')
        report_lines.append('')
        report_lines.append('| 节点ID | 标题 | 计划字数 | 实际字数 | 偏差(%) | 状态 |')
        report_lines.append('|--------|------|----------|----------|---------|------|')
        for stat in statistics:
            status_label = stat.get('status_label', 'qualified')
            if not stat.get('file_exists'):
                status = '❌ 文件缺失'
            elif status_label == 'insufficient':
                status = '⚠️ 字数不足'
            elif status_label == 'over_count':
                status = '📝 字数超标（仅记录）'
            else:
                status = '✅ 合格'
            report_lines.append(
                f'| {stat["node_id"]} | {stat["title"]} | {stat["planned"]} | '
                f'{stat["actual"]} | {stat["deviation"]}% | {status} |'
            )
        report_lines.append('')

        # 图表生成统计
        report_lines.append('## 三、图表生成统计')
        report_lines.append('')
        report_lines.append(f'| 项目 | 数量 |')
        report_lines.append(f'|------|------|')
        report_lines.append(f'| 总图表数 | {total_charts} |')
        report_lines.append(f'| 生成成功数 | {generated_charts} |')
        report_lines.append(f'| 生成失败数 | {failed_charts} |')
        report_lines.append('')

        # 自查结果汇总
        report_lines.append('## 四、自查结果汇总')
        report_lines.append('')
        report_lines.append('| 检查项 | 通过状态 | 问题数 |')
        report_lines.append('|--------|----------|--------|')
        for check_name, check_result in checks.items():
            check_label = {
                'heading_level': '标题层级',
                'format': '格式规范',
                'content_completeness': '内容完整性',
                'chart': '图表规范'
            }.get(check_name, check_name)
            passed = '✅ 通过' if check_result.get('passed') else '❌ 未通过'
            report_lines.append(
                f'| {check_label} | {passed} | {check_result.get("issue_count", 0)} |'
            )
        report_lines.append('')

        # 问题详情列表
        all_issues = quality_result.get('issues', [])
        report_lines.append('## 五、问题详情列表')
        report_lines.append('')
        if all_issues:
            for idx, issue in enumerate(all_issues, 1):
                report_lines.append(f'{idx}. {issue}')
        else:
            report_lines.append('无问题')
        report_lines.append('')

        report_lines.append('---')
        report_lines.append(f'*报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*')

        # 写入文件
        report_path = os.path.join(workspace_path, 'proposal_file', 'summary_report.md')
        try:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines))
        except Exception as e:
            return {
                'success': False,
                'report_path': '',
                'error': f'写入 summary_report.md 失败: {str(e)}'
            }

        return {
            'success': True,
            'report_path': report_path,
            'stats': {
                'total_sections': len(statistics),
                'completed_sections': len(completed_nodes),
                'failed_sections': len(failed_nodes),
                'total_charts': total_charts,
                'generated_charts': generated_charts,
                'failed_charts': failed_charts,
                'issue_count': len(all_issues)
            }
        }

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

    # ==========================================================
    # 6. update_metadata_status：更新项目状态
    # ==========================================================

    def update_metadata_status(self, workspace_path: str, status: str = '正文撰写完成') -> dict:
        """
        更新 metadata.json 的项目状态字段，并更新状态更新时间

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

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'status': status,
                'updated_fields': ['项目状态', '状态更新时间']
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 7. get_completed_nodes：获取已完成节点列表
    # ==========================================================

    def get_completed_nodes(self, workspace_path: str) -> dict:
        """
        获取已完成节点列表（检查点恢复）

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 已完成节点列表，包含：
                - completed_nodes: 已完成节点 ID 列表
                - failed_nodes: 失败节点 ID 列表
                - retry_counts: 各失败节点的重试次数（{node_id: count}）
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {
                'success': True,
                'completed_nodes': [],
                'failed_nodes': [],
                'retry_counts': {}
            }

        completed_nodes = metadata.get('completed_nodes', [])
        failed_nodes = metadata.get('failed_nodes', [])
        retry_counts = metadata.get('retry_counts', {})

        return {
            'success': True,
            'completed_nodes': completed_nodes,
            'failed_nodes': failed_nodes,
            'retry_counts': retry_counts
        }

    # ==========================================================
    # 7.1 identify_failed_nodes：自动识别失败节点（检查点恢复核心）
    # ==========================================================

    def identify_failed_nodes(self, workspace_path: str) -> dict:
        """
        自动识别失败节点：扫描所有叶子节点的文件状态和字数情况

        识别规则：
        1. 文件不存在 → 标记为 failed（writer-agent 未生成或被中断）
        2. 文件存在但实际字数 < 计划字数 * FAILED_NODE_WORD_RATIO_THRESHOLD → 标记为 failed（严重不足）
        3. 文件存在但实际字数 < MIN_FAILED_WORD_COUNT → 标记为 failed（绝对字数过少）

        本函数会自动更新 metadata.json 中的 failed_nodes 字段，并保留原 retry_counts。
        已标记为 completed 的节点不会被重复标记为 failed。

        Args:
            workspace_path: 工作空间路径

        Returns:
            dict: 失败节点检测报告，包含：
                - detected_failed: 本次新检测到的失败节点列表
                - existing_failed: 之前已标记的失败节点列表
                - total_failed: 合并后的失败节点总数
                - detection_details: 详细检测信息（每个失败节点的原因和字数）
        """
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if not os.path.exists(outline_path):
            return {
                'success': False,
                'detected_failed': [],
                'existing_failed': [],
                'total_failed': 0,
                'detection_details': [],
                'error': 'outline.json 不存在'
            }

        try:
            with open(outline_path, 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except Exception as e:
            return {
                'success': False,
                'detected_failed': [],
                'existing_failed': [],
                'total_failed': 0,
                'detection_details': [],
                'error': f'读取 outline.json 失败: {str(e)}'
            }

        # 收集叶子节点
        leaf_nodes = self._collect_leaf_nodes_for_detection(outline, workspace_path)

        # 读取当前 metadata
        metadata = self._read_metadata(workspace_path)
        completed_nodes = set(metadata.get('completed_nodes', []))
        existing_failed = set(metadata.get('failed_nodes', []))

        detected_failed = []  # 本次新检测到的失败节点
        detection_details = []  # 详细检测信息

        for leaf in leaf_nodes:
            node_id = leaf['node_id']
            # 已完成的节点不检测
            if node_id in completed_nodes:
                continue

            file_path = leaf['file_path']
            planned_word_count = leaf.get('word_count', 0) or 0
            file_exists = os.path.exists(file_path)

            failure_reason = None
            actual_word_count = 0

            if not file_exists:
                failure_reason = 'file_missing'
            else:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    actual_word_count = self._count_words(content)
                except Exception:
                    failure_reason = 'file_read_error'

                if failure_reason is None:
                    # 检查字数严重不足
                    if planned_word_count > 0:
                        ratio = actual_word_count / planned_word_count
                        if ratio < FAILED_NODE_WORD_RATIO_THRESHOLD:
                            failure_reason = 'word_count_severely_insufficient'
                        elif actual_word_count < MIN_FAILED_WORD_COUNT:
                            failure_reason = 'word_count_absolutely_insufficient'

            if failure_reason:
                if node_id not in existing_failed:
                    detected_failed.append(node_id)
                detection_details.append({
                    'node_id': node_id,
                    'title': leaf['title'],
                    'reason': failure_reason,
                    'planned_word_count': planned_word_count,
                    'actual_word_count': actual_word_count,
                    'file_exists': file_exists,
                    'file_path': file_path
                })

        # 合并失败节点列表
        all_failed = list(existing_failed.union(set(detected_failed)))

        # 更新 metadata.json
        if detected_failed:
            metadata['failed_nodes'] = all_failed
            # 初始化新检测到的失败节点的 retry_counts
            retry_counts = metadata.get('retry_counts', {})
            for nid in detected_failed:
                if nid not in retry_counts:
                    retry_counts[nid] = 0
            metadata['retry_counts'] = retry_counts
            metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._save_metadata(workspace_path, metadata)

        return {
            'success': True,
            'detected_failed': detected_failed,
            'existing_failed': list(existing_failed),
            'total_failed': len(all_failed),
            'detection_details': detection_details
        }

    def _collect_leaf_nodes_for_detection(self, outline: dict, workspace_path: str) -> list:
        """收集叶子节点用于失败检测（与 _collect_leaf_nodes 类似，独立实现以避免循环依赖）"""
        leaf_nodes = []

        def collect(node, parent_path_parts):
            if not isinstance(node, dict):
                return
            node_id = node.get('node_id', '')
            title = node.get('title', '')
            write_content = node.get('write_content', False)
            children = node.get('children', [])
            word_count = node.get('word_count', 0)
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
                    'word_count': word_count,
                    'file_path': file_path
                })
            else:
                for child in children:
                    collect(child, current_path_parts)

        collect(outline, [])
        return leaf_nodes

    # ==========================================================
    # 7.2 update_retry_count：更新失败节点重试计数
    # ==========================================================

    def update_retry_count(self, workspace_path: str, node_id: str, increment: int = 1) -> dict:
        """
        更新失败节点的重试计数

        当 writer-agent 完成一次重试后调用本函数：
        - 如果重试成功（文件生成且字数合格），应同时调用 update_completed_nodes(node_id, 'completed')
        - 如果重试失败，调用本函数增加重试计数

        当 retry_count >= MAX_RETRY_COUNT 时，节点状态变更为 exhausted，需人工介入。

        Args:
            workspace_path: 工作空间路径
            node_id: 节点 ID
            increment: 增量（默认 1）

        Returns:
            dict: 更新结果，包含：
                - retry_count: 当前重试次数
                - status: 节点当前状态（retry/exhausted）
                - max_retry: 最大重试次数
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        retry_counts = metadata.get('retry_counts', {})
        retry_counts[node_id] = retry_counts.get(node_id, 0) + increment
        metadata['retry_counts'] = retry_counts

        # 判断是否达到重试上限
        current_count = retry_counts[node_id]
        status = 'exhausted' if current_count >= MAX_RETRY_COUNT else 'retry'

        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'node_id': node_id,
                'retry_count': current_count,
                'status': status,
                'max_retry': MAX_RETRY_COUNT
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}

    # ==========================================================
    # 8. update_completed_nodes：更新已完成节点列表
    # ==========================================================

    def update_completed_nodes(self, workspace_path: str, node_id: str, status: str = 'completed') -> dict:
        """
        更新已完成节点列表（检查点机制）

        Args:
            workspace_path: 工作空间路径
            node_id: 节点 ID
            status: 节点状态（completed/failed）

        Returns:
            dict: 更新结果
        """
        metadata = self._read_metadata(workspace_path)
        if not metadata:
            return {'success': False, 'error': 'metadata.json 不存在或读取失败'}

        completed_nodes = metadata.get('completed_nodes', [])
        failed_nodes = metadata.get('failed_nodes', [])
        retry_counts = metadata.get('retry_counts', {})

        if status == 'completed':
            if node_id not in completed_nodes:
                completed_nodes.append(node_id)
            # 从失败列表中移除
            if node_id in failed_nodes:
                failed_nodes.remove(node_id)
            # 重试成功后清除重试计数
            if node_id in retry_counts:
                del retry_counts[node_id]
        elif status == 'failed':
            if node_id not in failed_nodes:
                failed_nodes.append(node_id)
            # 不从完成列表中移除（失败节点可能曾经完成过，记录为失败状态）
            # 初始化重试计数（如果不存在）
            if node_id not in retry_counts:
                retry_counts[node_id] = 0

        metadata['completed_nodes'] = completed_nodes
        metadata['failed_nodes'] = failed_nodes
        metadata['retry_counts'] = retry_counts

        # 计算撰写进度（需要从 outline.json 获取总叶子节点数）
        total_leaves = 0
        outline_path = os.path.join(workspace_path, 'proposal_file', 'outline.json')
        if os.path.exists(outline_path):
            try:
                with open(outline_path, 'r', encoding='utf-8') as f:
                    outline = json.load(f)

                def count_leaves(node):
                    if not isinstance(node, dict):
                        return 0
                    if node.get('write_content', False):
                        return 1
                    count = 0
                    for child in node.get('children', []):
                        count += count_leaves(child)
                    return count

                total_leaves = count_leaves(outline)
            except Exception:
                pass

        writing_progress = 0
        if total_leaves > 0:
            writing_progress = round(len(completed_nodes) / total_leaves * 100)
        metadata['writing_progress'] = writing_progress
        metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if self._save_metadata(workspace_path, metadata):
            return {
                'success': True,
                'node_id': node_id,
                'status': status,
                'completed_nodes': completed_nodes,
                'failed_nodes': failed_nodes,
                'retry_counts': retry_counts,
                'writing_progress': writing_progress
            }
        else:
            return {'success': False, 'error': '保存 metadata.json 失败'}


# ==========================================================
# 便捷函数（供主控 Agent 直接调用）
# ==========================================================

def read_outline_and_materials(workspace_path: str) -> dict:
    """读取大纲和所有撰写素材"""
    skill = TechnicalWritingSkill()
    return skill.read_outline_and_materials(workspace_path)


def build_task_queue(workspace_path: str) -> dict:
    """根据 outline.json 构建撰写任务队列"""
    skill = TechnicalWritingSkill()
    return skill.build_task_queue(workspace_path)


def word_count_statistics(workspace_path: str) -> dict:
    """统计各章节字数，校验偏差"""
    skill = TechnicalWritingSkill()
    return skill.word_count_statistics(workspace_path)


def quality_self_check(workspace_path: str) -> dict:
    """执行质量自查"""
    skill = TechnicalWritingSkill()
    return skill.quality_self_check(workspace_path)


def generate_summary_report(workspace_path: str) -> dict:
    """生成撰写完成报告"""
    skill = TechnicalWritingSkill()
    return skill.generate_summary_report(workspace_path)


def update_metadata_status(workspace_path: str, status: str = '正文撰写完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = TechnicalWritingSkill()
    return skill.update_metadata_status(workspace_path, status)


def get_completed_nodes(workspace_path: str) -> dict:
    """获取已完成节点列表"""
    skill = TechnicalWritingSkill()
    return skill.get_completed_nodes(workspace_path)


def update_completed_nodes(workspace_path: str, node_id: str, status: str = 'completed') -> dict:
    """更新已完成节点列表"""
    skill = TechnicalWritingSkill()
    return skill.update_completed_nodes(workspace_path, node_id, status)


def identify_failed_nodes(workspace_path: str) -> dict:
    """自动识别失败节点（文件缺失/字数严重不足）并更新 metadata.json"""
    skill = TechnicalWritingSkill()
    return skill.identify_failed_nodes(workspace_path)


def update_retry_count(workspace_path: str, node_id: str, increment: int = 1) -> dict:
    """更新失败节点重试计数（达到上限则标记为 exhausted 需人工介入）"""
    skill = TechnicalWritingSkill()
    return skill.update_retry_count(workspace_path, node_id, increment)


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
