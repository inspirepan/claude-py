import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from .tui import console, format_style

"""
Unified configuration management system
Priority: CLI args > Environment variables > Config file > Default values
"""

# Default value constants
DEFAULT_CONTEXT_WINDOW_THRESHOLD = 200000
DEFAULT_MODEL_NAME = 'claude-sonnet-4-20250514'
DEFAULT_BASE_URL = 'https://api.anthropic.com/v1/'
DEFAULT_MODEL_AZURE = False
DEFAULT_MAX_TOKENS = 8196
DEFAULT_EXTRA_HEADER = {}
DEFAULT_ENABLE_THINKING = False

T = TypeVar('T')


@dataclass
class ConfigValue(Generic[T]):
    """Configuration value with source information"""

    value: Optional[T]
    source: str

    def __bool__(self) -> bool:
        return self.value is not None


class ConfigModel(BaseModel):
    """Pydantic model for configuration with sources"""

    api_key: Optional[ConfigValue[str]] = None
    model_name: Optional[ConfigValue[str]] = None
    base_url: Optional[ConfigValue[str]] = None
    model_azure: Optional[ConfigValue[bool]] = None
    max_tokens: Optional[ConfigValue[int]] = None
    context_window_threshold: Optional[ConfigValue[int]] = None
    extra_header: Optional[ConfigValue[Union[Dict, str]]] = None
    enable_thinking: Optional[ConfigValue[bool]] = None

    def __init__(self, source: str = 'unknown', **data):
        # Convert plain values to ConfigValue objects with source
        config_values = {}
        for key, value in data.items():
            if value is not None:
                config_values[key] = ConfigValue(value=value, source=source)
        super().__init__(**config_values)

    def __rich__(self):
        """Rich display for configuration model"""
        table = Table.grid(padding=(0, 1))
        table.add_column(width=1, no_wrap=True)  # Status
        table.add_column(min_width=10, no_wrap=True)  # Setting name
        table.add_column(min_width=14)  # Value
        table.add_column()  # Source

        config_items = [
            ('api_key', 'API Key'),
            ('model_name', 'Model'),
            ('base_url', 'Base URL'),
            ('model_azure', 'Azure Mode'),
            ('max_tokens', 'Max Tokens'),
            ('context_window_threshold', 'Context Threshold'),
            ('extra_header', 'Extra Header'),
            ('enable_thinking', 'Extended Thinking'),
        ]

        for key, display_name in config_items:
            config_value = getattr(self, key, None)
            if config_value and config_value.value is not None:
                status = format_style('✓', 'green bold')
                value = str(config_value.value)
                source = f'from {config_value.source}'
            else:
                status = format_style('✗', 'red bold')
                value = format_style('Not Set', 'red')
                source = ''
            table.add_row(
                status,
                format_style(display_name, 'bold bright_black'),
                value,
                source,
            )
        return table


class ConfigSource:
    def __init__(self, source: str):
        self.source = source
        self.config_model: ConfigModel = None

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        """Get configuration value"""
        config_value = getattr(self.config_model, key, None)
        return config_value.value if config_value else None

    def get_source_name(self) -> str:
        """Get configuration source name"""
        return self.source

    def get_config_model(self) -> ConfigModel:
        """Get the internal config model"""
        return self.config_model


class ArgConfigSource(ConfigSource):
    """CLI argument configuration"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        model_azure: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        context_window_threshold: Optional[int] = None,
        extra_header: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
    ):
        super().__init__('cli')
        self.config_model = ConfigModel(
            source='cli',
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            model_azure=model_azure,
            max_tokens=max_tokens,
            context_window_threshold=context_window_threshold,
            extra_header=extra_header,
            enable_thinking=enable_thinking,
        )


class EnvConfigSource(ConfigSource):
    """Environment variable configuration"""

    def __init__(self):
        super().__init__('env')
        self._env_map = {
            'api_key': 'API_KEY',
            'model_name': 'MODEL_NAME',
            'base_url': 'BASE_URL',
            'model_azure': 'model_azure',
            'max_tokens': 'MAX_TOKENS',
            'context_window_threshold': 'CONTEXT_WINDOW_THRESHOLD',
            'extra_header': 'EXTRA_HEADER',
            'enable_thinking': 'ENABLE_THINKING',
        }
        self._load_env_config()

    def _load_env_config(self):
        """Load environment variables into config model"""
        config_data = {}
        for key, env_key in self._env_map.items():
            env_value = os.getenv(env_key)
            if env_value is not None:
                # Type conversion
                if key in ['model_azure', 'enable_thinking']:
                    config_data[key] = env_value.lower() in ['true', '1', 'yes', 'on']
                elif key in ['context_window_threshold', 'max_tokens']:
                    try:
                        config_data[key] = int(env_value)
                    except ValueError:
                        config_data[key] = None
                else:
                    config_data[key] = env_value

        self.config_model = ConfigModel(source='env', **config_data)


class GlobalConfigSource(ConfigSource):
    """Global configuration file"""

    def __init__(self):
        super().__init__('config')
        self._load_config()

    @staticmethod
    def get_config_path() -> Path:
        """Get configuration file path"""
        return Path.home() / '.klaude' / 'config.json'

    def _load_config(self):
        """Load configuration file into config model"""
        config_path = self.get_config_path()
        if not config_path.exists():
            self.config_model = ConfigModel(source='config')
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                # Filter only valid ConfigModel fields
                valid_fields = {k for k in ConfigModel.model_fields.keys()}
                filtered_data = {k: v for k, v in config_data.items() if k in valid_fields}
                self.config_model = ConfigModel(source='config', **filtered_data)
        except (json.JSONDecodeError, IOError) as e:
            console.print(format_style(f'Warning: Failed to load config: {e}', 'yellow'))
            self.config_model = ConfigModel(source='config')

    @classmethod
    def open_config_file(cls):
        """Open the configuration file in the default editor"""
        config_path = cls.get_config_path()
        if config_path.exists():
            console.print(
                format_style(
                    f'Opening config file: {format_style(str(config_path), "green")}',
                    'green',
                )
            )
            import sys

            editor = os.getenv('EDITOR', 'vi' if sys.platform != 'darwin' else 'open')
            os.system(f'{editor} {config_path}')
        else:
            console.print(format_style('Config file not found', 'red'))

    @classmethod
    def create_example_config(cls, config_path: Path = None):
        """Create an example configuration file"""
        if config_path is None:
            config_path = cls.get_config_path()

        example_config = {
            'api_key': 'your_api_key_here',
            'model_name': DEFAULT_MODEL_NAME,
            'base_url': DEFAULT_BASE_URL,
            'model_azure': DEFAULT_MODEL_AZURE,
            'max_tokens': DEFAULT_MAX_TOKENS,
            'context_window_threshold': DEFAULT_CONTEXT_WINDOW_THRESHOLD,
            'extra_header': DEFAULT_EXTRA_HEADER,
            'enable_thinking': DEFAULT_ENABLE_THINKING,
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(example_config, f, indent=2, ensure_ascii=False)
            console.print(format_style(f'Example config file created at: {config_path}', 'green'))
            console.print('Please edit the file and set your actual API key.')
            return True
        except (IOError, OSError) as e:
            console.print(format_style(f'Error: Failed to create config file: {e}', 'red'))
            return False

    @classmethod
    def edit_config_file(cls):
        """Edit the configuration file, creating one if it doesn't exist"""
        config_path = cls.get_config_path()
        if not config_path.exists():
            cls.create_example_config(config_path)
        cls.open_config_file()


