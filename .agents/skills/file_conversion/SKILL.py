import os
import re
import json
import subprocess
from datetime import datetime
from pathlib import Path
from markitdown import MarkItDown


class FileConversionSkill:
    """
    文件转换 Skill - 将招标文件及附件转换为 Markdown 格式
    
    功能：
    1. 创建项目工作空间目录结构
    2. 将 .doc/.docx/.pdf 文件转换为 .md 格式
    3. 按规范命名并存储转换后的文件
    4. 生成转换错误报告
    5. 创建初始 metadata.json
    """
    
    SUPPORTED_EXTENSIONS = ['.doc', '.docx', '.pdf']
    
    # 文件名中需要清洗的非法/危险字符（Windows/Linux 均适用）
    # ; 在 shell 中为命令分隔符，: 在 Windows 中为盘符分隔符，其余为文件系统非法字符
    ILLEGAL_FILENAME_CHARS = [';', ':', '*', '?', '"', '<', '>', '|', '/', '\\']
    
    FILE_TYPES = {
        'bidding': ('01_Bidding_Documents.md', '招标文件'),
        'technical': ('02_Technical_Requirements.md', '技术要求附件'),
        'procurement': ('03_procurement_list.md', '采购清单'),
        'evaluation': ('04_Evaluation_Criteria.md', '评审标准附件'),
        'construction': ('05_Construction_design.md', '施工设计说明'),
        'proposal': ('06_Proposal_scheme.md', '方案建议书'),
    }
    
    def __init__(self):
        self.md = MarkItDown()
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    
    def sanitize_filename(self, filename: str) -> str:
        """
        清洗文件名中的特殊字符，确保文件名在后续处理（shell 命令、JSON 存储、路径拼接）中安全
        
        清洗规则：
        1. 将非法/危险字符（; : * ? " < > | / \\）替换为下划线 _
        2. 合并连续的下划线为单个下划线
        3. 去除首尾的下划线和空格
        4. 保留中文、字母、数字、空格、连字符、点号、圆括号
        
        Args:
            filename: 原始文件名（含扩展名）
        
        Returns:
            str: 清洗后的文件名
        """
        if not filename:
            return filename
        
        # 1. 替换非法/危险字符为下划线
        for char in self.ILLEGAL_FILENAME_CHARS:
            filename = filename.replace(char, '_')
        
        # 2. 合并连续下划线
        filename = re.sub(r'_+', '_', filename)
        
        # 3. 去除首尾下划线和空格
        filename = filename.strip('_ ')
        
        return filename if filename else 'unnamed'
    
    def create_workspace(self, timestamp: str) -> dict:
        """
        创建项目工作空间目录结构
        
        Args:
            timestamp: 时间戳（YYYYMMDD HHMMSS）
        
        Returns:
            dict: 包含工作空间路径和创建的目录列表
        """
        import random
        random_suffix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
        workspace_name = f"{timestamp}_{random_suffix}"
        workspace_path = os.path.join(self.project_root, 'bid_project', workspace_name)
        
        directories = [
            os.path.join(workspace_path, 'source_file'),
            os.path.join(workspace_path, 'extraction_file'),
            os.path.join(workspace_path, 'proposal_file'),
            os.path.join(workspace_path, 'review_file'),
            os.path.join(workspace_path, 'final_document_file'),
        ]
        
        created_dirs = []
        for dir_path in directories:
            os.makedirs(dir_path, exist_ok=True)
            created_dirs.append(dir_path)
        
        return {
            'workspace_path': workspace_path,
            'directories_created': created_dirs
        }
    
    def create_metadata(self, workspace_path: str, timestamp: str, 
                       converted_files: list, failed_files: list) -> str:
        """
        创建初始 metadata.json
        
        Args:
            workspace_path: 工作空间路径
            timestamp: 时间戳
            converted_files: 成功转换的文件列表
            failed_files: 失败的文件列表
        
        Returns:
            str: metadata.json 文件路径
        """
        metadata = {
            '项目编号': '',
            '项目名称': '',
            '采购方式': '',
            '是否分标段': '',
            '项目标段数': '',
            '当前需撰写标段': '',
            '预期总字数': '',
            '项目状态': '文件上传完成',
            '状态更新时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '创建时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '时间戳': timestamp,
            '工作空间路径': workspace_path,
            '源文件列表': [file['original'] for file in converted_files],
            '转换后文件': [file['converted'] for file in converted_files],
            '转换失败文件': [file['filename'] for file in failed_files],
        }
        
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return metadata_path
    
    def get_output_filename(self, index: int, original_name: str) -> str:
        """
        获取输出文件名（按上传顺序编码命名）
        
        Args:
            index: 文件序号（从1开始）
            original_name: 原始文件名
        
        Returns:
            str: 输出文件名（格式：01_source.md）
        """
        return f"{index:02d}_source.md"
    
    def rename_files(self, workspace_path: str, rename_map: dict) -> dict:
        """
        批量重命名 source_file 目录下的 .md 文件
        
        Args:
            workspace_path: 工作空间路径
            rename_map: 重命名映射（原文件名 -> 新文件名）
        
        Returns:
            dict: 重命名结果
        """
        source_dir = os.path.join(workspace_path, 'source_file')
        
        success_count = 0
        failed_count = 0
        renamed_files = []
        failed_files = []
        
        for old_name, new_name in rename_map.items():
            old_path = os.path.join(source_dir, old_name)
            new_path = os.path.join(source_dir, new_name)
            
            if not os.path.exists(old_path):
                failed_files.append({
                    'old_name': old_name,
                    'new_name': new_name,
                    'reason': '源文件不存在'
                })
                failed_count += 1
                continue
            
            if os.path.exists(new_path):
                failed_files.append({
                    'old_name': old_name,
                    'new_name': new_name,
                    'reason': '目标文件已存在'
                })
                failed_count += 1
                continue
            
            try:
                os.rename(old_path, new_path)
                renamed_files.append({
                    'old_name': old_name,
                    'new_name': new_name,
                    'success': True
                })
                success_count += 1
            except Exception as e:
                failed_files.append({
                    'old_name': old_name,
                    'new_name': new_name,
                    'reason': str(e)
                })
                failed_count += 1
        
        self.update_metadata_after_rename(workspace_path, rename_map)
        
        return {
            'success': failed_count == 0,
            'success_count': success_count,
            'failed_count': failed_count,
            'renamed_files': renamed_files,
            'failed_files': failed_files
        }
    
    def update_metadata_after_rename(self, workspace_path: str, rename_map: dict) -> None:
        """
        重命名后更新 metadata.json 中的文件名记录
        
        Args:
            workspace_path: 工作空间路径
            rename_map: 重命名映射
        """
        metadata_path = os.path.join(workspace_path, 'metadata.json')
        if not os.path.exists(metadata_path):
            return
        
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        converted_files = metadata.get('转换后文件', [])
        updated_converted = [rename_map.get(f, f) for f in converted_files]
        metadata['转换后文件'] = updated_converted
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def update_metadata_fields(self, workspace_path: str, fields: dict) -> dict:
        """
        更新 metadata.json 中的指定字段（供 Agent 回填关键信息使用）

        Agent 阅读转换后的 .md 文件后，提取项目编号、项目名称、采购方式、
        是否分标段、项目标段数等关键信息，调用本函数回填到 metadata.json。

        Args:
            workspace_path: 工作空间路径
            fields: dict - 需要更新的字段及值，例如：
                {
                    '项目编号': 'HBZB-2026-123456',
                    '项目名称': 'XXX信息系统集成项目',
                    '采购方式': '公开招标',
                    '是否分标段': '否',
                    '项目标段数': '1'
                }

        Returns:
            dict: 更新结果
        """
        metadata_path = os.path.join(workspace_path, 'metadata.json')

        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                return {'success': False, 'error': 'metadata.json 不存在'}

            updated_fields = {}
            for key, value in fields.items():
                if value:
                    metadata[key] = value
                    updated_fields[key] = value

            metadata['状态更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            return {
                'success': True,
                'updated_fields': updated_fields
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def convert_doc_to_docx(self, doc_path: str) -> str:
        """
        将 .doc 文件转换为 .docx（使用 libreoffice）
        
        Args:
            doc_path: .doc 文件路径
        
        Returns:
            str: 转换后的 .docx 文件路径，失败返回空字符串
        """
        try:
            docx_path = os.path.splitext(doc_path)[0] + '.docx'
            if os.path.exists(docx_path):
                return docx_path
            
            subprocess.run(
                ['libreoffice', '--headless', '--convert-to', 'docx', doc_path],
                check=True,
                capture_output=True,
                timeout=120
            )
            
            if os.path.exists(docx_path):
                return docx_path
            else:
                return ''
        except Exception as e:
            return ''
    
    def convert_single_file(self, file_path: str, output_path: str) -> dict:
        """
        转换单个文件
        
        Args:
            file_path: 输入文件路径
            output_path: 输出文件路径
        
        Returns:
            dict: 转换结果，包含 success、output_path、error
        """
        try:
            result = self.md.convert(file_path)
            
            if result and hasattr(result, 'text_content') and result.text_content:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result.text_content)
                return {
                    'success': True,
                    'output_path': output_path,
                    'error': None
                }
            else:
                return {
                    'success': False,
                    'output_path': output_path,
                    'error': '转换结果为空'
                }
        
        except Exception as e:
            return {
                'success': False,
                'output_path': output_path,
                'error': str(e)
            }
    
    def convert_documents(self, files: list) -> dict:
        """
        转换招标文件及附件，创建项目工作空间
        
        Args:
            files: 文件路径列表
        
        Returns:
            dict: 转换结果
        """
        timestamp = datetime.now().strftime('%Y%m%d %H%M%S')
        
        workspace_result = self.create_workspace(timestamp)
        workspace_path = workspace_result['workspace_path']
        source_dir = os.path.join(workspace_path, 'source_file')
        
        converted_files = []
        failed_files = []
        file_index = 1
        
        for file_path in files:
            if not os.path.exists(file_path):
                failed_files.append({
                    'filename': self.sanitize_filename(os.path.basename(file_path)),
                    'reason': '文件不存在'
                })
                continue
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self.SUPPORTED_EXTENSIONS:
                failed_files.append({
                    'filename': self.sanitize_filename(os.path.basename(file_path)),
                    'reason': f'不支持的格式：{ext}（支持 .doc/.docx/.pdf）'
                })
                continue
            
            original_name = os.path.basename(file_path)
            # 清洗原始文件名中的特殊字符，避免后续处理（shell 命令、JSON 引用等）出现问题
            original_name = self.sanitize_filename(original_name)
            output_filename = self.get_output_filename(file_index, original_name)
            file_index += 1
            
            output_path = os.path.join(source_dir, output_filename)
            
            actual_input_path = file_path
            
            if ext == '.doc':
                docx_path = self.convert_doc_to_docx(file_path)
                if docx_path:
                    actual_input_path = docx_path
                else:
                    failed_files.append({
                        'filename': original_name,
                        'reason': '.doc 格式转换失败，请安装 libreoffice 或手动转换为 .docx'
                    })
                    continue
            
            result = self.convert_single_file(actual_input_path, output_path)
            
            if result['success']:
                converted_files.append({
                    'original': original_name,
                    'converted': output_filename,
                    'path': output_path
                })
            else:
                failed_files.append({
                    'filename': original_name,
                    'reason': result['error']
                })
        
        error_report = self.generate_error_report(failed_files)
        
        self.create_metadata(workspace_path, timestamp, converted_files, failed_files)
        
        return {
            'success': len(failed_files) == 0,
            'workspace_path': workspace_path,
            'converted_files': converted_files,
            'failed_files': failed_files,
            'error_report': error_report,
            'metadata_created': True
        }
    
    def generate_error_report(self, failed_files: list) -> str:
        """
        生成错误报告
        
        Args:
            failed_files: 失败文件列表
        
        Returns:
            str: 错误报告文本
        """
        if not failed_files:
            return ''
        
        report = f"【文件解析失败报告】\n"
        report += f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += f"失败文件数量：{len(failed_files)}\n\n"
        report += "失败文件详情：\n"
        
        for i, item in enumerate(failed_files, 1):
            report += f"{i}. {item['filename']}\n"
            report += f"   原因：{item['reason']}\n"
            report += f"   建议：请重新上传该文件或提供替代文件\n\n"
        
        report += "【处理建议】\n"
        report += "1. 检查文件是否损坏\n"
        report += "2. 确认文件格式是否正确（.doc/.docx/.pdf）\n"
        report += "3. .doc 文件建议先转换为 .docx 格式\n"
        report += "4. PDF 扫描件无法提取文字，建议提供可复制的电子版\n"
        
        return report


