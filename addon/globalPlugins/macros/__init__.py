# -*- coding: UTF-8 -*-
# Macros add-on for NVDA
# Copyright (C) 2026 Oscar Gomez
# This file is covered by the GNU General Public License.
# See the file COPYING.txt for more details.

"""Keyboard macros for NVDA.

Press NVDA+alt+shift+m to enter the macros layer, then:

* 1 to 0: play the macro stored in that slot.
* shift+1 to shift+0: start recording keystrokes into that slot. NVDA speech
  and the pauses between keys are recorded too. Press NVDA+alt+shift+m again
  to stop recording.
* alt+1 to alt+0: review what NVDA spoke after each recorded keystroke and
  edit the per-step wildcard safety checks enforced during playback.
* left and right arrows: switch between the ten macro stacks; every numbered
  command addresses the current stack.
* h or f1: speak a summary of these commands.
* escape: leave the layer.
"""

import os
import sys
import threading
import time

import addonHandler
import globalPluginHandler
import globalVars
import gui
import inputCore
import queueHandler
import tones
import ui
import wx
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from scriptHandler import script
from speech.extensions import pre_speech

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_ADDON_DIR = "\\".join(ADDON_DIR.split(os.sep)[:-2])
# uv keeps this project's third party packages in .venv\Lib\site-packages at the repository root.
UV_PACKAGES_DIR = os.path.join(os.path.dirname(ROOT_ADDON_DIR), ".venv", "Lib", "site-packages")
sys.path.insert(0, UV_PACKAGES_DIR)
# Import any third party dependencies installed with uv here,
# while .venv\Lib\site-packages is on sys.path.
sys.path.remove(UV_PACKAGES_DIR)

addonHandler.initTranslation()

from .macroEngine import (  # noqa: E402
	MacroRecorder,
	MacroStore,
	SLOT_COUNT,
	cycleStack,
	keyNameForSlot,
	normalizeSpokenText,
	slotForKeyName,
	wildcardMatch,
)

try:
	ADDON_INFO = addonHandler.Addon(ROOT_ADDON_DIR).manifest
except Exception:
	# The manifest only exists once the add-on has been built or installed.
	ADDON_INFO = None

