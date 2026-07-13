# -*- coding: UTF-8 -*-
# Macros add-on for NVDA
# Copyright (C) 2026 Oscar Gomez
# This file is covered by the GNU General Public License.
# See the file COPYING.txt for more details.

"""GUI for reviewing recorded speech, editing macro safety checks
and configuring the add-on."""

import addonHandler
import config
import wx
from gui import guiHelper, nvdaControls

from .macroEngine import clampDelay

addonHandler.initTranslation()

#: Index of the expected pattern column in the steps list.
_PATTERN_COLUMN = 2
#: Index of the enforced column in the steps list.
_ENFORCED_COLUMN = 3
#: Index of the delay column in the steps list.
_DELAY_COLUMN = 4


class MacroChecksDialog(wx.Dialog):
	"""Shows every recorded step of a macro with the speech NVDA gave,
	and lets the user edit, per step, the wildcard pattern that speech must
	match and whether that check is enforced during playback.
	"""

	def __init__(self, parent, stack, slot, macro):
		super().__init__(
			parent,
			# Translators: Title of the macro safety checks dialog.
			# {number} is the macro slot number and {stack} the stack it belongs to.
			title=_("Safety checks for macro {number} in stack {stack}").format(number=slot, stack=stack),
		)
		self._steps = macro.steps
		self._patterns = [step.expected for step in macro.steps]
		self._enforces = [step.enforce for step in macro.steps]
		self._delays = [step.delay for step in macro.steps]
		self._updatingPatternEdit = False
		self._updatingDelayEdit = False

		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		self.stepsList = sHelper.addLabeledControl(
			# Translators: Label of the list showing every recorded step of a macro.
			_("&Steps:"),
			nvdaControls.AutoWidthColumnListCtrl,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
		)
		# Translators: Header of the steps list column holding the recorded keystroke.
		self.stepsList.InsertColumn(0, _("Keystroke"))
		# Translators: Header of the steps list column holding what NVDA spoke while recording.
		self.stepsList.InsertColumn(1, _("Recorded speech"))
		# Translators: Header of the steps list column holding the expected speech pattern.
		self.stepsList.InsertColumn(_PATTERN_COLUMN, _("Expected speech pattern"))
		# Translators: Header of the steps list column telling whether the safety check
		# is enforced for that step.
		self.stepsList.InsertColumn(_ENFORCED_COLUMN, _("Enforced"))
		# Translators: Header of the steps list column holding the delay in seconds
		# waited before pressing that step's key.
		self.stepsList.InsertColumn(_DELAY_COLUMN, _("Delay (seconds)"))
		for index, step in enumerate(self._steps):
			self.stepsList.Append(
				(
					step.key,
					step.spoken,
					self._patterns[index],
					self._enforcedLabel(self._enforces[index]),
					self._formatDelay(self._delays[index]),
				),
			)
		self.stepsList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onStepSelected)

		self.patternEdit = sHelper.addLabeledControl(
			# Translators: Label of the edit field holding the expected speech pattern
			# for the selected macro step. * matches any text.
			_("Expected speech &pattern, use * as a wildcard:"),
			wx.TextCtrl,
		)
		self.patternEdit.Bind(wx.EVT_TEXT, self.onPatternChanged)

		self.enforceCheckbox = sHelper.addItem(
			# Translators: Label of the checkbox that turns safety check enforcement
			# on for the selected macro step.
			wx.CheckBox(self, label=_("&Enforce safety check for this step")),
		)
		self.enforceCheckbox.Bind(wx.EVT_CHECKBOX, self.onEnforceChanged)

		self.useRecordedButton = sHelper.addItem(
			# Translators: Label of the button that copies the recorded speech of the
			# selected step into its expected speech pattern.
			wx.Button(self, label=_("&Use recorded speech as pattern")),
		)
		self.useRecordedButton.Bind(wx.EVT_BUTTON, self.onUseRecorded)

		self.delayEdit = sHelper.addLabeledControl(
			# Translators: Label of the edit field holding the delay in seconds waited
			# before pressing the selected macro step's key.
			_("&Delay in seconds before pressing this key:"),
			wx.TextCtrl,
		)
		self.delayEdit.Bind(wx.EVT_TEXT, self.onDelayChanged)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.SetSizerAndFit(mainSizer)
		if self._steps:
			self.stepsList.Select(0)
			self.stepsList.Focus(0)
		self.stepsList.SetFocus()
		self.CentreOnScreen()

	@staticmethod
	def _enforcedLabel(enforced):
		if enforced:
			# Translators: Shown in the enforced column for steps whose safety check is on.
			return _("Yes")
		# Translators: Shown in the enforced column for steps whose safety check is off.
		return _("No")

	@staticmethod
	def _formatDelay(delay):
		return f"{round(delay, 2):g}"

	@staticmethod
	def _parseDelay(value):
		"""Return the delay a user typed as a clamped float, or None if it is not a number."""
		try:
			delay = float(value.strip().replace(",", "."))
		except ValueError:
			return None
		return clampDelay(delay)

	@property
	def _currentIndex(self):
		index = self.stepsList.GetFirstSelected()
		return index if index >= 0 else None

	def onStepSelected(self, evt):
		index = evt.GetIndex()
		self._updatingPatternEdit = True
		try:
			self.patternEdit.SetValue(self._patterns[index])
		finally:
			self._updatingPatternEdit = False
		self.enforceCheckbox.SetValue(self._enforces[index])
		self._updatingDelayEdit = True
		try:
			self.delayEdit.SetValue(self._formatDelay(self._delays[index]))
		finally:
			self._updatingDelayEdit = False

	def onPatternChanged(self, evt):
		if self._updatingPatternEdit:
			return
		index = self._currentIndex
		if index is None:
			return
		self._patterns[index] = self.patternEdit.GetValue()
		self.stepsList.SetItem(index, _PATTERN_COLUMN, self._patterns[index])

	def onEnforceChanged(self, evt):
		index = self._currentIndex
		if index is None:
			return
		self._enforces[index] = self.enforceCheckbox.GetValue()
		self.stepsList.SetItem(index, _ENFORCED_COLUMN, self._enforcedLabel(self._enforces[index]))

	def onDelayChanged(self, evt):
		if self._updatingDelayEdit:
			return
		index = self._currentIndex
		if index is None:
			return
		delay = self._parseDelay(self.delayEdit.GetValue())
		if delay is None:
			return
		self._delays[index] = delay
		self.stepsList.SetItem(index, _DELAY_COLUMN, self._formatDelay(delay))

	def onUseRecorded(self, evt):
		index = self._currentIndex
		if index is None:
			return
		self.patternEdit.SetValue(self._steps[index].spoken)
		self.patternEdit.SetFocus()

	def applyTo(self, macro):
		"""Write the edited patterns, enforcement flags and delays back into the macro."""
		for step, pattern, enforce, delay in zip(macro.steps, self._patterns, self._enforces, self._delays):
			step.expected = pattern
			step.enforce = enforce
			step.delay = delay


