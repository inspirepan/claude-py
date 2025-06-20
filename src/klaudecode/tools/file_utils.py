import difflib
import hashlib
import os
import re
import shutil
from typing import Dict, List, Tuple

from rich.console import Group

"""
- File validation functions (existence, cache status)
- Content processing functions (string replacement, occurrence counting)
- Backup management (creation, restoration, cleanup)
- Diff generation and context snippet display
- Formatting tools (line numbers, content truncation)
- File system operations (directory creation, text file identification)
"""

FILE_CACHE: Dict[str, str] = {}

TRUNCATE_CHAR_LIMIT = 5000
TRUNCATE_LINE_LIMIT = 1000
FILE_NOT_READ_ERROR = 'File has not been read yet. Read it first before writing to it.'
FILE_MODIFIED_ERROR = 'File has been modified externally. Either by user or a linter. Read it first before writing to it.'


def validate_file_exists(file_path: str) -> Tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, f'File does not exist: {file_path}'
    if not os.path.isfile(file_path):
        return False, f'Path is not a file: {file_path}'
    return True, ''


def validate_file_cache(file_path: str) -> Tuple[bool, str]:
    if file_path not in FILE_CACHE:
        return False, FILE_NOT_READ_ERROR

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            current_content = f.read()
        current_hash = hashlib.md5(current_content.encode()).hexdigest()
        cached_hash = FILE_CACHE[file_path]
        if current_hash != cached_hash:
            return False, FILE_MODIFIED_ERROR
    except Exception:
        return False, FILE_NOT_READ_ERROR

    return True, ''


def cache_file_content(file_path: str, content: str):
    FILE_CACHE[file_path] = hashlib.md5(content.encode()).hexdigest()


def count_occurrences(content: str, search_string: str) -> int:
    return content.count(search_string)


def replace_string_in_content(content: str, old_string: str, new_string: str, replace_all: bool = False) -> Tuple[str, int]:
    if replace_all:
        new_content = content.replace(old_string, new_string)
        count = content.count(old_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
        count = 1 if old_string in content else 0

    return new_content, count


def create_backup(file_path: str) -> str:
    backup_path = f'{file_path}.backup'
    try:
        shutil.copy2(file_path, backup_path)
        return backup_path
    except Exception as e:
        raise Exception(f'Failed to create backup: {str(e)}')


def restore_backup(file_path: str, backup_path: str):
    try:
        shutil.move(backup_path, file_path)
    except Exception as e:
        raise Exception(f'Failed to restore backup: {str(e)}')


def cleanup_backup(backup_path: str):
    try:
        if os.path.exists(backup_path):
            os.remove(backup_path)
    except Exception:
        pass


def generate_diff_lines(old_content: str, new_content: str) -> List[str]:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
        )
    )

    return diff_lines


def truncate_content(numbered_lines: List[Tuple[int, str]], char_limit: int = TRUNCATE_CHAR_LIMIT, line_limit: int = TRUNCATE_LINE_LIMIT) -> Tuple[List[Tuple[int, str]], int]:
    total_char_count = sum(len(line_content) for _, line_content in numbered_lines)
    if total_char_count <= char_limit and len(numbered_lines) <= line_limit:
        return numbered_lines, 0
    truncated_lines = []
    char_count = 0
    remaining_line_count = 0
    for i, (line_num, line_content) in enumerate(numbered_lines):
        if i >= line_limit:
            remaining_line_count = len(numbered_lines) - i
            break
        if char_count + len(line_content) + 1 > char_limit:
            remaining_line_count = len(numbered_lines) - i
            break
        truncated_lines.append((line_num, line_content))
        char_count += len(line_content) + 1
    return truncated_lines, remaining_line_count


def ensure_directory_exists(file_path: str):
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def read_file_content(file_path: str, encoding: str = 'utf-8') -> Tuple[str, str]:
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        return content, ''
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return content, 'Warning: File decoded using latin-1 encoding'
        except Exception as e:
            return '', f'Failed to read file: {str(e)}'
    except Exception as e:
        return '', f'Failed to read file: {str(e)}'


def write_file_content(file_path: str, content: str, encoding: str = 'utf-8') -> str:
    try:
        ensure_directory_exists(file_path)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return ''
    except Exception as e:
        return f'Failed to write file: {str(e)}'


def get_edit_context_snippet(new_content: str, new_string: str, old_content: str, old_string: str, context_lines: int = 5) -> str:
    """
    Smart context snippet for edit results with fallback logic:
    1. Try to find new_string in new_content
    2. If not found, find where old_string was and show that area in new_content
    3. If still not found, show first few lines of new_content
    Returns cat -n style output format
    """
    # First try: find new_string in new content
    if new_string in new_content:
        lines = new_content.splitlines()
        for i, line in enumerate(lines):
            if new_string in line:
                start_idx = max(0, i - context_lines)
                end_idx = min(len(lines), i + context_lines + 1)
                context_lines_slice = lines[start_idx:end_idx]
                start_line_num = start_idx + 1

                snippet_lines = []
                for j, line_content in enumerate(context_lines_slice):
                    line_num = start_line_num + j
                    snippet_lines.append(f'     {line_num:>3}\t{line_content}')
                return '\n'.join(snippet_lines)

    # Second try: find where old_string was and show that area in new content
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    old_line_idx = -1
    for i, line in enumerate(old_lines):
        if old_string in line:
            old_line_idx = i
            break

    if old_line_idx != -1 and old_line_idx < len(new_lines):
        start_idx = max(0, old_line_idx - context_lines)
        end_idx = min(len(new_lines), old_line_idx + context_lines + 1)
        context_lines_slice = new_lines[start_idx:end_idx]
        start_line_num = start_idx + 1

        snippet_lines = []
        for j, line_content in enumerate(context_lines_slice):
            line_num = start_line_num + j
            snippet_lines.append(f'     {line_num:>3}\t{line_content}')
        return '\n'.join(snippet_lines)

    # Last fallback: show first few lines of the file
    first_lines = new_content.splitlines()[:10]
    snippet_lines = []
    for i, line_content in enumerate(first_lines):
        snippet_lines.append(f'     {i + 1:>3}\t{line_content}')
    return '\n'.join(snippet_lines)


def render_diff_lines(diff_lines: List[str]):
    if not diff_lines:
        return ''

    old_line_num = 1
    new_line_num = 1
    width = 3

    lines = []
    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                old_line_num = int(match.group(1))
                new_line_num = int(match.group(2))
        elif line.startswith('-'):
            removed_line = line[1:].strip()
            lines.append(f'[diff_removed]{old_line_num:{width}d}:-  {removed_line}[/diff_removed]')
            old_line_num += 1
        elif line.startswith('+'):
            added_line = line[1:].strip()
            lines.append(f'[diff_added]{new_line_num:{width}d}:+  {added_line}[/diff_added]')
            new_line_num += 1
        elif line.startswith(' '):
            context_line = line[1:].strip()
            lines.append(f'{old_line_num:{width}d}:   {context_line}')
            old_line_num += 1
            new_line_num += 1
        else:
            lines.append(line)
    return Group(*lines)
