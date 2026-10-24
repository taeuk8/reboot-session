"""Windows entry point. --demo is safe on any platform with Tk installed."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='Reboot Session — Windows 작업 환경 복원')
    parser.add_argument('--demo', action='store_true', help='실제 실행·재시작 없는 미리보기')
    parser.add_argument('--restore', metavar='PLAN_ID')
    args = parser.parse_args()
    if sys.platform != 'win32' and not args.demo:
        parser.error('Windows용 앱입니다. 이 컴퓨터에서는 --demo로 실행하세요.')
    # One Windows instance per user; prevents concurrent restores and overwriting startup registration.
    mutex = None
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        suffix = os.environ.get('USERNAME', 'user') + ('-demo' if args.demo else '')
        mutex = kernel.CreateMutexW(None, False, 'Local\\RebootSession-' + suffix)
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            ctypes.windll.user32.MessageBoxW(None, 'Reboot Session이 이미 실행 중입니다.', 'Reboot Session', 0)
            return
    from reboot_session.ui import App
    try:
        App(demo=args.demo, restore_id=args.restore).mainloop()
    finally:
        if mutex:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()