class MacroConfigurationDialog(wx.Dialog):
	"""Lets the user change the add-on wide settings stored in NVDA's configuration."""

	def __init__(self, parent):
		super().__init__(
			parent,
			# Translators: Title of the macros configuration dialog.
			title=_("Macros configuration"),
		)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		self.silenceCheckbox = sHelper.addItem(
			# Translators: Label of the checkbox that silences NVDA speech while
			# a macro is playing.
			wx.CheckBox(self, label=_("&Silence speech while running a macro")),
		)
		self.silenceCheckbox.SetValue(config.conf["macros"]["silenceSpeechWhilePlaying"])

		self.loopDelayEdit = sHelper.addLabeledControl(
			# Translators: Label of the edit field holding the pause in milliseconds
			# between two runs of a macro played on repeat.
			_("&Delay in milliseconds between runs of a looping macro:"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=0,
			max=60000,
			initial=config.conf["macros"]["loopDelayMs"],
		)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.SetSizerAndFit(mainSizer)
		self.silenceCheckbox.SetFocus()
		self.CentreOnScreen()

	def applyToConfig(self):
		"""Write the edited settings into NVDA's configuration."""
		config.conf["macros"]["silenceSpeechWhilePlaying"] = self.silenceCheckbox.IsChecked()
		config.conf["macros"]["loopDelayMs"] = self.loopDelayEdit.GetValue()
