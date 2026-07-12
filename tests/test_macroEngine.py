# -*- coding: UTF-8 -*-
# Macros add-on for NVDA
# Copyright (C) 2026 Oscar Gomez
# This file is covered by the GNU General Public License.
# See the file COPYING.txt for more details.

"""Tests for the NVDA-independent macro engine."""

import json
import os
import sys
import tempfile
import unittest

_PLUGIN_DIR = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"addon",
	"globalPlugins",
	"macros",
)
if _PLUGIN_DIR not in sys.path:
	sys.path.insert(0, _PLUGIN_DIR)

import macroEngine  # noqa: E402
from macroEngine import (  # noqa: E402
	Macro,
	MacroRecorder,
	MacroStep,
	MacroStore,
	clampDelay,
	cycleStack,
	keyNameForSlot,
	normalizeSpokenText,
	slotForKeyName,
	wildcardMatch,
	wildcardToRegex,
)


class WildcardMatchTests(unittest.TestCase):
	"""The wildcard language promised to users: case insensitive, * matches
	any run of characters, and the pattern may match anywhere in the text."""

	def test_examplesFromTheSpec(self):
		# After tabbing onto "Save button", all of these must pass.
		for pattern in ("s*ve", "S*ve", "save", "Save", "* button"):
			with self.subTest(pattern=pattern):
				self.assertTrue(wildcardMatch(pattern, "Save button"))

	def test_caseInsensitive(self):
		self.assertTrue(wildcardMatch("SAVE BUTTON", "save button"))
		self.assertTrue(wildcardMatch("save", "SAVE BUTTON"))

	def test_matchesAnywhereInText(self):
		self.assertTrue(wildcardMatch("button", "Save button unavailable"))
		self.assertTrue(wildcardMatch("save", "Do you want to save your work?"))

	def test_starMatchesAnyRun(self):
		self.assertTrue(wildcardMatch("s*n", "save button"))  # spans words
		self.assertTrue(wildcardMatch("sa*ve", "save"))  # empty run
		self.assertTrue(wildcardMatch("*", "anything at all"))
		self.assertTrue(wildcardMatch("*", ""))

	def test_multipleStars(self):
		self.assertTrue(wildcardMatch("s*e b*n", "Save button"))
		self.assertFalse(wildcardMatch("s*e b*z", "Save button"))

	def test_mismatch(self):
		self.assertFalse(wildcardMatch("load", "Save button"))
		self.assertFalse(wildcardMatch("saveX", "Save button"))

	def test_emptyPatternAlwaysMatches(self):
		self.assertTrue(wildcardMatch("", "Save button"))
		self.assertTrue(wildcardMatch("   ", "Save button"))
		self.assertTrue(wildcardMatch("", ""))

	def test_regexCharactersAreLiteral(self):
		self.assertTrue(wildcardMatch("1.5 items", "1.5 items"))
		self.assertFalse(wildcardMatch("1.5", "1x5"))  # . must not act as a regex dot
		self.assertTrue(wildcardMatch("(2 of 10)", "row 5 (2 of 10)"))
		self.assertFalse(wildcardMatch("[abc]", "b"))  # no character classes

	def test_whitespaceIsNormalized(self):
		self.assertTrue(wildcardMatch("save   button", "save button"))
		self.assertTrue(wildcardMatch("save button", "save\n\tbutton"))

	def test_wildcardToRegexEscapes(self):
		self.assertEqual(wildcardToRegex("a+b*c"), r"a\+b.*c")

	def test_normalizeSpokenText(self):
		self.assertEqual(normalizeSpokenText("  Save \n button\t"), "Save button")
		self.assertEqual(normalizeSpokenText(""), "")