class DefaultConfigSource(ConfigSource):
    """Default configuration"""

    def __init__(self):
        super().__init__('default')
        self.config_model = ConfigModel(
            source='default',
            api_key=None,
            model_name=DEFAULT_MODEL_NAME,
            base_url=DEFAULT_BASE_URL,
            model_azure=DEFAULT_MODEL_AZURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            context_window_threshold=DEFAULT_CONTEXT_WINDOW_THRESHOLD,
            extra_header=DEFAULT_EXTRA_HEADER,
            enable_thinking=DEFAULT_ENABLE_THINKING,
        )


class ConfigManager:
    """Configuration manager that merges multiple config sources with priority"""

    def __init__(self, sources: List[ConfigSource]):
        # Sources in priority order (higher index = higher priority)
        self.sources = sources
        self._merged_config_model = self._merge_config_models()
        self._validate_api_key()

    def _merge_config_models(self) -> ConfigModel:
        """Merge all configuration models from sources"""
        merged_config = {}

        # Merge all sources (later sources override earlier ones)
        for source in self.sources:
            if source.config_model:
                for field_name in ConfigModel.model_fields.keys():
                    config_value = getattr(source.config_model, field_name, None)
                    if config_value and config_value.value is not None:
                        merged_config[field_name] = config_value

        # Create final config model with preserved source information
        final_model = ConfigModel()
        for key, config_value in merged_config.items():
            setattr(final_model, key, config_value)

        return final_model

    def _validate_api_key(self):
        """Validate that API key is provided and not from default source"""
        api_key_config = self._merged_config_model.api_key

        if not api_key_config or not api_key_config.value or api_key_config.source == 'default':
            console.print(format_style('Warning: API key not set', 'red'))
            console.print('Please set your API key using one of the following methods:')
            console.print('  1. Command line: --api-key YOUR_API_KEY')
            console.print('  2. Environment: export API_KEY=YOUR_API_KEY')
            console.print("  3. Config file: Run 'klaude config edit' to set it")
            return

    def get_config_model(self) -> ConfigModel:
        """Get merged configuration model from all sources"""
        return self._merged_config_model

    def __rich__(self):
        return Group(
            f' config path: {Path.home() / ".klaude" / "config.json"}',
            Panel(self.get_config_model(), box=box.HORIZONTALS),
        )

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        """Get configuration value with priority resolution"""
        config_value = getattr(self._merged_config_model, key, None)
        return config_value.value if config_value else None

    def get_value_with_source(self, key: str) -> Optional[ConfigValue]:
        """Get configuration value with source information"""
        return getattr(self._merged_config_model, key, None)

    @classmethod
    def setup(
        cls,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        model_azure: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        context_window_threshold: Optional[int] = None,
        extra_header: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
    ) -> 'ConfigManager':
        """Create a ConfigManager with all configuration sources

        Args:
            CLI arguments that will be passed to ArgConfigSource

        Returns:
            ConfigManager with sources in priority order: Default < Config File < Environment < CLI Args
        """
        sources = [
            DefaultConfigSource(),
            GlobalConfigSource(),
            EnvConfigSource(),
            ArgConfigSource(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                model_azure=model_azure,
                max_tokens=max_tokens,
                context_window_threshold=context_window_threshold,
                extra_header=extra_header,
                enable_thinking=enable_thinking,
            ),
        ]

        return cls(sources)
