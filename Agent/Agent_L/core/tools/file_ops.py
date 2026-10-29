"""文件操作工具集（10 个）。

工具返回格式统一为：
    {"success": True, "result": ...}
    {"success": False, "error": ...}
"""

from __future__ import annotations

import os
import shutil

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_directory",
            "description": "获取当前工作目录的绝对路径。用户询问当前所在目录时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出指定目录下的所有文件和子目录，并标注每一项是文件还是目录。不传 dir_path 时使用当前目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "要列出的目录路径，默认为当前目录",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_type",
            "description": "判断给定路径是文件还是目录。文件返回扩展名（无扩展名返回“无扩展名”），目录返回“directory”。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要判断的路径",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_content",
            "description": "读取纯文本文件的内容，使用 UTF-8 编码。二进制文件或非 UTF-8 文件会返回错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "在指定目录下创建新文件，可写入初始内容。父目录必须已存在，文件已存在时不会覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "文件所在目录的路径",
                    },
                    "file_name": {
                        "type": "string",
                        "description": "要创建的文件名，例如 note.txt",
                    },
                    "content": {
                        "type": "string",
                        "description": "文件初始内容，默认为空",
                    },
                },
                "required": ["dir_path", "file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑已存在的纯文本文件。mode 为 overwrite 时覆盖全部内容，为 append 时追加到文件末尾。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要编辑的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的内容",
                    },
                    "mode": {
                        "type": "string",
                        "description": "编辑模式：overwrite 覆盖，append 追加，默认 overwrite",
                        "enum": ["overwrite", "append"],
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "创建目录，支持多级嵌套路径。目录已存在时返回错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "要创建的目录路径",
                    }
                },
                "required": ["dir_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_directory",
            "description": "删除目录。非空目录会被递归删除，请谨慎使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    }
                },
                "required": ["dir_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_file",
            "description": "删除单个文件。目标是目录时返回错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "重命名文件或目录，只修改名称，不移动到其他位置。新名称已存在时返回错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {
                        "type": "string",
                        "description": "原文件或目录路径",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "新名称，只包含名称本身，不能包含路径分隔符",
                    },
                },
                "required": ["old_path", "new_name"],
            },
        },
    },
]


def get_current_directory():
    try:
        return {"success": True, "result": os.getcwd()}
    except Exception as e:
        return {"success": False, "error": f"获取当前目录失败：{e}"}


def list_directory(dir_path=None):
    try:
        target = os.path.abspath(dir_path if dir_path else os.getcwd())
        if not os.path.exists(target):
            return {"success": False, "error": f"目录不存在：{target}"}
        if not os.path.isdir(target):
            return {"success": False, "error": f"路径不是目录：{target}"}
        items = []
        for name in sorted(os.listdir(target)):
            full_path = os.path.join(target, name)
            items.append(
                {
                    "name": name,
                    "type": "目录" if os.path.isdir(full_path) else "文件",
                }
            )
        return {"success": True, "result": items}
    except Exception as e:
        return {"success": False, "error": f"列出目录失败：{e}"}


def get_file_type(file_path):
    try:
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"路径不存在：{target}"}
        if os.path.isdir(target):
            return {"success": True, "result": "directory"}
        ext = os.path.splitext(target)[1]
        return {"success": True, "result": ext if ext else "无扩展名"}
    except Exception as e:
        return {"success": False, "error": f"判断文件类型失败：{e}"}


def read_file_content(file_path):
    try:
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"文件不存在：{target}"}
        if not os.path.isfile(target):
            return {"success": False, "error": f"路径不是文件：{target}"}
        try:
            with open(target, "r", encoding="utf-8") as f:
                return {"success": True, "result": f.read()}
        except UnicodeDecodeError:
            return {
                "success": False,
                "error": "文件不是 UTF-8 编码的纯文本文件，无法读取",
            }
    except Exception as e:
        return {"success": False, "error": f"读取文件失败：{e}"}


