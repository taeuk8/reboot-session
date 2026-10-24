from __future__ import annotations
import base64
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse
from .core import item, validate_task, atomic_write, read_json, now

IS_WINDOWS = sys.platform == 'win32'
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def require_windows():
    if not IS_WINDOWS:
        raise RuntimeError('이 기능은 Windows에서만 실행됩니다. --demo로 화면을 확인할 수 있습니다.')


def ps(script, timeout=30):
    require_windows()
    code = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();$ErrorActionPreference='Stop';" + script
    encoded = base64.b64encode(code.encode('utf-16le')).decode('ascii')
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                         capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
                         creationflags=NO_WINDOW)
    if run.returncode:
        raise RuntimeError(run.stderr.strip()[-1200:] or 'PowerShell 실행 실패')
    return json.loads(run.stdout.lstrip('\ufeff').strip() or 'null')


def rows(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    candidates = {
        'wezterm': [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WezTerm/wezterm.exe'],
        'chrome': [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                   Path(os.environ.get('LOCALAPPDATA', '')) / 'Google/Chrome/Application/chrome.exe'],
    }
    for candidate in candidates.get(name, []):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f'{name} 실행 파일을 찾을 수 없습니다. 설치 경로를 PATH에 추가해주세요.')


def wez_cwd(uri):
    if not uri:
        return ''
    parsed = urlparse(uri)
    if parsed.scheme != 'file':
        return ''
    path = unquote(parsed.path)
    if len(path) > 2 and path[0] == '/' and path[2] == ':':
        return path[1:]
    # Do not interpret remote/WSL paths as native Windows folders.
    return path if path.startswith('//') else ''


def collect(tasks=()):
    require_windows()
    collected, warnings = [], []
    processes = rows(ps("@(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | ForEach-Object {"
                       "try {@{pid=$_.Id;name=$_.ProcessName;title=$_.MainWindowTitle;path=$_.Path;handle=$_.MainWindowHandle.ToInt64()}} catch {}}) | ConvertTo-Json -Depth 4"))
    skip = {'chrome', 'excel', 'explorer', 'wezterm', 'wezterm-gui', 'python', 'pythonw', 'rebootsession'}
    seen = set()
    for proc in processes:
        if not proc.get('path') or proc['name'].lower() in skip or proc['path'] in seen:
            continue
        seen.add(proc['path'])
        collected.append(item('app', proc['title'] or proc['name'], {'path': proc['path']},
                              proc['name'] + ' · 앱만 실행', selected=False,
                              warning='문서·내부 상태는 복원하지 않습니다.'))
    if any(p['name'].lower() == 'chrome' for p in processes):
        collected.append(item('chrome', 'Chrome · 이전 세션 열기', {},
                              'Chrome 자체 세션 복원 사용 · 기본 프로필',
                              warning='정확한 창·탭은 Chrome JSON 가져오기를 사용하세요. 시크릿 창 제외.'))
    if any(p['name'].lower() == 'excel' for p in processes):
        try:
            excel = ps("$e=[Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application');"
                       "$a=@();foreach($w in $e.Workbooks){$a+=@{name=$w.Name;path=$w.FullName;"
                       "has_path=([bool]$w.Path);saved=[bool]$w.Saved;sheet=[string]$w.ActiveSheet.Name}};"
                       "ConvertTo-Json -InputObject $a -Depth 4")
            for book in rows(excel):
                if not book['has_path'] or not book['saved']:
                    warnings.append('Excel 저장 필요: ' + book['name'] + ' (저장 후 목록을 새로고침하세요)')
                if book['has_path']:
                    collected.append(item('excel', book['name'], {'path': book['path'], 'sheet': book['sheet']},
                                          'Excel · ' + book['sheet'], warning='' if book['saved'] else '저장하지 않은 변경 있음'))
        except Exception as error:
            warnings.append('Excel 문서 수집 실패: ' + str(error))
    try:
        folders = ps("$s=New-Object -ComObject Shell.Application;$a=@();foreach($w in $s.Windows()){"
                     "try {if($w.FullName -match 'explorer.exe$'){$a+= [string]$w.Document.Folder.Self.Path}} catch {}};"
                     "ConvertTo-Json -InputObject $a")
        for folder in dict.fromkeys(rows(folders)):
            if Path(folder).is_dir():
                collected.append(item('folder', Path(folder).name or folder, {'path': folder}, folder))
    except Exception as error:
        warnings.append('탐색기 수집 실패: ' + str(error))
    configured_cwds = {str(t.get('cwd', '')).casefold().rstrip('\\/') for t in tasks}
    try:
        wez = executable('wezterm')
        run = subprocess.run([wez, 'cli', 'list', '--format', 'json'], capture_output=True,
                             encoding='utf-8', errors='replace', timeout=12, creationflags=NO_WINDOW)
        if run.returncode:
            if any(p['name'].lower().startswith('wezterm') for p in processes):
                warnings.append('WezTerm 패널 수집 실패: CLI 연결을 확인하세요.')
        else:
            for pane in json.loads(run.stdout):
                cwd = wez_cwd(pane.get('cwd', ''))
                if not cwd:
                    warnings.append('WezTerm 경로 확인 필요: ' + pane.get('title', '패널') + ' · WSL/SSH는 작업을 직접 등록하세요.')
                    continue
                if cwd.casefold().rstrip('\\/') in configured_cwds:
                    continue
                task = {'name': pane.get('title', cwd), 'cwd': cwd, 'tool': 'shell', 'environment': 'windows',
                        'source_pane': pane['pane_id']}
                collected.append(item('terminal', task['name'], task,
                                      'WezTerm · ' + cwd, warning='셸을 새 창으로 엽니다. AI 세션은 작업 등록 필요.'))
    except FileNotFoundError:
        warnings.append('WezTerm을 찾지 못했습니다. 설치되어 있다면 PATH를 확인하세요.')
    except Exception as error:
        warnings.append('WezTerm 수집 실패: ' + str(error))
    for task in tasks:
        validate_task(task)
        collected.append(item('terminal', task['name'], task,
                              f"등록된 작업 · {task['tool']} · {task['cwd']}",
                              warning='등록한 명령을 다시 실행합니다.' if task['tool'] == 'command' else ''))
    return collected, warnings


def terminal_args(task):
    validate_task(task)
    tool = task['tool']
    command = []
    if tool == 'codex':
        command = ['codex', 'resume', task['session']]
    elif tool == 'opencode':
        command = ['opencode', '--session', task['session']]
    elif tool == 'command':
        command = ['powershell.exe', '-NoExit', '-Command', task['command']]
    if task.get('environment') == 'wsl':
        args = ['wsl.exe']
        if task.get('distro'):
            args += ['--distribution', task['distro']]
        args += ['--cd', task['cwd']]
        if tool == 'command':
            args += ['--exec', 'bash', '-lc', task['command']]
        elif command:
            args += ['--exec'] + command
        return args
    # PowerShell resolves npm .cmd/.ps1 shims. Encode literal argv, never interpolate into shell code.
    if tool in ('codex', 'opencode'):
        literals = ' '.join("'" + arg.replace("'", "''") + "'" for arg in command)
        source = '& ' + literals
        encoded = base64.b64encode(source.encode('utf-16le')).decode()
        return ['powershell.exe', '-NoExit', '-EncodedCommand', encoded]
    return command


def launch(row):
    require_windows()
    kind, payload = row['kind'], row['payload']
    if kind in ('folder', 'app'):
        path = payload['path']
        if not Path(path).exists():
            raise FileNotFoundError(path)
        if kind == 'folder':
            subprocess.Popen(['explorer.exe', path])
        else:
            subprocess.Popen([path])
    elif kind == 'excel':
        path = payload['path']
        if not Path(path).is_file() and not path.startswith('https://'):
            raise FileNotFoundError(path)
        # Open through COM to select the saved sheet; never execute macros explicitly.
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        ps("$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))|ConvertFrom-Json;"
           "try {$e=[Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')}"
           "catch {$e=New-Object -ComObject Excel.Application};$e.Visible=$true;"
           "$w=$e.Workbooks.Open($p.path);if($p.sheet){try {$w.Sheets.Item($p.sheet).Activate()} catch {}}; 'true'")
    elif kind == 'chrome':
        args = [executable('chrome')]
        profile = payload.get('profile', 'Default')
        if '/' in profile or '\\' in profile or profile.startswith('-'):
            raise ValueError('Chrome 프로필 이름이 잘못되었습니다.')
        args += ['--profile-directory=' + profile]
        urls = payload.get('urls')
        if urls:
            if not all(urlparse(u).scheme in ('http', 'https', 'file', 'chrome') for u in urls):
                raise ValueError('지원하지 않는 URL입니다.')
            args += ['--new-window'] + urls
        else:
            args += ['--restore-last-session']
        subprocess.Popen(args)
    elif kind == 'terminal':
        task = validate_task(payload)
        args = [executable('wezterm'), 'start', '--always-new-process']
        if task.get('environment', 'windows') == 'windows':
            if not Path(task['cwd']).is_dir():
                raise FileNotFoundError(task['cwd'])
            args += ['--cwd', task['cwd']]
        command = terminal_args(task)
        if command:
            args += ['--'] + command
        subprocess.Popen(args)
    else:
        raise ValueError('지원하지 않는 항목')
    return '실행 요청 완료 · 프로그램 내부 상태는 화면에서 확인하세요.'


def startup_path():
    require_windows()
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/RebootSession.cmd'


def launch_command(extra=()):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *extra]
    root = Path(__file__).resolve().parent.parent
    python = Path(sys.executable)
    pythonw = python.with_name('pythonw.exe')
    return [str(pythonw if pythonw.exists() else python), str(root / 'app.py'), *extra]


