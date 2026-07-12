Using the file NVDA_ADDON_STRUCTURES.md and folder "d:\code\python\NVDA stuff\nvda" which contains NVDA's source code, figure out how to leverage all of NVDA's capabilities to make an add-on. Create an Add-On that does the following:

I want to make a macros add-on
press layered keystroke alt shift NVDA m
shift + number from 1 to 0: start recording keystrokes on that macro (excpet shift NVDA alt m)
records the macro, including how long you wait between keypresses and all the speech NVDA gives.
then hit alt shift NVDA m: since it was recording, this causes it to stop recording and send keys normally.

pressing a number, does all the keystrokes on that macro

alt+number: lets you put safety checks of things that NVDA should be speaking after certain keys are pressed and stopped if not
this is off by default, it records what NVDA has spoken after every key press but it's not enforced unless you mark that slot as enforced
lets you change what you expect in an edit field
obviously allows wildcards
kind of regexp but not really, like
imagine after pressing tab 5 times you must be in "SAve button"
you can use s*ve, S*ve, save, Save, * button...

Add tests

Make sure all strings are translator ready prefixing them with the _ fucntion provided by initTranslation
Uncomment the sys.path dependency lines and add .venv\Lib\site-packages (we wil use uv).
