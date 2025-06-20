import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel, Field

from .message import AIMessage, BasicMessage, SystemMessage, ToolMessage, UserMessage
from .tools.todo import TodoList
from .tui import console
from .utils import sanitize_filename


class Session(BaseModel):
    """Session model for managing conversation history and metadata."""

    messages: List[BasicMessage] = Field(default_factory=list)
    todo_list: TodoList = Field(default_factory=TodoList)
    work_dir: str
    source: Literal['user', 'subagent'] = 'user'
    session_id: str = ''
    append_message_hook: Optional[Callable] = None

    def __init__(
        self,
        work_dir: str,
        messages: Optional[List[BasicMessage]] = None,
        append_message_hook: Optional[Callable] = None,
        todo_list: Optional[TodoList] = None,
        source: Literal['user', 'subagent'] = 'user',
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            messages=messages or [],
            session_id=str(uuid.uuid4()),
            append_message_hook=append_message_hook,
            todo_list=todo_list or TodoList(),
            source=source,
        )

    def append_message(self, *msgs: BasicMessage) -> None:
        """Add messages to the session and save it."""
        self.messages.extend(msgs)
        self.save()
        if self.append_message_hook:
            self.append_message_hook(*msgs)

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None) -> Optional[BasicMessage]:
        """Get the last message with the specified role."""
        if role:
            return next((msg for msg in reversed(self.messages) if msg.role == role), None)
        return self.messages[-1] if self.messages else None

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None) -> Optional[BasicMessage]:
        """Get the first message with the specified role"""
        if role:
            return next((msg for msg in self.messages if msg.role == role), None)
        return self.messages[0] if self.messages else None

    def print_all(self):
        """Print all messages in the session"""
        for msg in self.messages:
            console.print(msg)

    def _get_session_dir(self) -> Path:
        """Get the directory path for storing session files."""
        return Path(self.work_dir) / '.klaude' / 'sessions'

    def _get_formatted_filename_prefix(self) -> str:
        """Generate formatted filename prefix with datetime and title."""
        created_at = getattr(self, '_created_at', time.time())
        dt = datetime.fromtimestamp(created_at)
        datetime_str = dt.strftime('%Y_%m%d_%H%M')

        first_user_msg = self.get_first_message(role='user')
        if first_user_msg:
            title = sanitize_filename(first_user_msg.content, max_length=20)
        else:
            title = 'untitled'

        return f'{datetime_str}{".SUBAGENT" if self.source == "subagent" else ""}.{title}'

    def _get_metadata_file_path(self) -> Path:
        """Get the file path for session metadata."""
        prefix = self._get_formatted_filename_prefix()
        return self._get_session_dir() / f'{prefix}.metadata.{self.session_id}.json'

    def _get_messages_file_path(self) -> Path:
        """Get the file path for session messages."""
        prefix = self._get_formatted_filename_prefix()
        return self._get_session_dir() / f'{prefix}.messages.{self.session_id}.json'

    def save(self) -> None:
        """Save session to local files (metadata and messages separately)"""
        # Only save sessions that have user messages (meaningful conversations)
        if not any(msg.role == 'user' for msg in self.messages):
            return

        try:
            if not self._get_session_dir().exists():
                self._get_session_dir().mkdir(parents=True)

            metadata_file = self._get_metadata_file_path()
            messages_file = self._get_messages_file_path()
            current_time = time.time()

            # Set created_at if not exists
            if not hasattr(self, '_created_at'):
                self._created_at = current_time

            # Save metadata (lightweight for fast listing)
            metadata = {
                'id': self.session_id,
                'work_dir': self.work_dir,
                'created_at': getattr(self, '_created_at', current_time),
                'updated_at': current_time,
                'message_count': len(self.messages),
                'todo_list': self.todo_list.model_dump(),
                'source': self.source,
            }

            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save messages (heavy data)
            messages_data = {
                'session_id': self.session_id,
                'messages': [msg.model_dump(exclude_none=True) for msg in self.messages],
            }

            with open(messages_file, 'w', encoding='utf-8') as f:
                json.dump(messages_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            console.print(f'[red]Failed to save session - error: {e}[/red]')

    @classmethod
    def load(cls, session_id: str, work_dir: str = os.getcwd()) -> Optional['Session']:
        """Load session from local files"""

        try:
            session_dir = cls(work_dir=work_dir)._get_session_dir()
            metadata_files = list(session_dir.glob(f'*.metadata.{session_id}.json'))
            messages_files = list(session_dir.glob(f'*.messages.{session_id}.json'))

            if not metadata_files or not messages_files:
                return None

            metadata_file = metadata_files[0]
            messages_file = messages_files[0]

            if not metadata_file.exists() or not messages_file.exists():
                return None

            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            with open(messages_file, 'r', encoding='utf-8') as f:
                messages_data = json.load(f)

            messages = []
            tool_calls_dict = {}
            for msg_data in messages_data.get('messages', []):
                role = msg_data.get('role')
                if role == 'system':
                    messages.append(SystemMessage(**msg_data))
                elif role == 'user':
                    messages.append(UserMessage(**msg_data))
                elif role == 'assistant':
                    ai_msg = AIMessage(**msg_data)
                    if ai_msg.tool_calls:
                        for tool_call_id, tool_call in ai_msg.tool_calls.items():
                            tool_calls_dict[tool_call_id] = tool_call
                    messages.append(ai_msg)
                elif role == 'tool':
                    tool_call_id = msg_data.get('tool_call_id')
                    if tool_call_id and tool_call_id in tool_calls_dict:
                        msg_data['tool_call_cache'] = tool_calls_dict[tool_call_id]
                    else:
                        raise ValueError(f'Tool call {tool_call_id} not found')
                    messages.append(ToolMessage(**msg_data))

            todo_list_data = metadata.get('todo_list', [])
            if isinstance(todo_list_data, list):
                todo_list = TodoList(root=todo_list_data)
            else:
                todo_list = TodoList()

            session = cls(work_dir=metadata['work_dir'], messages=messages, todo_list=todo_list)
            session.session_id = metadata['id']
            session._created_at = metadata.get('created_at')
            return session

        except Exception as e:
            console.print(f'[red]Failed to load session {session_id}: {e}[/red]')
            return None

    def fork(self) -> 'Session':
        forked_session = Session(
            work_dir=self.work_dir,
            messages=self.messages.copy(),  # Copy the messages list
            todo_list=self.todo_list.model_copy(),
        )
        return forked_session

    @classmethod
    def load_session_list(cls, work_dir: str = os.getcwd()) -> List[dict]:
        """Load a list of session metadata from the specified directory."""
        try:
            session_dir = cls(work_dir=work_dir)._get_session_dir()
            if not session_dir.exists():
                return []
            sessions = []
            for metadata_file in session_dir.glob('*.metadata.*.json'):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    if metadata.get('source', 'user') == 'subagent':
                        continue
                    sessions.append(
                        {
                            'id': metadata['id'],
                            'work_dir': metadata['work_dir'],
                            'created_at': metadata.get('created_at'),
                            'updated_at': metadata.get('updated_at'),
                            'message_count': metadata.get('message_count', 0),
                            'source': metadata.get('source', 'user'),
                        }
                    )
                except Exception as e:
                    console.print(f'[yellow]Warning: Failed to read metadata file {metadata_file}: {e}[/yellow]')
                    continue
            sessions.sort(key=lambda x: x.get('updated_at', 0), reverse=True)
            return sessions

        except Exception as e:
            console.print(f'[red]Failed to list sessions: {e}[/red]')
            return []

    @classmethod
    def get_latest_session(cls, work_dir: str = os.getcwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        sessions = cls.load_session_list(work_dir)
        if not sessions:
            return None
        latest_session = sessions[0]
        return cls.load(latest_session['id'], work_dir)
