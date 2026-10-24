from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timezone
from . import windows
from .core import (atomic_write, data_dir, fingerprint, item, now, plan,
                   read_json, RestoreEngine, validate, validate_task)

BG, PANEL, TEXT, MUTED, ACCENT = '#101827', '#182438', '#eef3fc', '#9aadc8', '#68dfbb'


class App(tk.Tk):
    def __init__(self, demo=False, restore_id=None):
        super().__init__()
        self.demo = demo
        self.root_dir = data_dir() / ('demo' if demo else '')
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.items, self.extra, self.warnings = [], [], []
        self.events = queue.Queue()
        self.busy = False
        self.title('Reboot Session' + (' · 미리보기' if demo else ''))
        self.geometry('1100x780')
        self.minsize(900, 650)
        self.configure(bg=BG)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.style()
        self.build()
        self.after(100, self.poll)
        if restore_id:
            self.after(350, lambda: self.auto_restore(restore_id))
        elif demo:
            self.capture()
        if (self.root_dir / 'pending.json').exists() and not restore_id:
            self.status.set('재시작 대기 계획이 있습니다. 재시작을 취소했다면 아래 예약 해제를 누르세요.')

    def style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Title.TLabel', font=('Segoe UI', 28, 'bold'))
        style.configure('TButton', background=PANEL, foreground=TEXT, padding=(12, 10), borderwidth=0)
        style.map('TButton', background=[('active', '#2d405a')], foreground=[('disabled', '#5d718c')])
        style.configure('Accent.TButton', background=ACCENT, foreground=BG, font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#94efcf')])
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=42, borderwidth=0)
        style.configure('Treeview.Heading', background='#22324b', foreground=MUTED, padding=10)
        style.map('Treeview', background=[('selected', '#304e68')])
        style.configure('TEntry', fieldbackground=PANEL, foreground=TEXT, padding=6)
        style.configure('TCombobox', fieldbackground=PANEL, foreground=TEXT, padding=6)

    def build(self):
        frame = ttk.Frame(self, padding=28)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='REBOOT SESSION / WINDOWS', style='Muted.TLabel').pack(anchor='w')
        ttk.Label(frame, text='다시 켜도, 하던 자리로.', style='Title.TLabel').pack(anchor='w', pady=(10, 5))
        ttk.Label(frame, text='현재 작업을 확인하고 저장하세요. 다음 로그인 후 선택한 작업을 다시 엽니다.',
                  style='Muted.TLabel').pack(anchor='w')
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill='x', pady=(24, 12))
        self.buttons = []
        for title, action in [('① 재시작 준비', self.capture), ('＋ 개발 작업', self.task_dialog),
                              ('＋ 파일·폴더', self.add_path), ('Chrome JSON 가져오기', self.import_chrome)]:
            self.button(toolbar, title, action).pack(side='left', padx=(0, 8))
        self.count = tk.StringVar(value='준비 버튼을 눌러 현재 작업을 수집하세요.')
        ttk.Label(frame, textvariable=self.count, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=('check', 'name', 'detail', 'state'), show='headings', selectmode='browse')
        for key, label, width in [('check', '복원', 55), ('name', '작업', 260), ('detail', '복원 범위', 420), ('state', '상태', 130)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key in ('name', 'detail'))
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Button-1>', self.click)
        self.tree.bind('<space>', self.toggle)
        self.tree.bind('<<TreeviewSelect>>', self.show_detail)
        self.detail = tk.StringVar(value='항목을 선택하면 복원 범위와 주의 사항을 볼 수 있습니다. 첫 열을 눌러 복원을 선택하세요.')
        ttk.Label(frame, textvariable=self.detail, wraplength=990, style='Muted.TLabel').pack(anchor='w', pady=(10, 6))
        self.notices = tk.Text(frame, height=4, bg=PANEL, fg='#f2cc88', relief='flat', font=('Segoe UI', 10), padx=12, pady=10, wrap='word')
        self.notices.pack(fill='x')
        self.set_notices(['저장하지 않은 문서와 진행 중인 명령은 그대로 이어지지 않습니다.'])
        footer = ttk.Frame(frame)
        footer.pack(fill='x', pady=(16, 0))
        self.button(footer, '저장만', self.save_only).pack(side='left', padx=(0, 8))
        self.button(footer, '저장한 상태 복원', self.manual_restore).pack(side='left', padx=(0, 8))
        self.button(footer, '실패 항목 재시도', lambda: self.manual_restore(retry=True)).pack(side='left')
        self.button(footer, '② 저장하고 다시 시작', self.restart, 'Accent.TButton').pack(side='right')
        bottom = ttk.Frame(frame)
        bottom.pack(fill='x', pady=(12, 0))
        self.status = tk.StringVar(value='미리보기 모드 · 실제 프로그램 실행과 재시작은 하지 않습니다.' if self.demo else '준비됨 · 자동 주기 저장 없음')
        ttk.Label(bottom, textvariable=self.status, style='Muted.TLabel', wraplength=800).pack(side='left')
        self.button(bottom, '재시작 예약 해제', self.cancel_pending).pack(side='right')

    def button(self, parent, text, command, style='TButton'):
        widget = ttk.Button(parent, text=text, command=command, style=style)
        self.buttons.append(widget)
        return widget

    def set_notices(self, notices):
        self.notices.configure(state='normal')
        self.notices.delete('1.0', 'end')
        self.notices.insert('1.0', '\n'.join('• ' + n for n in notices) or '• 확인 필요 사항이 없습니다. 복원 목록을 검토해주세요.')
        self.notices.configure(state='disabled')

    def config_tasks(self):
        path = self.root_dir / 'tasks.json'
        tasks = read_json(path) if path.exists() else []
        for task in tasks:
            validate_task(task)
        return tasks

    def work(self, operation, done):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.state(['disabled'])
        def run():
            try:
                value = operation()
                self.events.put(('done', done, value))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'progress':
                    _, row_id, state, detail = event
                    if self.tree.exists(row_id):
                        values = list(self.tree.item(row_id, 'values'))
                        values[3] = {'launched': '실행 요청됨', 'failed': '실패', 'launching': '확인 필요'}.get(state, state)
                        self.tree.item(row_id, values=values)
                    self.status.set(detail)
                    continue
                self.busy = False
                for button in self.buttons:
                    button.state(['!disabled'])
                if event[0] == 'error':
                    self.status.set('작업 실패 · 상태를 확인하고 다시 시도하세요.')
                    messagebox.showerror('작업을 완료하지 못했습니다', event[1], parent=self)
                else:
                    try:
                        event[1](event[2])
                    except Exception as error:
                        messagebox.showerror('작업 오류', str(error), parent=self)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def capture_values(self):
        if self.demo:
            return demo_items(), ['미리보기 데이터입니다. 실제 PC 상태를 수집하지 않았습니다.',
                                   'WezTerm 첫 버전은 패널을 각각 새 창으로 복원합니다. 분할 배치 복원은 미지원입니다.']
        captured, warnings = windows.collect(self.config_tasks())
        if any(r['kind'] == 'chrome' for r in self.extra):
            captured = [r for r in captured if r['kind'] != 'chrome']
        return captured, warnings

    def capture(self):
        self.status.set('현재 작업을 수집하고 있습니다…')
        self.work(self.capture_values, lambda result: self.display(result[0] + self.extra, result[1]))

    def display(self, items, warnings):
        self.items = list({r['id']: r for r in items}.values())
        self.warnings = warnings
        self.tree.delete(*self.tree.get_children())
        for row in self.items:
            self.tree.insert('', 'end', iid=row['id'], values=('✓' if row['selected'] else '—', row['label'], row['detail'], '확인 필요' if row['warning'] else '준비'))
        self.set_notices(warnings)
        self.update_count()
        self.status.set('목록을 검토한 뒤 저장하거나 재시작하세요.' + (' · 미리보기' if self.demo else ''))

    def update_count(self):
        self.count.set(f"전체 {len(self.items)}개 · 복원 선택 {sum(r['selected'] for r in self.items)}개 · 첫 열 클릭으로 선택 변경")

    def click(self, event):
        if self.tree.identify_column(event.x) == '#1':
            row_id = self.tree.identify_row(event.y)
            if row_id:
                self.toggle(row_id=row_id)

    def toggle(self, event=None, row_id=None):
        if self.busy:
            return
        selection = self.tree.selection()
        row_id = row_id or (selection[0] if selection else None)
        for row in self.items:
            if row['id'] == row_id:
                row['selected'] = not row['selected']
                values = list(self.tree.item(row_id, 'values'))
                values[0] = '✓' if row['selected'] else '—'
                self.tree.item(row_id, values=values)
        self.update_count()
        return 'break'

    def show_detail(self, event=None):
        chosen = self.tree.selection()
        for row in self.items:
            if chosen and row['id'] == chosen[0]:
                self.detail.set(row['detail'] + ('  |  ' + row['warning'] if row['warning'] else '') + '  |  ' + json.dumps(row['payload'], ensure_ascii=False))

    def save(self):
        if not any(row['selected'] for row in self.items):
            raise ValueError('복원할 작업을 하나 이상 선택해주세요.')
        saved = validate(plan(self.items, self.warnings))
        path = self.root_dir / 'plans' / (saved['id'] + '.json')
        atomic_write(path, saved)
        if validate(read_json(path)) != saved:
            raise ValueError('저장 결과가 일치하지 않습니다.')
        atomic_write(self.root_dir / 'last.json', {'id': saved['id']})
        return saved

    def save_only(self):
        try:
            saved = self.save()
            self.status.set('저장 완료 · ' + saved['created_at'] + ' · 재시작 예약은 하지 않았습니다.')
        except Exception as error:
            messagebox.showerror('저장 실패', str(error), parent=self)

    def load_last(self):
        index = read_json(self.root_dir / 'last.json')
        return self.load_plan(index['id'])

    def load_plan(self, identity):
        import uuid
        if str(uuid.UUID(identity)) != identity:
            raise ValueError('잘못된 계획 ID')
        saved = validate(read_json(self.root_dir / 'plans' / (identity + '.json')))
        if saved['owner'] != plan([])['owner']:
            raise ValueError('다른 Windows 사용자의 계획입니다.')
        return saved

    def restore(self, saved, retry=False):
        self.display(saved['items'], saved['warnings'])
        self.status.set('선택한 작업을 다시 열고 있습니다…')
        def operation():
            launch = (lambda row: '미리보기 · 실행하지 않음') if self.demo else windows.launch
            return RestoreEngine(self.root_dir, launch).run(saved, retry,
                lambda *args: self.events.put(('progress', *args)))
        def done(result):
            states = [r['state'] for r in result['items'].values()]
            self.status.set(f"복원 처리 완료 · 실행 요청 {states.count('launched')}개 / 실패 {states.count('failed')}개 / 확인 필요 {states.count('launching')}개. 실제 화면을 확인하세요.")
        self.work(operation, done)

    def manual_restore(self, retry=False):
        try:
            saved = self.load_last()
            prompt = ('실패·실행 중단 항목을 다시 실행할까요? 이미 열린 창이 있으면 중복될 수 있습니다.' if retry else
                      '저장한 목록의 프로그램과 명령을 지금 실행할까요? 재부팅하지 않으면 현재 창과 중복될 수 있습니다.')
            if messagebox.askyesno('복원 확인', prompt, parent=self):
                self.restore(saved, retry)
        except Exception as error:
            messagebox.showerror('복원할 수 없습니다', str(error), parent=self)

    def restart(self):
        if self.demo:
            messagebox.showinfo('미리보기', '실제 재시작은 Windows 실행 모드에서만 가능합니다.', parent=self)
            return
        if (self.root_dir / 'pending.json').exists():
            messagebox.showwarning('기존 예약 확인', '재시작 대기 계획이 있습니다. 예약을 해제한 다음 다시 준비해주세요.', parent=self)
            return
        self.status.set('목록 변경 여부를 다시 확인하고 있습니다…')
        def checked(result):
            fresh, warnings = result
            fresh += self.extra
            if fingerprint(fresh) != fingerprint(self.items) or warnings != self.warnings:
                chosen = {r['id']: r['selected'] for r in self.items}
                for row in fresh:
                    row['selected'] = chosen.get(row['id'], row['selected'])
                self.display(fresh, warnings)
                messagebox.showinfo('작업 상태가 바뀌었습니다', '목록을 갱신했습니다. 확인 후 다시 시작 버튼을 눌러주세요.', parent=self)
                return
            if any('Excel 저장 필요:' in w for w in warnings):
                messagebox.showwarning('Excel 저장 필요', '저장하지 않은 Excel 문서가 있습니다. 문서를 저장하고 목록을 새로고침하세요.', parent=self)
                return
            if not messagebox.askyesno('저장하고 Windows 다시 시작',
                    '선택한 작업을 저장하고 지금 Windows를 재시작합니다.\n\n저장하지 않은 문서를 먼저 저장하세요. 다음 로그인 후 복원이 시작됩니다.', parent=self):
                return
            try:
                saved = self.save()
                windows.arm(self.root_dir, saved)
                try:
                    windows.request_restart()
                except Exception:
                    windows.disarm(self.root_dir)
                    raise
                self.status.set('Windows 재시작 요청됨 · 취소했다면 재시작 예약 해제를 눌러주세요.')
            except Exception as error:
                messagebox.showerror('재시작을 중단했습니다', str(error), parent=self)
        self.work(self.capture_values, checked)

    def auto_restore(self, identity):
        try:
            if not windows.IS_WINDOWS or self.demo:
                raise ValueError('자동 복원은 Windows에서만 가능합니다.')
            pending = read_json(self.root_dir / 'pending.json')
            if pending['plan_id'] != identity:
                raise ValueError('예약된 계획과 일치하지 않습니다.')
            if pending['boot'] == windows.boot_id():
                raise ValueError('아직 재부팅되지 않았습니다. 자동 복원을 실행하지 않습니다.')
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(pending['armed_at'])).total_seconds()
            saved = self.load_plan(identity)
            windows.disarm(self.root_dir)  # consume once before any application is launched
            if not 0 <= age <= 86400:
                raise ValueError('24시간이 지난 예약입니다. 저장한 상태 복원 버튼으로 직접 복원하세요.')
            self.restore(saved)
        except Exception as error:
            self.status.set('자동 복원 보류 · ' + str(error))

    def cancel_pending(self):
        try:
            if not self.demo:
                windows.disarm(self.root_dir)
            self.status.set('재시작 복원 예약을 해제했습니다. 저장한 계획은 남아 있습니다.')
        except Exception as error:
            messagebox.showerror('예약 해제 실패', str(error), parent=self)

    def add_path(self):
        popup = messagebox.askyesnocancel('파일·폴더 추가', '파일을 추가하려면 예, 폴더를 추가하려면 아니요를 누르세요.', parent=self)
        if popup is None:
            return
        path = filedialog.askopenfilename(parent=self) if popup else filedialog.askdirectory(parent=self)
        if path:
            kind = 'excel' if Path(path).suffix.lower() in ('.xlsx', '.xls', '.xlsm', '.xlsb') else 'folder'
            if popup and kind != 'excel':
                messagebox.showinfo('지원 파일', '첫 버전은 Excel 파일과 폴더를 직접 추가할 수 있습니다.', parent=self)
                return
            self.extra.append(item(kind, Path(path).name, {'path': path}, path))
            self.display(self.items + self.extra, self.warnings)

    def import_chrome(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Chrome snapshot', '*.json')])
        if not path:
            return
        try:
            snapshot = read_json(path)
            if snapshot.get('format') != 'reboot-session-chrome-v1':
                raise ValueError('제공된 Chrome 확장 프로그램으로 내보낸 JSON이 필요합니다.')
            from urllib.parse import urlparse
            new = []
            profile = snapshot.get('profile', 'Default')
            if not isinstance(profile, str) or any(c in profile for c in ('/', '\\')):
                raise ValueError('잘못된 Chrome 프로필')
            for index, window in enumerate(snapshot['windows']):
                urls = [tab['url'] for tab in window['tabs'] if urlparse(tab.get('url', '')).scheme in ('http', 'https', 'file', 'chrome')]
                if urls:
                    new.append(item('chrome', f'Chrome · 창 {index + 1} · 탭 {len(urls)}개',
                                    {'profile': profile, 'urls': urls}, '내보낸 시점: ' + snapshot.get('captured_at', '알 수 없음'),
                                    warning='가져온 시점의 탭입니다. 재시작 전 변경했다면 다시 내보내세요.'))
            if not new:
                raise ValueError('복원할 수 있는 탭이 없습니다.')
            incoming = {r['payload']['profile'] for r in new}
            self.extra = [r for r in self.extra if r['kind'] != 'chrome' or r['payload'].get('profile') not in incoming] + new
            self.items = [r for r in self.items if r['kind'] != 'chrome' or (r['payload'].get('urls') and r['payload'].get('profile') not in incoming)]
            # Suppress the native fallback when explicit tab snapshots exist.
            self.display(self.items + self.extra, self.warnings)
        except Exception as error:
            messagebox.showerror('가져오기 실패', str(error), parent=self)

    def task_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title('개발 작업 등록')
        dialog.configure(bg=BG)
        dialog.geometry('650x620')
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='프로젝트와 대화 세션을 연결하세요', font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 12))
        values = {}
        for key, title, default, choices in [
            ('name', '작업 이름', '', None), ('cwd', '작업 폴더 (WSL은 /home/… 경로)', '', None),
            ('environment', '실행 환경', 'windows', ['windows', 'wsl']),
            ('distro', 'WSL 배포판 (선택)', '', None),
            ('tool', '도구', 'codex', ['codex', 'opencode', 'shell', 'command']),
            ('session', '대화 세션 ID (Codex / OpenCode)', '', None),
            ('command', '직접 실행할 명령 (command 도구만)', '', None)]:
            ttk.Label(frame, text=title, style='Muted.TLabel').pack(anchor='w', pady=(5, 2))
            var = tk.StringVar(value=default)
            values[key] = var
            widget = ttk.Combobox(frame, textvariable=var, values=choices, state='readonly') if choices else ttk.Entry(frame, textvariable=var)
            widget.pack(fill='x')
        ttk.Label(frame, text='세션 ID는 각 도구에서 확인해 입력하세요. 명령은 재실행해도 되는 작업만 등록하세요.',
                  wraplength=570, style='Muted.TLabel').pack(anchor='w', pady=12)
        def submit():
            try:
                task = validate_task({key: var.get().strip() for key, var in values.items()})
                tasks = self.config_tasks()
                tasks.append(task)
                atomic_write(self.root_dir / 'tasks.json', tasks)
                dialog.destroy()
                self.capture()
            except Exception as error:
                messagebox.showerror('등록 실패', str(error), parent=dialog)
        ttk.Button(frame, text='작업 등록', command=submit, style='Accent.TButton').pack(anchor='e')

    def close(self):
        if self.busy:
            messagebox.showinfo('작업 중', '현재 작업이 끝난 뒤 닫아주세요.', parent=self)
            return
        self.destroy()


