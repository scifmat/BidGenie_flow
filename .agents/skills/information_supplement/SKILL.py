# -*- coding: utf-8 -*-
"""
BidGenie Flow - 信息补充 Skill 执行脚本

功能：
1. 回填 metadata.json 中的「当前需撰写标段」「预期总字数」字段
2. 更新 metadata.json 项目状态
3. 读取提取文件供 Agent 分析招标文件要求
4. 校验 Supplementary_info.md 完整性（7 类信息是否齐全且无占位符）

注意：Supplementary_info.md 模板由 Agent 直接使用 Write 工具创建，
      不再由脚本生成。参考模板见 bid_flow_docs/附件1-项目结构与配置说明.md
"""

import os
import json
import re
from datetime import datetime


# Supplementary_info.md 的 7 类信息章节定义（用于校验）
SECTION_DEFINITIONS = {
    1: {'title': '投标人基本信息'},
    2: {'title': '预计开工日期及进度计划'},
    3: {'title': '投标人的资质情况'},
    4: {'title': '拟派技术人员的基本情况'},
    5: {'title': '拟投入的设备情况'},
    6: {'title': '投标人荣誉'},
    7: {'title': '其它信息'},
}

# 待补充占位符（校验用）
PLACEHOLDER = '{{待补充}}'

# 章节总数
TOTAL_SECTIONS = 7


