"""The error a chat tool raises: a refusal or failure whose message is safe to show to the model and in the step trace."""
from __future__ import annotations


class ToolError(Exception):
    """A refusal or failure whose message is safe to show to the model and in the step trace."""
