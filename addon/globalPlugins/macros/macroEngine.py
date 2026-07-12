# -*- coding: UTF-8 -*-
# Macros add-on for NVDA
# Copyright (C) 2026 Oscar Gomez
# This file is covered by the GNU General Public License.
# See the file COPYING.txt for more details.

"""Core model for the Macros add-on.

This module is intentionally free of NVDA imports so that it can be unit
tested outside of a running NVDA instance. All user visible strings live in
the plugin package (`__init__.py` and `dialogs.py`), never here.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

#: Number of macro slots available (keys 1 to 9 plus 0).
SLOT_COUNT = 10
#: Number of macro stacks available; every stack holds SLOT_COUNT slots.
STACK_COUNT = 10
#: Number row keys in slot order; index 0 holds the key for slot 1.
_SLOT_KEYS = "1234567890"
#: Upper bound applied to recorded delays between keystrokes, in seconds.
MAX_STEP_DELAY = 60.0
#: Version stamp written to the persistence file.
FILE_VERSION = 3


def keyNameForSlot(slot: int) -> str:
	"""Return the number row key that addresses the given 1-based slot."""
	if not 1 <= slot <= SLOT_COUNT:
		raise ValueError(f"slot must be between 1 and {SLOT_COUNT}, got {slot!r}")
	return _SLOT_KEYS[slot - 1]


def slotForKeyName(keyName: str) -> int | None:
	"""Return the 1-based slot for a number row key name, or None for other keys."""
	index = _SLOT_KEYS.find(keyName) if len(keyName) == 1 else -1
	return index + 1 if index >= 0 else None


def normalizeSpokenText(text: str) -> str:
	"""Collapse all whitespace runs to single spaces so speech chunks compare cleanly."""
	return " ".join(text.split())


def wildcardToRegex(pattern: str) -> str:
	"""Translate a wildcard pattern into a regular expression source string.

	Every character is matched literally except ``*``, which matches any run of
	characters, including an empty one.
	"""
	return ".*".join(re.escape(part) for part in pattern.split("*"))


def wildcardMatch(pattern: str, text: str) -> bool:
	"""Check whether spoken text satisfies a wildcard pattern.

	Matching is case insensitive, ignores extra whitespace, and succeeds when
	the pattern matches anywhere inside the text, so ``save``, ``Save``,
	``s*ve`` and ``* button`` all match "Save button". An empty pattern
	always matches.
	"""
	pattern = normalizeSpokenText(pattern)
	if not pattern:
		return True
	text = normalizeSpokenText(text)
	return re.search(wildcardToRegex(pattern), text, re.IGNORECASE | re.DOTALL) is not None


def clampDelay(delay: float) -> float:
	"""Keep a recorded delay within sane bounds for playback."""
	return max(0.0, min(float(delay), MAX_STEP_DELAY))


def cycleStack(current: int, delta: int) -> int:
	"""Move delta positions through the stacks, wrapping around at both ends."""
	return (current - 1 + delta) % STACK_COUNT + 1


@dataclass
class MacroStep:
	"""One keystroke of a macro.

	:ivar key: NVDA key name, e.g. ``control+shift+t`` or ``NVDA+f7``.
	:ivar delay: Seconds waited before pressing this key.
	:ivar spoken: What NVDA spoke after this key while recording.
	:ivar expected: Wildcard pattern the speech must match when this step's
		safety check is enforced; empty disables the check for this step.
	:ivar enforce: When True, playback stops unless NVDA's speech after this
		step matches the expected pattern.
	"""

	key: str
	delay: float = 0.0
	spoken: str = ""
	expected: str = ""
	enforce: bool = False

	def __post_init__(self) -> None:
		self.delay = clampDelay(self.delay)

	def toDict(self) -> dict[str, object]:
		return {
			"key": self.key,
			"delay": self.delay,
			"spoken": self.spoken,
			"expected": self.expected,
			"enforce": self.enforce,
		}

	@classmethod
	def fromDict(cls, data: object) -> "MacroStep":
		if not isinstance(data, dict):
			raise ValueError(f"macro step must be a mapping, got {type(data).__name__}")
		key = data.get("key")
		if not isinstance(key, str) or not key:
			raise ValueError("macro step requires a non-empty key name")
		delay = data.get("delay", 0.0)
		if isinstance(delay, bool) or not isinstance(delay, (int, float)):
			raise ValueError("macro step delay must be a number")
		spoken = data.get("spoken", "")
		expected = data.get("expected", "")
		if not isinstance(spoken, str) or not isinstance(expected, str):
			raise ValueError("macro step speech fields must be strings")
		enforce = data.get("enforce", False)
		if not isinstance(enforce, bool):
			raise ValueError("macro step enforce flag must be a boolean")
		return cls(key=key, delay=float(delay), spoken=spoken, expected=expected, enforce=enforce)


@dataclass
class Macro:
	"""A recorded sequence of keystrokes stored in one slot."""

	steps: list[MacroStep] = field(default_factory=list)

	def toDict(self) -> dict[str, object]:
		return {
			"steps": [step.toDict() for step in self.steps],
		}

	@classmethod
	def fromDict(cls, data: object) -> "Macro":
		if not isinstance(data, dict):
			raise ValueError(f"macro must be a mapping, got {type(data).__name__}")
		rawSteps = data.get("steps", [])
		if not isinstance(rawSteps, list):
			raise ValueError("macro steps must be a list")
		steps = [MacroStep.fromDict(rawStep) for rawStep in rawSteps]
		# Files from version 1 stored a single enforce flag on the macro;
		# carry it over to every step.
		legacyEnforce = data.get("enforce", False)
		if not isinstance(legacyEnforce, bool):
			raise ValueError("macro enforce flag must be a boolean")
		if legacyEnforce:
			for step in steps:
				step.enforce = True
		return cls(steps=steps)


class MacroRecorder:
	"""Accumulates keystrokes and NVDA speech during one recording session.

	Timestamps are supplied by the caller (``time.monotonic()`` inside NVDA)
	so the recorder itself stays deterministic and testable.
	"""

	def __init__(self) -> None:
		self.steps: list[MacroStep] = []
		self._lastKeyTime: float | None = None

	@property
	def hasSteps(self) -> bool:
		return bool(self.steps)

	def addKeystroke(self, keyName: str, timestamp: float) -> None:
		"""Record a keystroke pressed at the given monotonic timestamp.

		The first keystroke always gets a zero delay: the time the user spent
		before starting to type is not part of the macro.
		"""
		delay = 0.0 if self._lastKeyTime is None else clampDelay(timestamp - self._lastKeyTime)
		self._lastKeyTime = timestamp
		self.steps.append(MacroStep(key=keyName, delay=delay))

	def addSpeech(self, text: str) -> None:
		"""Attach spoken text to the most recent keystroke.

		Speech heard before the first keystroke (such as the announcement that
		recording started) is discarded.
		"""
		if not self.steps:
			return
		text = normalizeSpokenText(text)
		if not text:
			return
		step = self.steps[-1]
		step.spoken = f"{step.spoken} {text}" if step.spoken else text

	def finish(self) -> Macro:
		"""Build the final macro; expected patterns default to the recorded speech.

		Safety checks start disabled on every step; the user turns them on per
		step in the safety checks dialog.
		"""
		for step in self.steps:
			if not step.expected:
				step.expected = step.spoken
		return Macro(steps=self.steps)


class MacroStore:
	"""Loads and saves every macro stack, and tracks the selected stack.

	Macros live in STACK_COUNT stacks of SLOT_COUNT slots each. The
	:attr:`macros` property exposes the slots of the currently selected
	stack, which is itself persisted so users come back to the stack they
	were working with.
	"""

	def __init__(self, path: str) -> None:
		self.path = path
		self.stacks: dict[int, dict[int, Macro]] = {}
		self.currentStack: int = 1

	@property
	def macros(self) -> dict[int, Macro]:
		"""The slot to macro mapping of the currently selected stack."""
		return self.stacks.setdefault(self.currentStack, {})

	def setStack(self, stack: int) -> None:
		if not 1 <= stack <= STACK_COUNT:
			raise ValueError(f"stack must be between 1 and {STACK_COUNT}, got {stack!r}")
		self.currentStack = stack

	def load(self) -> None:
		"""Read all stacks from disk.

		A missing file simply yields an empty store. A file that is not valid
		JSON or not shaped like a macros file raises ValueError. Individual
		slots that fail validation are skipped so one corrupt macro cannot
		take the rest down with it. Files from versions 1 and 2, which held a
		single set of macros, load into stack 1.
		"""
		self.stacks = {}
		self.currentStack = 1
		try:
			with open(self.path, "r", encoding="utf-8") as fileObj:
				data = json.load(fileObj)
		except FileNotFoundError:
			return
		except json.JSONDecodeError as error:
			raise ValueError(f"macros file {self.path} is not valid JSON") from error
		if not isinstance(data, dict):
			raise ValueError(f"macros file {self.path} has an unexpected structure")
		if "stacks" in data:
			rawStacks = data["stacks"]
		elif "macros" in data:
			rawStacks = {"1": data["macros"]}
		else:
			rawStacks = {}
		if not isinstance(rawStacks, dict):
			raise ValueError(f"macros file {self.path} has an unexpected structure")
		for rawStack, rawSlots in rawStacks.items():
			try:
				stack = int(rawStack)
			except (TypeError, ValueError):
				continue
			if not 1 <= stack <= STACK_COUNT:
				continue
			if not isinstance(rawSlots, dict):
				raise ValueError(f"macros file {self.path} has an unexpected structure")
			slots = self._loadSlots(rawSlots)
			if slots:
				self.stacks[stack] = slots
		rawCurrent = data.get("currentStack", 1)
		if (
			isinstance(rawCurrent, int)
			and not isinstance(rawCurrent, bool)
			and 1 <= rawCurrent <= STACK_COUNT
		):
			self.currentStack = rawCurrent

	@staticmethod
	def _loadSlots(rawSlots: dict[object, object]) -> dict[int, Macro]:
		slots: dict[int, Macro] = {}
		for rawSlot, rawMacro in rawSlots.items():
			try:
				slot = int(rawSlot)
			except (TypeError, ValueError):
				continue
			if not 1 <= slot <= SLOT_COUNT:
				continue
			try:
				slots[slot] = Macro.fromDict(rawMacro)
			except ValueError:
				continue
		return slots

	def save(self) -> None:
		"""Write all stacks and the selected stack to disk atomically."""
		data = {
			"version": FILE_VERSION,
			"currentStack": self.currentStack,
			"stacks": {
				str(stack): {str(slot): macro.toDict() for slot, macro in sorted(slots.items())}
				for stack, slots in sorted(self.stacks.items())
				if slots
			},
		}
		directory = os.path.dirname(self.path)
		if directory:
			os.makedirs(directory, exist_ok=True)
		tempPath = f"{self.path}.tmp"
		with open(tempPath, "w", encoding="utf-8") as fileObj:
			json.dump(data, fileObj, ensure_ascii=False, indent=2)
		os.replace(tempPath, self.path)