class InformationSupplementSkill:
    """
    信息补充 Skill - 阶段三辅助工具

    为主控 Agent 提供 metadata.json 回填、提取文件读取、完整性校验等能力。
    Supplementary_info.md 模板由 Agent 直接创建，本脚本不再负责生成。
    """

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))

    # ==========================================================
    # metadata.json 操作
    # ==========================================================

    def update_metadata_package(self, workspace_path: str, package: str) -> dict:
        return self._update_metadata_field(workspace_path, '当前需撰写标段', package)

    def update_metadata_wordcount(self, workspace_path: str, word_count) -> dict:
        return self._update_metadata_field(workspace_path, '预期总字数', str(word_count))

    def update_metadata_status(self, workspace_path: str, status: str = '信息补充完成') -> dict:
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
            return {'success': True, 'status': status, 'updated_fields': ['项目状态', '状态更新时间']}
        except Exception as e:
            return {'success': False, 'error': f'更新 metadata.json 失败: {str(e)}'}

    def _update_metadata_field(self, workspace_path: str, field: str, value: str) -> dict:
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {}
            metadata[field] = value
            metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            return {'success': True, 'updated_fields': [field, '状态更新时间'], field: value}
        except Exception as e:
            return {'success': False, 'error': f'写入 metadata.json 失败: {str(e)}'}

    # ==========================================================
    # 提取文件读取（供 Agent 分析招标文件要求）
    # ==========================================================

    def read_extraction_for_supplementary(self, workspace_path: str, package: str) -> dict:
        extraction_path = os.path.join(workspace_path, 'extraction_file')
        common_path = os.path.join(extraction_path, 'common_file')
        package_path = os.path.join(extraction_path, 'packages_file', f'package_{package}')
        target_files = {
            'common_file/02_Eligibility_Review.md': os.path.join(common_path, '02_Eligibility_Review.md'),
            f'packages_file/package_{package}/06_Procurement_Content.md': os.path.join(package_path, '06_Procurement_Content.md'),
            f'packages_file/package_{package}/07_Evaluation_Criteria.md': os.path.join(package_path, '07_Evaluation_Criteria.md'),
            f'packages_file/package_{package}/08_Business_Requirements.md': os.path.join(package_path, '08_Business_Requirements.md'),
            f'packages_file/package_{package}/09_Technical_Requirements.md': os.path.join(package_path, '09_Technical_Requirements.md'),
        }
        files_content = {}
        missing_files = []
        for rel_path, abs_path in target_files.items():
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        files_content[rel_path] = f.read()
                except Exception as e:
                    files_content[rel_path] = f'读取失败: {str(e)}'
                    missing_files.append(rel_path)
            else:
                missing_files.append(rel_path)
        return {'success': len(missing_files) == 0, 'files': files_content, 'missing_files': missing_files}

    # ==========================================================
    # 完整性校验
    # ==========================================================

    def validate_supplementary_info(self, workspace_path: str) -> dict:
        file_path = os.path.join(workspace_path, 'Supplementary_info.md')
        if not os.path.exists(file_path):
            return {
                'success': False, 'valid': False, 'error': 'Supplementary_info.md 不存在',
                'existing_sections': [], 'missing_sections': list(range(1, TOTAL_SECTIONS + 1)),
                'incomplete_sections': [], 'empty_sections': [], 'section_details': {}
            }
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {
                'success': False, 'valid': False, 'error': f'读取文件失败: {str(e)}',
                'existing_sections': [], 'missing_sections': list(range(1, TOTAL_SECTIONS + 1)),
                'incomplete_sections': [], 'empty_sections': [], 'section_details': {}
            }

        # 预处理：剥离"填写说明"等非编号章节，避免其 {{待补充}} 文本污染最后一个编号章节的校验
        # "填写说明"章节格式为 ## 填写说明（非 ## 数字. 格式），位于文件末尾
        # 该章节内容为模板使用说明，包含 {{待补充}} 字样，会导致最后一节被误判为含有占位符
        fill_instruction_match = re.search(r'\n##\s*填写说明', content)
        if fill_instruction_match:
            content = content[:fill_instruction_match.start()]
        # 兜底：剥离所有非数字编号的 ## 章节（如 ## 注意事项、## 备注 等）
        # 仅保留 ## 数字. 格式的章节内容
        # 注意：\s* 必须放在 (?!\d+\.) 之后，否则 \s* 会回溯匹配空字符导致负向先行断言失效
        content = re.split(r'\n##(?!\s*\d+\.)', content)[0]

        existing_sections = []
        missing_sections = []
        incomplete_sections = []
        empty_sections = []
        section_details = {}

        for section_num in range(1, TOTAL_SECTIONS + 1):
            section_title = SECTION_DEFINITIONS[section_num]['title']
            section_pattern = r'##\s*' + str(section_num) + r'\.\s*' + re.escape(section_title)
            section_match = re.search(section_pattern, content)

            if not section_match:
                missing_sections.append(section_num)
                section_details[section_num] = {'title': section_title, 'exists': False, 'has_placeholder': False, 'is_empty': True}
                continue

            existing_sections.append(section_num)
            section_start = section_match.start()
            next_section_match = re.search(r'\n##\s*\d+\.', content[section_start + 1:])
            section_end = section_start + 1 + next_section_match.start() if next_section_match else len(content)
            section_text = content[section_start:section_end]
            has_placeholder = PLACEHOLDER in section_text

            if section_num == 1:
                table_placeholder_count = section_text.count(PLACEHOLDER)
                is_empty = table_placeholder_count >= 5
                if table_placeholder_count > 0:
                    incomplete_sections.append(section_num)
                if is_empty:
                    empty_sections.append(section_num)
            else:
                supplement_match = re.search(r'\*\*投标人补充：\*\*\s*\n(.*?)(?=\n##\s*\d+\.|$)', section_text, re.DOTALL)
                if supplement_match:
                    supplement_text = supplement_match.group(1).strip()
                    if PLACEHOLDER in supplement_text:
                        incomplete_sections.append(section_num)
                        is_empty = True
                    elif not supplement_text:
                        empty_sections.append(section_num)
                        is_empty = True
                    else:
                        is_empty = False
                else:
                    empty_sections.append(section_num)
                    is_empty = True

            section_details[section_num] = {
                'title': section_title, 'exists': True, 'has_placeholder': has_placeholder,
                'is_empty': is_empty if section_num > 1 else (section_text.count(PLACEHOLDER) >= 5)
            }

        valid = len(missing_sections) == 0 and len(incomplete_sections) == 0 and len(empty_sections) == 0
        return {
            'success': True, 'valid': valid,
            'existing_sections': existing_sections, 'missing_sections': missing_sections,
            'incomplete_sections': incomplete_sections, 'empty_sections': empty_sections,
            'section_details': section_details
        }