class SlotKeyTests(unittest.TestCase):
	def test_roundTripForAllSlots(self):
		for slot in range(1, macroEngine.SLOT_COUNT + 1):
			with self.subTest(slot=slot):
				self.assertEqual(slotForKeyName(keyNameForSlot(slot)), slot)

	def test_zeroKeyIsSlotTen(self):
		self.assertEqual(keyNameForSlot(10), "0")
		self.assertEqual(slotForKeyName("0"), 10)
		self.assertEqual(slotForKeyName("1"), 1)

	def test_nonNumberKeysHaveNoSlot(self):
		for keyName in ("a", "escape", "f1", "numpad1", ""):
			with self.subTest(keyName=keyName):
				self.assertIsNone(slotForKeyName(keyName))

	def test_invalidSlotRaises(self):
		for slot in (0, 11, -1):
			with self.subTest(slot=slot):
				with self.assertRaises(ValueError):
					keyNameForSlot(slot)

	def test_clampDelay(self):
		self.assertEqual(clampDelay(-5.0), 0.0)
		self.assertEqual(clampDelay(1.5), 1.5)
		self.assertEqual(clampDelay(macroEngine.MAX_STEP_DELAY + 100), macroEngine.MAX_STEP_DELAY)

	def test_cycleStackWrapsAround(self):
		self.assertEqual(cycleStack(1, 1), 2)
		self.assertEqual(cycleStack(macroEngine.STACK_COUNT, 1), 1)
		self.assertEqual(cycleStack(1, -1), macroEngine.STACK_COUNT)
		self.assertEqual(cycleStack(5, -1), 4)


class MacroRecorderTests(unittest.TestCase):
	def test_firstKeystrokeHasZeroDelay(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 100.0)
		self.assertEqual(recorder.steps[0].delay, 0.0)

	def test_delaysAreMeasuredBetweenKeystrokes(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 100.0)
		recorder.addKeystroke("tab", 100.25)
		recorder.addKeystroke("enter", 102.0)
		self.assertEqual([step.delay for step in recorder.steps], [0.0, 0.25, 1.75])

	def test_hugeAndNegativeGapsAreClamped(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 100.0)
		recorder.addKeystroke("tab", 100.0 + macroEngine.MAX_STEP_DELAY * 5)
		recorder.addKeystroke("tab", 90.0)  # clock went backwards
		self.assertEqual(recorder.steps[1].delay, macroEngine.MAX_STEP_DELAY)
		self.assertEqual(recorder.steps[2].delay, 0.0)

	def test_speechAttachesToLastKeystroke(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 1.0)
		recorder.addSpeech("Save button")
		recorder.addKeystroke("tab", 2.0)
		recorder.addSpeech("Cancel")
		recorder.addSpeech("button")
		self.assertEqual(recorder.steps[0].spoken, "Save button")
		self.assertEqual(recorder.steps[1].spoken, "Cancel button")

	def test_speechBeforeFirstKeystrokeIsDropped(self):
		recorder = MacroRecorder()
		recorder.addSpeech("Recording macro 1")
		self.assertFalse(recorder.hasSteps)
		recorder.addKeystroke("tab", 1.0)
		self.assertEqual(recorder.steps[0].spoken, "")

	def test_blankSpeechIsIgnored(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 1.0)
		recorder.addSpeech("   \n ")
		self.assertEqual(recorder.steps[0].spoken, "")

	def test_finishDefaultsExpectedToSpoken(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 1.0)
		recorder.addSpeech("Save button")
		recorder.addKeystroke("enter", 2.0)
		macro = recorder.finish()
		self.assertEqual(macro.steps[0].expected, "Save button")
		self.assertEqual(macro.steps[1].expected, "")

	def test_finishLeavesSafetyChecksOff(self):
		recorder = MacroRecorder()
		recorder.addKeystroke("tab", 1.0)
		recorder.addSpeech("Save button")
		self.assertFalse(any(step.enforce for step in recorder.finish().steps))