def convert_documents(files: list) -> dict:
    """
    转换招标文件及附件的便捷函数
    
    Args:
        files: 文件路径列表
    
    Returns:
        dict: 转换结果
    """
    skill = FileConversionSkill()
    return skill.convert_documents(files)


def create_workspace(timestamp: str) -> dict:
    """
    创建工作空间的便捷函数
    
    Args:
        timestamp: 时间戳
    
    Returns:
        dict: 工作空间创建结果
    """
    skill = FileConversionSkill()
    return skill.create_workspace(timestamp)


def rename_files(workspace_path: str, rename_map: dict) -> dict:
    """
    批量重命名文件的便捷函数

    Args:
        workspace_path: 工作空间路径
        rename_map: 重命名映射（原文件名 -> 新文件名）

    Returns:
        dict: 重命名结果
    """
    skill = FileConversionSkill()
    return skill.rename_files(workspace_path, rename_map)


def update_metadata_fields(workspace_path: str, fields: dict) -> dict:
    """
    更新 metadata.json 中指定字段的便捷函数

    供 Agent 阅读转换后的 .md 文件后，回填项目编号、项目名称、采购方式、
    是否分标段、项目标段数等关键信息到 metadata.json。

    Args:
        workspace_path: 工作空间路径
        fields: dict - 需要更新的字段及值

    Returns:
        dict: 更新结果
    """
    skill = FileConversionSkill()
    return skill.update_metadata_fields(workspace_path, fields)


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