def arm(root, saved):
    require_windows()
    root = Path(root)
    argv = launch_command(['--restore', saved['id']])
    if any('"' in arg for arg in argv):
        raise ValueError('실행 경로에 큰따옴표를 사용할 수 없습니다.')
    command = ' '.join('"' + arg + '"' for arg in argv)
    # cmd expands percent even inside double quotes. Refuse unsafe installation paths.
    if any(c in command for c in ('%', '\n', '\r')):
        raise ValueError('설치 경로에 % 또는 줄바꿈을 사용할 수 없습니다.')
    target = startup_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = {'plan_id': saved['id'], 'armed_at': now(), 'boot': boot_id()}
    atomic_write(root / 'pending.json', pending)
    try:
        content = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n' + command + '\r\n').encode('utf-8')
        target.write_bytes(content)
        if target.read_bytes() != content:
            raise RuntimeError('로그인 후 실행 등록 검증 실패')
    except Exception:
        disarm(root)
        raise


def boot_id():
    return ps('(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString("o")')


def disarm(root):
    require_windows()
    startup_path().unlink(missing_ok=True)
    (Path(root) / 'pending.json').unlink(missing_ok=True)


def request_restart():
    require_windows()
    # No /f: applications are allowed to block shutdown for unsaved changes.
    subprocess.run(['shutdown.exe', '/r', '/t', '0'], check=True, creationflags=NO_WINDOW)
