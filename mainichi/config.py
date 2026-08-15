"""Configuration objects shared by the whole application.

Everything the user can pick on the command line, plus everything the
context menu can toggle at run time, lives here so that the UI layer never
has to invent its own defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# Official JLPT levels, easiest first. N5 is the default for a beginner.
LEVELS: tuple[str, ...] = ("N5", "N4", "N3", "N2", "N1")
DEFAULT_LEVEL = "N5"

# Below this the layout stops being readable.
MIN_SIZE: tuple[int, int] = (210, 230)
DEFAULT_SIZE: tuple[int, int] = (300, 340)

# Languages the sentence translations can be shown in.
LANGUAGES: dict[str, str] = {"en": "English", "fr": "Français", "es": "Español"}
DEFAULT_LANGUAGE = "en"


@dataclass(slots=True)
class PostItOptions:
    """Per-post-it options, all reachable from the right-click menu.

    Each post-it owns its own copy: the user may want one pinned on top and
    another one not, one yellow and another one blue.
    """

    palette: str = "yellow"
    always_on_top: bool = True
    show_furigana: bool = True
    show_translation: bool = True
    language: str = DEFAULT_LANGUAGE

    def copy(self) -> "PostItOptions":
        return replace(self)


@dataclass(slots=True)
class AppConfig:
    """Immutable-ish launch configuration, built from the command line."""

    level: str = DEFAULT_LEVEL
    kanji: str | None = None
    decorated: bool = False
    size: tuple[int, int] = DEFAULT_SIZE
    options: PostItOptions = field(default_factory=PostItOptions)

    @property
    def selection_label(self) -> str:
        """Human readable description of what was asked for."""
        return self.kanji if self.kanji else f"JLPT {self.level}"
