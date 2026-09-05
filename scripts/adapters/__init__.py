"""External agent adapters for Forge."""
from .claude_code import ClaudeCodeImplementer
from .codex_cli import CodexCLIReviewer

__all__ = ["ClaudeCodeImplementer", "CodexCLIReviewer"]
