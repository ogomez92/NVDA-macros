# Version 1.0.0

Initial release.

* Ten stacks of ten macro slots driven by the `NVDA+alt+shift+m` layer: number to play, shift+number to record, alt+number to edit safety checks, left/right arrows to switch stacks, escape to exit.
* Recording captures keystrokes, the pauses between them, and everything NVDA spoke after each keystroke.
* Playback replays the keystrokes with the recorded timing; NVDA commands run as commands, everything else goes to the application. `NVDA+alt+shift+m` stops a running playback.
* Optional per-step safety checks: playback stops when NVDA's speech after an enforced keystroke does not match that step's expected wildcard pattern (`*` matches anything, case insensitive, matched anywhere in the spoken text).
* Macros, safety checks, and the selected stack persist in `macros.json` inside the NVDA configuration directory.