# ==========================================================
# 便捷函数（供主控 Agent 直接调用）
# ==========================================================

def update_metadata_package(workspace_path: str, package: str) -> dict:
    """回填 metadata.json 的「当前需撰写标段」字段"""
    skill = InformationSupplementSkill()
    return skill.update_metadata_package(workspace_path, package)


def update_metadata_wordcount(workspace_path: str, word_count) -> dict:
    """回填 metadata.json 的「预期总字数」字段"""
    skill = InformationSupplementSkill()
    return skill.update_metadata_wordcount(workspace_path, word_count)


def update_metadata_status(workspace_path: str, status: str = '信息补充完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = InformationSupplementSkill()
    return skill.update_metadata_status(workspace_path, status)


def read_extraction_for_supplementary(workspace_path: str, package: str) -> dict:
    """读取与 7 类补充信息相关的提取文件内容，供 Agent 分析"""
    skill = InformationSupplementSkill()
    return skill.read_extraction_for_supplementary(workspace_path, package)


def validate_supplementary_info(workspace_path: str) -> dict:
    """校验 Supplementary_info.md 完整性（7 类信息）"""
    skill = InformationSupplementSkill()
    return skill.validate_supplementary_info(workspace_path)


# ==========================================================
# 临时文件管理便捷函数（封装 TempManager，供 Agent 直接调用）
# ==========================================================


def get_temp_manager(project_id: str = None):
    """
    获取临时文件管理器实例

    Args:
        project_id: 项目ID（如项目编号），用于创建项目专属临时目录

    Returns:
        TempManager: 临时文件管理器实例
    """
    import sys
    import os
    # 将 .trae 添加到 sys.path 以解决前缀点号导入问题
    trae_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.trae'))
    if trae_path not in sys.path:
        sys.path.insert(0, trae_path)
    
    from utils.temp_manager import TempManager
    return TempManager(project_id)


def create_temp_dir(project_id: str = None, subdir: str = None) -> str:
    """
    创建临时目录

    Args:
        project_id: 项目ID（如项目编号）
        subdir: 子目录名称（如 'conversion', 'parsing'）

    Returns:
        str: 创建的临时目录路径
    """
    tm = get_temp_manager(project_id)
    return tm.create_temp_dir(subdir)


def save_temp_file(project_id: str, filename: str, content: str or bytes, subdir: str = None) -> str:
    """
    保存临时文件

    Args:
        project_id: 项目ID
        filename: 文件名
        content: 文件内容（字符串或字节）
        subdir: 子目录名称

    Returns:
        str: 保存的文件路径
    """
    tm = get_temp_manager(project_id)
    return tm.save_temp_file(filename, content, subdir)


def read_temp_file(project_id: str, filename: str, subdir: str = None, binary: bool = False) -> str or bytes:
    """
    读取临时文件

    Args:
        project_id: 项目ID
        filename: 文件名
        subdir: 子目录名称
        binary: 是否以二进制模式读取

    Returns:
        str or bytes: 文件内容
    """
    tm = get_temp_manager(project_id)
    return tm.read_temp_file(filename, subdir, binary)


def cleanup_temp(project_id: str = None, days: int = 7) -> int:
    """
    清理临时文件

    Args:
        project_id: 项目ID（不传则清理所有过期文件）
        days: 过期天数（默认7天）

    Returns:
        int: 清理的文件/目录数量
    """
    if project_id:
        tm = get_temp_manager(project_id)
        return tm.cleanup_project_temp()
    else:
        tm = get_temp_manager()
        return tm.cleanup_expired(days)