def create_file(dir_path, file_name, content=""):
    try:
        target_dir = os.path.abspath(dir_path if dir_path else os.getcwd())
        if not os.path.exists(target_dir):
            return {"success": False, "error": f"父目录不存在：{target_dir}"}
        if not os.path.isdir(target_dir):
            return {"success": False, "error": f"路径不是目录：{target_dir}"}
        file_path = os.path.join(target_dir, file_name)
        if os.path.exists(file_path):
            return {"success": False, "error": f"文件已存在，不会覆盖：{file_path}"}
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "result": f"已创建文件：{file_path}"}
    except Exception as e:
        return {"success": False, "error": f"创建文件失败：{e}"}


def edit_file(file_path, content, mode="overwrite"):
    try:
        if mode not in ("overwrite", "append"):
            return {"success": False, "error": f"不支持的模式：{mode}，仅支持 overwrite 或 append"}
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"文件不存在：{target}"}
        if not os.path.isfile(target):
            return {"success": False, "error": f"路径不是文件：{target}"}
        open_mode = "w" if mode == "overwrite" else "a"
        with open(target, open_mode, encoding="utf-8") as f:
            f.write(content)
        action = "覆盖写入" if mode == "overwrite" else "追加写入"
        return {"success": True, "result": f"已{action}：{target}"}
    except Exception as e:
        return {"success": False, "error": f"编辑文件失败：{e}"}


def create_directory(dir_path):
    try:
        target = os.path.abspath(dir_path)
        if os.path.exists(target):
            if os.path.isdir(target):
                return {"success": False, "error": f"目录已存在：{target}"}
            return {"success": False, "error": f"路径已存在且不是目录：{target}"}
        os.makedirs(target)
        return {"success": True, "result": f"已创建目录：{target}"}
    except Exception as e:
        return {"success": False, "error": f"创建目录失败：{e}"}


def remove_directory(dir_path):
    try:
        target = os.path.abspath(dir_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"目录不存在：{target}"}
        if not os.path.isdir(target):
            return {"success": False, "error": f"路径不是目录：{target}"}
        shutil.rmtree(target)
        return {"success": True, "result": f"已删除目录：{target}"}
    except Exception as e:
        return {"success": False, "error": f"删除目录失败：{e}"}


def remove_file(file_path):
    try:
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"文件不存在：{target}"}
        if os.path.isdir(target):
            return {"success": False, "error": f"目标是目录，不能作为文件删除：{target}"}
        os.remove(target)
        return {"success": True, "result": f"已删除文件：{target}"}
    except Exception as e:
        return {"success": False, "error": f"删除文件失败：{e}"}


def rename_path(old_path, new_name):
    try:
        target = os.path.abspath(old_path)
        if not os.path.exists(target):
            return {"success": False, "error": f"原路径不存在：{target}"}
        if (
            not new_name
            or new_name in (".", "..")
            or os.path.basename(new_name) != new_name
            or "/" in new_name
            or "\\" in new_name
        ):
            return {"success": False, "error": f"新名称不合法：{new_name}，只能包含名称本身"}
        new_path = os.path.join(os.path.dirname(target), new_name)
        if os.path.exists(new_path):
            return {"success": False, "error": f"新名称已存在：{new_path}"}
        os.rename(target, new_path)
        return {"success": True, "result": f"已重命名：{target} -> {new_path}"}
    except Exception as e:
        return {"success": False, "error": f"重命名失败：{e}"}


TOOL_MAP = {
    "get_current_directory": get_current_directory,
    "list_directory": list_directory,
    "get_file_type": get_file_type,
    "read_file_content": read_file_content,
    "create_file": create_file,
    "edit_file": edit_file,
    "create_directory": create_directory,
    "remove_directory": remove_directory,
    "remove_file": remove_file,
    "rename_path": rename_path,
}