def demo_items():
    return [
        item('terminal', '쇼핑몰 API · Codex', {'name': '쇼핑몰 API', 'cwd': 'C:\\projects\\shop-api', 'tool': 'codex', 'session': 'demo-session', 'environment': 'windows'}, '등록된 작업 · Codex 대화 세션 재개'),
        item('terminal', '대시보드 · OpenCode', {'name': '대시보드', 'cwd': '/home/me/dashboard', 'tool': 'opencode', 'session': 'demo-session-2', 'environment': 'wsl'}, '등록된 작업 · WSL / Ubuntu'),
        item('chrome', 'Chrome · 창 1 · 탭 8개', {'urls': ['https://example.com'], 'profile': 'Default'}, '가져온 탭 목록 · 기본 프로필'),
        item('excel', '2026_매출현황.xlsx', {'path': 'C:\\Work\\2026_매출현황.xlsx', 'sheet': '10월'}, 'Excel · 10월 시트'),
        item('folder', '프로젝트 자료', {'path': 'C:\\Work'}, '탐색기 · C:\\Work'),
        item('app', 'Visual Studio Code', {'path': 'C:\\Code.exe'}, '앱 실행만 지원', selected=False, warning='편집 중인 내부 상태는 앱 자체 복원에 따릅니다.')]