class SerializationTests(unittest.TestCase):
	def test_stepRoundTrip(self):
		step = MacroStep(
			key="control+shift+t",
			delay=0.5,
			spoken="tab restored",
			expected="tab *",
			enforce=True,
		)
		self.assertEqual(MacroStep.fromDict(step.toDict()), step)

	def test_macroRoundTrip(self):
		macro = Macro(
			steps=[
				MacroStep(key="tab", delay=0.1, spoken="Save button", expected="s*ve", enforce=True),
				MacroStep(key="enter", delay=0.2, spoken="Saved", expected="", enforce=False),
			],
		)
		self.assertEqual(Macro.fromDict(macro.toDict()), macro)

	def test_stepDefaults(self):
		step = MacroStep.fromDict({"key": "enter"})
		self.assertEqual(step, MacroStep(key="enter", delay=0.0, spoken="", expected="", enforce=False))

	def test_legacyMacroLevelEnforceAppliesToAllSteps(self):
		# Version 1 files stored one enforce flag on the whole macro.
		data = {
			"enforce": True,
			"steps": [{"key": "tab"}, {"key": "enter", "enforce": False}],
		}
		macro = Macro.fromDict(data)
		self.assertTrue(all(step.enforce for step in macro.steps))
		self.assertNotIn("enforce", macro.toDict())

	def test_stepDelayIsClampedOnConstruction(self):
		self.assertEqual(MacroStep(key="tab", delay=-2.0).delay, 0.0)
		self.assertEqual(MacroStep.fromDict({"key": "tab", "delay": 1e9}).delay, macroEngine.MAX_STEP_DELAY)

	def test_invalidStepsRaise(self):
		badSteps = (
			"not a dict",
			{},  # no key
			{"key": ""},
			{"key": 5},
			{"key": "tab", "delay": "fast"},
			{"key": "tab", "delay": True},
			{"key": "tab", "spoken": 3},
			{"key": "tab", "expected": None},
			{"key": "tab", "enforce": "yes"},
		)
		for data in badSteps:
			with self.subTest(data=data):
				with self.assertRaises(ValueError):
					MacroStep.fromDict(data)

	def test_invalidMacrosRaise(self):
		badMacros = (
			[],
			{"enforce": "yes"},
			{"steps": "nope"},
			{"steps": [{"key": ""}]},
		)
		for data in badMacros:
			with self.subTest(data=data):
				with self.assertRaises(ValueError):
					Macro.fromDict(data)