#: The gesture that toggles the layer, stops recording and stops playback.
TOGGLE_GESTURE = "kb:NVDA+alt+shift+m"
#: How long playback waits for speech satisfying a safety check before giving up, in seconds.
SPEECH_CHECK_TIMEOUT = 3.0
#: How often waits are interrupted to honour a cancel request, in seconds.
_CANCEL_POLL_INTERVAL = 0.05
#: File name of the persisted macros inside NVDA's configuration directory.
MACROS_FILE = "macros.json"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	# Translators: Script category shown in NVDA's input gestures dialog.
	scriptCategory = _("Macros")

	def __init__(self):
		super().__init__()
		self._store = MacroStore(os.path.join(globalVars.appArgs.configPath, MACROS_FILE))
		try:
			self._store.load()
		except (ValueError, OSError):
			log.error("Could not load saved macros; starting with an empty set", exc_info=True)
		self._layerActive = False
		#: MacroRecorder while a recording is in progress, else None.
		self._recorder = None
		self._recordingSlot = None
		self._playbackThread = None
		self._stopPlayback = threading.Event()
		self._speechLock = threading.Lock()
		self._playbackSpeech = []
		self._speechArrived = threading.Event()
		self._collectPlaybackSpeech = False
		self._layerGestures = {}
		for slot in range(1, SLOT_COUNT + 1):
			key = keyNameForSlot(slot)
			self._layerGestures[f"kb:{key}"] = "playMacro"
			self._layerGestures[f"kb:shift+{key}"] = "recordMacro"
			self._layerGestures[f"kb:alt+{key}"] = "editMacroChecks"
		self._layerGestures["kb:leftArrow"] = "previousStack"
		self._layerGestures["kb:rightArrow"] = "nextStack"
		self._layerGestures["kb:h"] = "layerHelp"
		self._layerGestures["kb:f1"] = "layerHelp"
		self._layerGestures["kb:escape"] = "exitLayer"
		inputCore.decide_executeGesture.register(self._onDecideExecuteGesture)
		pre_speech.register(self._onPreSpeech)

	def terminate(self):
		self._stopPlayback.set()
		self._recorder = None
		self._recordingSlot = None
		inputCore.decide_executeGesture.unregister(self._onDecideExecuteGesture)
		pre_speech.unregister(self._onPreSpeech)
		super().terminate()

	@property
	def isRecording(self):
		return self._recorder is not None

	@property
	def isPlaying(self):
		thread = self._playbackThread
		return thread is not None and thread.is_alive()

	# Extension point handlers

	def _onDecideExecuteGesture(self, gesture=None, **kwargs):
		"""Observe every gesture NVDA is about to execute; never blocks any of them."""
		recorder = self._recorder
		if recorder is None or not isinstance(gesture, KeyboardInputGesture):
			return True
		if gesture.isModifier:
			# Combined gestures already include their modifiers; recording the
			# lone modifier press as well would double it up on playback.
			return True
		boundScript = gesture.script
		if boundScript is not None and getattr(boundScript, "__self__", None) is self:
			# This add-on's own commands (in particular the stop recording
			# gesture) must never become part of a macro.
			return True
		keyName = gesture.identifiers[-1].split(":", 1)[1]
		recorder.addKeystroke(keyName, time.monotonic())
		return True

	def _onPreSpeech(self, speechSequence=None, **kwargs):
		"""Capture what NVDA speaks, both while recording and while checking playback."""
		if not speechSequence:
			return
		text = normalizeSpokenText(" ".join(item for item in speechSequence if isinstance(item, str)))
		if not text:
			return
		recorder = self._recorder
		if recorder is not None:
			recorder.addSpeech(text)
		if self._collectPlaybackSpeech:
			with self._speechLock:
				self._playbackSpeech.append(text)
			self._speechArrived.set()

	# Layer handling

	def getScript(self, gesture):
		if not self._layerActive:
			return super().getScript(gesture)
		boundScript = super().getScript(gesture)
		if boundScript is not None:
			return boundScript
		if isinstance(gesture, KeyboardInputGesture) and gesture.isModifier:
			# Let the user finish shift+number and alt+number combinations.
			return None
		return self.script_wrongLayerGesture

	def _enterLayer(self):
		self.bindGestures(self._layerGestures)
		self._layerActive = True
		tones.beep(660, 60)
		# Translators: Announced when the macros command layer becomes active.
		ui.message(_("Macros layer"))

	def _exitLayer(self):
		if not self._layerActive:
			return
		self._layerActive = False
		for gestureIdentifier in self._layerGestures:
			try:
				self.removeGestureBinding(gestureIdentifier)
			except LookupError:
				pass

	@script(
		description=_(
			# Translators: Input help description for the main macros command.
			"Turns the macros layer on or off. "
			"While recording a macro, stops recording. "
			"While a macro is playing, stops playback.",
		),
		gesture=TOGGLE_GESTURE,
	)
	def script_macrosLayer(self, gesture):
		if self.isRecording:
			self._finishRecording()
			return
		if self.isPlaying:
			self._stopPlayback.set()
			# Translators: Announced when macro playback is interrupted by the user.
			ui.message(_("Macro playback stopped"))
			return
		if self._layerActive:
			self._exitLayer()
			# Translators: Announced when leaving the macros layer without running a command.
			ui.message(_("Macros layer off"))
			return
		self._enterLayer()

	@script(
		# Translators: Input help description for the layer command that plays a macro.
		description=_("Plays the macro stored in the pressed number slot"),
	)
	def script_playMacro(self, gesture):
		self._exitLayer()
		slot = slotForKeyName(gesture.mainKeyName)
		if slot is None:
			tones.beep(120, 80)
			return
		self._playMacro(slot)

	@script(
		# Translators: Input help description for the layer command that records a macro.
		description=_("Starts recording a macro into the pressed number slot"),
	)
	def script_recordMacro(self, gesture):
		self._exitLayer()
		slot = slotForKeyName(gesture.mainKeyName)
		if slot is None:
			tones.beep(120, 80)
			return
		self._startRecording(slot)

	@script(
		# Translators: Input help description for the layer command that edits macro safety checks.
		description=_("Opens the safety checks dialog for the macro in the pressed number slot"),
	)
	def script_editMacroChecks(self, gesture):
		self._exitLayer()
		slot = slotForKeyName(gesture.mainKeyName)
		if slot is None:
			tones.beep(120, 80)
			return
		self._openChecksDialog(slot)

	@script(
		# Translators: Input help description for the layer command that switches
		# to the previous macro stack.
		description=_("Switches to the previous macro stack"),
	)
	def script_previousStack(self, gesture):
		self._switchStack(-1)

	@script(
		# Translators: Input help description for the layer command that switches
		# to the next macro stack.
		description=_("Switches to the next macro stack"),
	)
	def script_nextStack(self, gesture):
		self._switchStack(1)

	def _switchStack(self, delta):
		self._store.setStack(cycleStack(self._store.currentStack, delta))
		self._saveStore()
		count = len(self._store.macros)
		if not count:
			# Translators: Announced when switching to a macro stack with no recorded macros.
			# {number} is the stack number.
			message = _("Stack {number}, empty").format(number=self._store.currentStack)
		else:
			message = ngettext(
				# Translators: Announced when switching macro stacks.
				# {number} is the stack number and {count} how many macros it holds.
				"Stack {number}, {count} macro",
				"Stack {number}, {count} macros",
				count,
			).format(number=self._store.currentStack, count=count)
		ui.message(message)

	@script(
		# Translators: Input help description for the layer command that lists the layer commands.
		description=_("Speaks the commands available in the macros layer"),
	)
	def script_layerHelp(self, gesture):
		# The layer stays active so the user can press one of the announced keys.
		ui.message(
			_(
				# Translators: Help message spoken when pressing h or f1 inside the macros layer.
				"1 to 0: play the macro in that slot. "
				"Shift plus a number: record into that slot. "
				"Alt plus a number: review speech and edit safety checks. "
				"Left and right arrows: switch macro stacks. "
				"H or F1: this help. "
				"Escape: exit the layer.",
			),
		)

	@script(
		# Translators: Input help description for the layer command that leaves the macros layer.
		description=_("Exits the macros layer"),
	)
	def script_exitLayer(self, gesture):
		self._exitLayer()
		# Translators: Announced when leaving the macros layer without running a command.
		ui.message(_("Macros layer off"))

	def script_wrongLayerGesture(self, gesture):
		self._exitLayer()
		tones.beep(120, 80)

	# Recording

	def _startRecording(self, slot):
		if self.isPlaying:
			# Translators: Error announced when trying to record while a macro is playing.
			ui.message(_("Cannot record while a macro is playing"))
			return
		self._recordingSlot = slot
		self._recorder = MacroRecorder()
		tones.beep(880, 80)
		# Translators: Announced when macro recording starts.
		# {number} is the macro slot number.
		ui.message(_("Recording macro {number}").format(number=slot))

	def _finishRecording(self):
		recorder = self._recorder
		slot = self._recordingSlot
		self._recorder = None
		self._recordingSlot = None
		if recorder is None:
			return
		if not recorder.hasSteps:
			tones.beep(220, 80)
			ui.message(
				_(
					# Translators: Announced when recording ends without any keystrokes.
					# {number} is the macro slot number.
					"Recording stopped. Macro {number} is unchanged because no keystrokes were recorded",
				).format(
					number=slot,
				),
			)
			return
		macro = recorder.finish()
		self._store.macros[slot] = macro
		self._saveStore()
		tones.beep(440, 80)
		count = len(macro.steps)
		message = ngettext(
			# Translators: Announced when a macro has been recorded.
			# {number} is the macro slot number and {count} the amount of recorded keystrokes.
			"Macro {number} recorded with {count} keystroke",
			"Macro {number} recorded with {count} keystrokes",
			count,
		).format(number=slot, count=count)
		ui.message(message)

	def _saveStore(self):
		try:
			self._store.save()
		except OSError:
			log.error("Could not save macros", exc_info=True)
			# Translators: Error announced when the macros file cannot be written to disk.
			ui.message(_("Error saving macros"))

	# Playback

	def _playMacro(self, slot):
		if self.isRecording:
			return
		if self.isPlaying:
			# Translators: Error announced when trying to start a macro while another is playing.
			ui.message(_("A macro is already playing"))
			return
		macro = self._store.macros.get(slot)
		if macro is None or not macro.steps:
			# Translators: Announced when the chosen macro slot has no recording.
			# {number} is the macro slot number.
			ui.message(_("Macro {number} is empty").format(number=slot))
			return
		self._stopPlayback.clear()
		self._playbackThread = threading.Thread(
			target=self._playbackWorker,
			name=f"macroPlayback{slot}",
			args=(slot, macro),
			daemon=True,
		)
		self._playbackThread.start()

	def _playbackWorker(self, slot, macro):
		failure = None
		try:
			for index, step in enumerate(macro.steps):
				if not self._waitCancellable(step.delay):
					return
				try:
					gesture = KeyboardInputGesture.fromName(step.key)
				except (KeyError, ValueError, LookupError):
					log.error(f"Cannot rebuild keystroke {step.key!r} for macro {slot}", exc_info=True)
					# Translators: Error announced when a recorded keystroke cannot be replayed.
					# {key} is the name of the keystroke.
					failure = _("Macro stopped: cannot send {key}").format(key=step.key)
					return
				enforcing = step.enforce and bool(step.expected)
				if enforcing:
					with self._speechLock:
						self._playbackSpeech.clear()
					self._speechArrived.clear()
					self._collectPlaybackSpeech = True
				queueHandler.queueFunction(queueHandler.eventQueue, inputCore.manager.emulateGesture, gesture)
				if enforcing:
					matched = self._waitForSpeechMatch(step.expected)
					self._collectPlaybackSpeech = False
					if self._stopPlayback.is_set():
						return
					if not matched:
						with self._speechLock:
							heard = " ".join(self._playbackSpeech)
						if not heard:
							# Translators: Placeholder used in the safety check failure message
							# when NVDA spoke nothing at all after a keystroke.
							heard = _("nothing")
						failure = _(
							# Translators: Error announced when a macro safety check fails during playback.
							# {number} is the macro slot number, {step} the failing step number,
							# {key} the keystroke, {expected} the expected speech pattern
							# and {heard} what NVDA actually spoke.
							"Macro {number} stopped at step {step}, {key}: "
							"expected speech matching {expected} but heard {heard}",
						).format(
							number=slot, step=index + 1, key=step.key, expected=step.expected, heard=heard
						)
						return
			tones.beep(880, 60)
		finally:
			self._collectPlaybackSpeech = False
			if failure:
				tones.beep(220, 150)
				queueHandler.queueFunction(queueHandler.eventQueue, ui.message, failure)

	def _waitCancellable(self, delay):
		"""Wait for up to delay seconds; return False if playback was cancelled meanwhile."""
		deadline = time.monotonic() + delay
		while True:
			remaining = deadline - time.monotonic()
			if remaining <= 0:
				return not self._stopPlayback.is_set()
			if self._stopPlayback.wait(min(_CANCEL_POLL_INTERVAL, remaining)):
				return False

	def _waitForSpeechMatch(self, pattern):
		"""Wait until captured speech matches the pattern; return False on timeout or cancel."""
		deadline = time.monotonic() + SPEECH_CHECK_TIMEOUT
		while True:
			with self._speechLock:
				heard = " ".join(self._playbackSpeech)
			if wildcardMatch(pattern, heard):
				return True
			remaining = deadline - time.monotonic()
			if remaining <= 0 or self._stopPlayback.is_set():
				return False
			self._speechArrived.wait(min(remaining, 0.25))
			self._speechArrived.clear()

	# Safety checks dialog

	def _openChecksDialog(self, slot):
		macro = self._store.macros.get(slot)
		if macro is None or not macro.steps:
			# Translators: Announced when the chosen macro slot has no recording.
			# {number} is the macro slot number.
			ui.message(_("Macro {number} is empty").format(number=slot))
			return
		wx.CallAfter(self._showChecksDialog, self._store.currentStack, slot, macro)

	def _showChecksDialog(self, stack, slot, macro):
		from .dialogs import MacroChecksDialog

		gui.mainFrame.prePopup()
		try:
			dialog = MacroChecksDialog(gui.mainFrame, stack, slot, macro)
			try:
				if dialog.ShowModal() == wx.ID_OK:
					dialog.applyTo(macro)
					self._saveStore()
			finally:
				dialog.Destroy()
		finally:
			gui.mainFrame.postPopup()
