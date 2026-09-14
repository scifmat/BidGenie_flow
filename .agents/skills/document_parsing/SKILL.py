import os
import json
import re
from datetime import datetime
from pathlib import Path


class DocumentParsingSkill:
    """
    文档解析 Skill - 主控 Agent 协调子智能体提取信息的辅助工具

    功能：
    1. 创建 extraction_file 目录结构
    2. 提供模板路径查询
    3. 校验提取文件存在性
    4. 从提取结果回填元数据到 metadata.json
    5. 更新项目状态
    """

    COMMON_FILES = [
        '01_Basic_Information.md',
        '02_Eligibility_Review.md',
        '03_Invalid_Bid_Item.md',
        '04_Compilation_Requirements.md',
        '05_Substantive_Response.md'
    ]

    PACKAGE_FILES = [
        '06_Procurement_Content.md',
        '07_Evaluation_Criteria.md',
        '08_Business_Requirements.md',
        '09_Technical_Requirements.md'
    ]

    def __init__(self):
        self.skill_root = os.path.abspath(os.path.dirname(__file__))
        self.project_root = os.path.abspath(os.path.join(self.skill_root, '..', '..', '..'))

    def get_template_path(self, template_name: str) -> str:
        """
        获取参考模板文件路径

        Args:
            template_name: 模板文件名

        Returns:
            str: 模板文件路径
        """
        if template_name in self.COMMON_FILES:
            return os.path.join(self.skill_root, 'templates', 'common_file', template_name)
        elif template_name in self.PACKAGE_FILES:
            return os.path.join(self.skill_root, 'templates', 'packages_file', template_name)
        else:
            return ''

    def get_all_template_paths(self) -> dict:
        """
        获取所有模板文件路径

        Returns:
            dict: 模板分类及路径
        """
        result = {
            'common_file': [],
            'packages_file': []
        }

        for file_name in self.COMMON_FILES:
            result['common_file'].append(self.get_template_path(file_name))

        for file_name in self.PACKAGE_FILES:
            result['packages_file'].append(self.get_template_path(file_name))

        return result

    def create_extraction_structure(self, workspace_path: str, package_count: int = 1) -> dict:
        """
        创建 extraction_file 目录结构

        Args:
            workspace_path: 工作空间路径
            package_count: 标段数量（默认1）

        Returns:
            dict: 创建结果
        """
        extraction_path = os.path.join(workspace_path, 'extraction_file')
        common_path = os.path.join(extraction_path, 'common_file')
        packages_path = os.path.join(extraction_path, 'packages_file')

        directories_created = []

        os.makedirs(common_path, exist_ok=True)
        directories_created.append(common_path)

        os.makedirs(packages_path, exist_ok=True)
        directories_created.append(packages_path)

        for i in range(1, package_count + 1):
            package_dir = os.path.join(packages_path, f'package_{i}')
            os.makedirs(package_dir, exist_ok=True)
            directories_created.append(package_dir)

        return {
            'success': True,
            'directories_created': directories_created,
            'extraction_path': extraction_path
        }

    def check_extraction_files(self, extraction_path: str, package_count: int = 1) -> dict:
        """
        检查提取文件存在性与基础内容有效性

        - 检查文件是否存在
        - 检查文件是否非空（>0 bytes）
        - 检查文件是否包含至少一个 Markdown 标题行（以 # 开头）

        Args:
            extraction_path: extraction_file 路径
            package_count: 标段数量

        Returns:
            dict: 检查结果
        """
        existing_files = []
        missing_files = []
        empty_files = []
        invalid_files = []

        common_path = os.path.join(extraction_path, 'common_file')
        packages_path = os.path.join(extraction_path, 'packages_file')

        def check_file(file_path: str, rel_path: str) -> bool:
            """检查单个文件：存在性 → 非空 → Markdown标题"""
            if not os.path.exists(file_path):
                missing_files.append(rel_path)
                return False

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                empty_files.append(rel_path)
                return False

            # 轻量级 Markdown 有效性：检查是否有标题行
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if not re.search(r'^#+\s', content, re.MULTILINE):
                    invalid_files.append(rel_path)
                    return False
            except Exception:
                invalid_files.append(rel_path)
                return False

            existing_files.append(rel_path)
            return True

        for file_name in self.COMMON_FILES:
            file_path = os.path.join(common_path, file_name)
            check_file(file_path, f'common_file/{file_name}')

        for package_num in range(1, package_count + 1):
            package_path = os.path.join(packages_path, f'package_{package_num}')
            for file_name in self.PACKAGE_FILES:
                file_path = os.path.join(package_path, file_name)
                check_file(file_path, f'packages_file/package_{package_num}/{file_name}')

        all_valid = len(missing_files) == 0 and len(empty_files) == 0 and len(invalid_files) == 0
        total_expected = len(self.COMMON_FILES) + len(self.PACKAGE_FILES) * package_count

        return {
            'valid': all_valid,
            'existing_files': existing_files,
            'missing_files': missing_files,
            'empty_files': empty_files,
            'invalid_files': invalid_files,
            'total_expected': total_expected,
            'total_existing': len(existing_files)
        }

    def update_metadata_from_extraction(self, workspace_path: str, package_count: int = 1) -> dict:
        """
        校验 01_Basic_Information.md 中的信息与 metadata.json 的一致性

        ⚠️ 注意：项目编号、项目名称、采购方式、是否分标段、项目标段数
        已在阶段一由 Agent 从招标文件中提取并回填到 metadata.json。
        本函数不再覆盖这些字段，仅读取提取文件进行一致性校验，
        返回对比结果供 Agent 参考判断。

        支持两种表格格式：
        - 行标签式：| 字段 | 值 |
        - 表头列式：| 字段 | 字段 | ... |
                  | 值   | 值   | ... |

        Args:
            workspace_path: 工作空间路径
            package_count: 标段数量（默认1）

        Returns:
            dict: 校验结果，包含提取文件中的值和 metadata.json 中的值
        """
        info_path = os.path.join(workspace_path, 'extraction_file', 'common_file', '01_Basic_Information.md')
        metadata_path = os.path.join(workspace_path, 'metadata.json')

        if not os.path.exists(info_path):
            return {'success': False, 'error': '01_Basic_Information.md 不存在'}

        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {'success': False, 'error': f'读取提取文件失败: {str(e)}'}

        # 定义需要提取的字段映射：表格中的字段名 → metadata.json 中的键
        field_mapping = {
            '项目编号': '项目编号',
            '项目名称': '项目名称',
            '采购方式': '采购方式',
        }

        extracted_fields = {}
        lines = content.split('\n')

        # 方法1：解析行标签式表格（| 字段名 | 字段值 | ...）
        for line in lines:
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                parts = [p for p in parts if p]
                if len(parts) >= 2:
                    # 去除字段名首尾空格，避免前导空格导致字段匹配失败
                    label = parts[0].strip()
                    value = parts[1].strip()
                    if label in ('---', ':-', '--', '字段', '项目属性', '类别', '类型'):
                        continue
                    if label in field_mapping and value:
                        metadata_key = field_mapping[label]
                        extracted_fields[metadata_key] = value

        # 方法2：解析表头列式表格，用正则补充提取
        if '项目编号' not in extracted_fields:
            match = re.search(r'项目编号[：:]\s*(\S+)', content)
            if match:
                extracted_fields['项目编号'] = match.group(1).strip()

        if '项目名称' not in extracted_fields:
            match = re.search(r'项目名称[：:]\s*(.+?)(?:\n|$)', content)
            if match:
                extracted_fields['项目名称'] = match.group(1).strip()

        # 读取 metadata.json 中已有的值（阶段一已回填，不再覆盖）
        metadata_values = {}
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                for key in ('项目编号', '项目名称', '采购方式', '是否分标段', '项目标段数'):
                    metadata_values[key] = metadata.get(key, '')
            except Exception:
                pass

        # 一致性校验：对比提取文件中的值与 metadata.json 中的值
        inconsistencies = {}
        for key, extracted_value in extracted_fields.items():
            metadata_value = metadata_values.get(key, '')
            if metadata_value and extracted_value and metadata_value != extracted_value:
                inconsistencies[key] = {
                    'metadata_value': metadata_value,
                    'extraction_value': extracted_value
                }

        return {
            'success': True,
            'extracted_fields': extracted_fields,
            'metadata_values': metadata_values,
            'inconsistencies': inconsistencies,
            'note': '项目编号、项目名称、采购方式、是否分标段、项目标段数已在阶段一回填，本函数仅做一致性校验，不覆盖现有值'
        }

    def update_metadata_status(self, workspace_path: str, status: str = '文件分析完成') -> dict:
        """
        更新 metadata.json 的项目状态

        Args:
            workspace_path: 工作空间路径
            status: 项目状态值（默认：文件分析完成）

        Returns:
            dict: 更新结果
        """
        metadata_path = os.path.join(workspace_path, 'metadata.json')

        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {
                    '项目状态': status,
                    '状态更新时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    '创建时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

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
            return {
                'success': False,
                'error': str(e)
            }


# 便捷函数

def create_extraction_structure(workspace_path: str, package_count: int = 1) -> dict:
    """创建 extraction_file 目录结构"""
    skill = DocumentParsingSkill()
    return skill.create_extraction_structure(workspace_path, package_count)


def check_extraction_files(extraction_path: str, package_count: int = 1) -> dict:
    """检查提取文件存在性"""
    skill = DocumentParsingSkill()
    return skill.check_extraction_files(extraction_path, package_count)


def update_metadata_from_extraction(workspace_path: str, package_count: int = 1) -> dict:
    """校验 01_Basic_Information.md 与 metadata.json 的一致性（不覆盖阶段一已回填的字段）"""
    skill = DocumentParsingSkill()
    return skill.update_metadata_from_extraction(workspace_path, package_count)


def update_metadata_status(workspace_path: str, status: str = '文件分析完成') -> dict:
    """更新 metadata.json 项目状态"""
    skill = DocumentParsingSkill()
    return skill.update_metadata_status(workspace_path, status)


def get_template_path(template_name: str) -> str:
    """获取参考模板路径"""
    skill = DocumentParsingSkill()
    return skill.get_template_path(template_name)


def get_all_template_paths() -> dict:
    """获取所有模板文件路径"""
    skill = DocumentParsingSkill()
    return skill.get_all_template_paths()


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