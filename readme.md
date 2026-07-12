# Macros

Record and replay keyboard macros in ten stacks of ten slots, complete with the pauses between keystrokes and everything NVDA spoke while you recorded.

## The macros layer

Press `NVDA+alt+shift+m` to enter the macros layer. Inside the layer, the number row keys `1` to `0` address macro slots 1 to 10 of the current stack:

* `1` to `0`: play the macro stored in that slot.
* `shift+1` to `shift+0`: start recording keystrokes into that slot.
* `alt+1` to `alt+0`: open the safety checks dialog for that slot.
* `left arrow` and `right arrow`: switch to the previous or next macro stack. NVDA announces the stack number and how many macros it holds, and the layer stays active so you can press a number right away.
* `escape`: leave the layer without doing anything.

Any other key leaves the layer with a low beep.

## Stacks

There are ten independent stacks of ten macros each, so you can keep up to one hundred macros organized by task or application. All numbered commands, playing, recording and editing safety checks, work on the current stack. The selected stack is remembered across NVDA restarts.

## Recording

After pressing `shift` plus a number, everything you type is recorded into that slot: the keystrokes themselves, how long you waited between them, and all the speech NVDA produced after each keystroke. Press `NVDA+alt+shift+m` to stop recording; the stop command itself is never recorded. If you stopped without pressing any key, the slot is left unchanged.

## Playback

Enter the layer and press the macro's number. The keystrokes are replayed with the same pauses you used while recording. NVDA commands that are part of the macro run as NVDA commands; everything else is sent to the application. A short high beep signals the end of the macro. Press `NVDA+alt+shift+m` while a macro is playing to stop it immediately.

Note that NVDA does not echo characters typed by a playing macro, so the speech you hear during playback comes from the applications you are driving, for example focus changes and control announcements.

## Safety checks

While recording, the add-on remembers what NVDA spoke after every keystroke. Safety checks are set per step and are off by default: to manage them, enter the layer and press `alt` plus the macro's number.

The dialog shows each step with its keystroke, the recorded speech, the expected speech pattern, and whether the check is enforced. Select a step, edit its pattern in the edit field, and check "Enforce safety check for this step" to turn enforcement on for exactly that step; other steps can stay unchecked. The "Use recorded speech as pattern" button resets the pattern to what NVDA originally spoke.

During playback, every enforced step must produce speech matching its pattern within a few seconds, otherwise the macro stops with an error message telling you which step failed, what was expected, and what was heard. This protects you from a macro blindly typing into the wrong window.

Patterns are matched anywhere inside the spoken text, ignoring case, and `*` matches any run of characters. For example, after tabbing to a button announced as "Save button", all of these patterns match: `save`, `Save`, `s*ve`, `S*ve`, `* button`. A step with an empty pattern is never checked.

## Storage

Macros, their safety checks, and the selected stack are saved to `macros.json` in your NVDA configuration directory as soon as recording stops, a stack is switched, or the safety checks dialog is accepted, so everything survives NVDA restarts.

## Development

This repository uses the NVDA add-on scons template with [uv](https://docs.astral.sh/uv/):

* Build the installable package: `uv run scons` (produces `macros-<version>.nvda-addon`).
* Run the unit tests for the macro engine: `uv run python -m unittest discover -s tests -v`.
* Lint and format: `uv run ruff check .` and `uv run ruff format addon tests`.
* Generate the translation template: `uv run scons pot`.

The add-on sources live in `addon/globalPlugins/macros/`: `macroEngine.py` holds the NVDA-independent model (recording, wildcard matching, persistence) covered by the tests, `__init__.py` wires it to NVDA (layered gestures, keystroke capture through `inputCore.decide_executeGesture`, speech capture through `speech.extensions.pre_speech`, playback through `inputCore.manager.emulateGesture`), and `dialogs.py` contains the safety checks dialog.
