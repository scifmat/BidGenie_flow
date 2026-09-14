#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidGenie Flow - 临时文件管理工具

功能：
1. 创建项目专属临时目录（基于时间戳和项目ID）
2. 安全写入/读取临时文件
3. 自动清理过期临时文件
4. 提供统一的临时文件路径管理

使用方式：
from temp_manager import TempManager

tm = TempManager(project_id='HBZB-2026-123456')
temp_dir = tm.create_temp_dir()
file_path = tm.save_temp_file('converted_doc.txt', content)
content = tm.read_temp_file('converted_doc.txt')
tm.cleanup_expired(days=3)
"""

import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path


class TempManager:
    """
    临时文件管理器
    
    在系统临时目录下创建项目专属的临时文件夹，避免工作空间污染。
    """
    
    def __init__(self, project_id: str = None):
        """
        初始化临时文件管理器
        
        Args:
            project_id: 项目ID（如项目编号），用于创建项目专属临时目录
        """
        self.project_id = project_id or 'bidgenie_flow'
        self.system_temp_dir = tempfile.gettempdir()
        self.base_temp_dir = os.path.join(self.system_temp_dir, 'bidgenie_flow')
        
        # 确保基础临时目录存在
        os.makedirs(self.base_temp_dir, exist_ok=True)
    
    def get_project_temp_dir(self) -> str:
        """
        获取项目专属临时目录路径
        
        Returns:
            str: 项目临时目录路径
        """
        # 使用项目ID创建子目录
        project_dir = os.path.join(self.base_temp_dir, self.project_id)
        os.makedirs(project_dir, exist_ok=True)
        return project_dir
    
    def create_temp_dir(self, subdir: str = None) -> str:
        """
        创建临时子目录
        
        Args:
            subdir: 子目录名称，如 'conversion', 'parsing' 等
        
        Returns:
            str: 创建的临时目录路径
        """
        project_dir = self.get_project_temp_dir()
        
        if subdir:
            target_dir = os.path.join(project_dir, subdir)
        else:
            # 生成时间戳子目录
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            target_dir = os.path.join(project_dir, timestamp)
        
        os.makedirs(target_dir, exist_ok=True)
        return target_dir
    
    def save_temp_file(self, filename: str, content: str or bytes, subdir: str = None) -> str:
        """
        保存临时文件
        
        Args:
            filename: 文件名
            content: 文件内容（字符串或字节）
            subdir: 子目录名称
        
        Returns:
            str: 保存的文件路径
        """
        if subdir:
            temp_dir = os.path.join(self.get_project_temp_dir(), subdir)
        else:
            temp_dir = self.get_project_temp_dir()
        
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, filename)
        
        try:
            if isinstance(content, str):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            else:
                with open(file_path, 'wb') as f:
                    f.write(content)
            return file_path
        except Exception as e:
            raise RuntimeError(f"保存临时文件失败: {str(e)}")
    
    def read_temp_file(self, filename: str, subdir: str = None, binary: bool = False) -> str or bytes:
        """
        读取临时文件
        
        Args:
            filename: 文件名
            subdir: 子目录名称
            binary: 是否以二进制模式读取
        
        Returns:
            str or bytes: 文件内容
        """
        if subdir:
            file_path = os.path.join(self.get_project_temp_dir(), subdir, filename)
        else:
            file_path = os.path.join(self.get_project_temp_dir(), filename)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"临时文件不存在: {file_path}")
        
        try:
            if binary:
                with open(file_path, 'rb') as f:
                    return f.read()
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            raise RuntimeError(f"读取临时文件失败: {str(e)}")
    
    def list_temp_files(self, subdir: str = None) -> list:
        """
        列出临时目录中的文件
        
        Args:
            subdir: 子目录名称
        
        Returns:
            list: 文件路径列表
        """
        if subdir:
            temp_dir = os.path.join(self.get_project_temp_dir(), subdir)
        else:
            temp_dir = self.get_project_temp_dir()
        
        if not os.path.exists(temp_dir):
            return []
        
        files = []
        for item in os.listdir(temp_dir):
            item_path = os.path.join(temp_dir, item)
            if os.path.isfile(item_path):
                files.append(item_path)
        return sorted(files)
    
    def cleanup_project_temp(self) -> int:
        """
        清理当前项目的所有临时文件
        
        Returns:
            int: 清理的文件/目录数量
        """
        project_dir = self.get_project_temp_dir()
        count = 0
        
        if os.path.exists(project_dir):
            for item in os.listdir(project_dir):
                item_path = os.path.join(project_dir, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    count += 1
                except Exception:
                    pass
        
        return count
    
    def cleanup_expired(self, days: int = 7) -> int:
        """
        清理过期的临时文件（按创建时间判断）
        
        Args:
            days: 过期天数，超过此天数的文件将被清理
        
        Returns:
            int: 清理的文件/目录数量
        """
        count = 0
        cutoff_time = datetime.now() - timedelta(days=days)
        
        # 遍历所有项目目录
        if os.path.exists(self.base_temp_dir):
            for project_name in os.listdir(self.base_temp_dir):
                project_dir = os.path.join(self.base_temp_dir, project_name)
                if not os.path.isdir(project_dir):
                    continue
                
                for item in os.listdir(project_dir):
                    item_path = os.path.join(project_dir, item)
                    try:
                        # 获取文件/目录的修改时间
                        mtime = os.path.getmtime(item_path)
                        mtime_dt = datetime.fromtimestamp(mtime)
                        
                        if mtime_dt < cutoff_time:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                            count += 1
                    except Exception:
                        pass
        
        return count
    
    def get_temp_path(self, filename: str, subdir: str = None) -> str:
        """
        获取临时文件的完整路径（不创建文件）
        
        Args:
            filename: 文件名
            subdir: 子目录名称
        
        Returns:
            str: 文件路径
        """
        if subdir:
            return os.path.join(self.get_project_temp_dir(), subdir, filename)
        else:
            return os.path.join(self.get_project_temp_dir(), filename)


# 便捷函数

def get_temp_manager(project_id: str = None) -> TempManager:
    """获取临时文件管理器实例"""
    return TempManager(project_id)


def create_temp_dir(project_id: str = None, subdir: str = None) -> str:
    """创建临时目录"""
    tm = TempManager(project_id)
    return tm.create_temp_dir(subdir)


def save_temp_file(project_id: str, filename: str, content: str or bytes, subdir: str = None) -> str:
    """保存临时文件"""
    tm = TempManager(project_id)
    return tm.save_temp_file(filename, content, subdir)


def cleanup_expired_temp(days: int = 7) -> int:
    """清理过期临时文件"""
    tm = TempManager()
    return tm.cleanup_expired(days)


if __name__ == '__main__':
    # 测试示例
    tm = TempManager('HBZB-2026-123456')
    
    # 创建临时目录
    temp_dir = tm.create_temp_dir('test')
    print(f"创建临时目录: {temp_dir}")
    
    # 保存临时文件
    file_path = tm.save_temp_file('test.txt', 'Hello, BidGenie Flow!', 'test')
    print(f"保存临时文件: {file_path}")
    
    # 读取临时文件
    content = tm.read_temp_file('test.txt', 'test')
    print(f"读取临时文件内容: {content}")
    
    # 列出临时文件
    files = tm.list_temp_files('test')
    print(f"临时文件列表: {files}")
    
    # 清理测试文件
    count = tm.cleanup_project_temp()
    print(f"清理临时文件数量: {count}")