class MacroStoreTests(unittest.TestCase):
	def setUp(self):
		self._tempDir = tempfile.TemporaryDirectory()
		self.addCleanup(self._tempDir.cleanup)
		self.path = os.path.join(self._tempDir.name, "macros.json")

	def test_loadMissingFileYieldsEmptyStore(self):
		store = MacroStore(self.path)
		store.load()
		self.assertEqual(store.macros, {})

	def test_saveAndLoadRoundTrip(self):
		store = MacroStore(self.path)
		store.macros[1] = Macro(
			steps=[
				MacroStep(key="tab", delay=0.25, spoken="Save button", expected="* button", enforce=True),
			],
		)
		store.macros[10] = Macro(steps=[MacroStep(key="NVDA+f7")])
		store.save()

		reloaded = MacroStore(self.path)
		reloaded.load()
		self.assertEqual(reloaded.macros, store.macros)

	def test_saveCreatesParentDirectory(self):
		nestedPath = os.path.join(self._tempDir.name, "sub", "dir", "macros.json")
		store = MacroStore(nestedPath)
		store.macros[2] = Macro(steps=[MacroStep(key="enter")])
		store.save()
		reloaded = MacroStore(nestedPath)
		reloaded.load()
		self.assertIn(2, reloaded.macros)

	def test_saveOverwritesAtomically(self):
		store = MacroStore(self.path)
		store.macros[1] = Macro(steps=[MacroStep(key="a")])
		store.save()
		store.macros[1] = Macro(steps=[MacroStep(key="b")])
		store.save()
		self.assertFalse(os.path.exists(self.path + ".tmp"))
		reloaded = MacroStore(self.path)
		reloaded.load()
		self.assertEqual(reloaded.macros[1].steps[0].key, "b")

	def test_corruptJsonRaisesValueError(self):
		with open(self.path, "w", encoding="utf-8") as fileObj:
			fileObj.write("{not json")
		store = MacroStore(self.path)
		with self.assertRaises(ValueError):
			store.load()
		self.assertEqual(store.macros, {})

	def test_unexpectedStructureRaisesValueError(self):
		for data in ([1, 2, 3], {"macros": "nope"}):
			with self.subTest(data=data):
				with open(self.path, "w", encoding="utf-8") as fileObj:
					json.dump(data, fileObj)
				with self.assertRaises(ValueError):
					MacroStore(self.path).load()

	def test_invalidSlotsAreSkipped(self):
		data = {
			"version": macroEngine.FILE_VERSION,
			"macros": {
				"1": Macro(steps=[MacroStep(key="tab")]).toDict(),
				"0": Macro(steps=[MacroStep(key="a")]).toDict(),  # out of range
				"11": Macro(steps=[MacroStep(key="a")]).toDict(),  # out of range
				"seven": Macro(steps=[MacroStep(key="a")]).toDict(),  # not a number
				"3": {"steps": [{"delay": 1.0}]},  # step without a key name
			},
		}
		with open(self.path, "w", encoding="utf-8") as fileObj:
			json.dump(data, fileObj)
		store = MacroStore(self.path)
		store.load()
		self.assertEqual(sorted(store.macros), [1])

	def test_stacksPersistIndependentlyWithCurrentStack(self):
		store = MacroStore(self.path)
		store.setStack(2)
		store.macros[1] = Macro(steps=[MacroStep(key="tab")])
		store.setStack(5)
		store.macros[1] = Macro(steps=[MacroStep(key="enter")])
		store.save()

		reloaded = MacroStore(self.path)
		reloaded.load()
		self.assertEqual(reloaded.currentStack, 5)
		self.assertEqual(reloaded.macros[1].steps[0].key, "enter")
		reloaded.setStack(2)
		self.assertEqual(reloaded.macros[1].steps[0].key, "tab")
		reloaded.setStack(3)
		self.assertEqual(reloaded.macros, {})

	def test_macrosPropertyFollowsCurrentStack(self):
		store = MacroStore(self.path)
		store.macros[4] = Macro(steps=[MacroStep(key="a")])
		store.setStack(9)
		self.assertEqual(store.macros, {})
		store.setStack(1)
		self.assertIn(4, store.macros)

	def test_setStackValidatesRange(self):
		store = MacroStore(self.path)
		for stack in (0, macroEngine.STACK_COUNT + 1, -3):
			with self.subTest(stack=stack):
				with self.assertRaises(ValueError):
					store.setStack(stack)

	def test_legacySingleStackFileLoadsIntoStackOne(self):
		# Versions 1 and 2 stored one flat "macros" mapping and no stacks.
		data = {"version": 2, "macros": {"3": Macro(steps=[MacroStep(key="tab")]).toDict()}}
		with open(self.path, "w", encoding="utf-8") as fileObj:
			json.dump(data, fileObj)
		store = MacroStore(self.path)
		store.load()
		self.assertEqual(store.currentStack, 1)
		self.assertEqual(sorted(store.stacks), [1])
		self.assertIn(3, store.macros)

	def test_invalidCurrentStackFallsBackToOne(self):
		for badCurrent in (0, 99, "five", True, None):
			with self.subTest(badCurrent=badCurrent):
				data = {
					"version": macroEngine.FILE_VERSION,
					"currentStack": badCurrent,
					"stacks": {},
				}
				with open(self.path, "w", encoding="utf-8") as fileObj:
					json.dump(data, fileObj)
				store = MacroStore(self.path)
				store.load()
				self.assertEqual(store.currentStack, 1)

	def test_invalidStackEntriesAreSkipped(self):
		data = {
			"version": macroEngine.FILE_VERSION,
			"currentStack": 1,
			"stacks": {
				"2": {"1": Macro(steps=[MacroStep(key="tab")]).toDict()},
				"0": {"1": Macro(steps=[MacroStep(key="a")]).toDict()},  # out of range
				"eleven": {"1": Macro(steps=[MacroStep(key="a")]).toDict()},  # not a number
			},
		}
		with open(self.path, "w", encoding="utf-8") as fileObj:
			json.dump(data, fileObj)
		store = MacroStore(self.path)
		store.load()
		self.assertEqual(sorted(store.stacks), [2])

	def test_emptyStacksAreNotSaved(self):
		store = MacroStore(self.path)
		store.setStack(7)
		_ = store.macros  # creates the empty stack in memory
		store.save()
		with open(self.path, "r", encoding="utf-8") as fileObj:
			data = json.load(fileObj)
		self.assertEqual(data["stacks"], {})
		self.assertEqual(data["currentStack"], 7)

	def test_savedFileIsHumanReadableJson(self):
		store = MacroStore(self.path)
		store.macros[1] = Macro(steps=[MacroStep(key="tab", spoken="Botón guardar")])
		store.save()
		with open(self.path, "r", encoding="utf-8") as fileObj:
			data = json.load(fileObj)
		self.assertEqual(data["version"], macroEngine.FILE_VERSION)
		# Non-ASCII speech must be stored readably, not as escape sequences.
		with open(self.path, "r", encoding="utf-8") as fileObj:
			self.assertIn("Botón", fileObj.read())


if __name__ == "__main__":
	unittest.main()
