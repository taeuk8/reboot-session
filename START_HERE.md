# Reboot Session v0.1

Windows용 실행 가능한 첫 프로토타입입니다. 자동 주기 저장 없이 사용자가 준비 → 목록 검토 → 저장하고 다시 시작을 진행합니다.

## Windows에서 실행

1. Python 3.11 이상을 설치합니다. 설치 시 **tcl/tk and IDLE**과 Python Launcher를 포함해주세요.
2. 이 폴더를 로컬 디스크에 압축 해제합니다. 앱을 계속 같은 위치에 두세요.
3. `run-windows.bat`을 더블클릭합니다. 관리자 권한은 필요하지 않습니다.
4. **재시작 준비**를 누르고 항목별 복원 범위를 확인합니다.
5. 처음에는 **저장만 → 저장한 상태 복원**으로 시험하세요. 기존 창과 중복될 수 있습니다.
6. 확인 후 **저장하고 다시 시작**을 사용합니다. Windows 로그인 후 복원이 시작됩니다.

Python 없이 실행할 EXE가 필요하면 Windows에서 `build-windows.bat`을 실행하세요. 빌드 의존성을 다운로드하고 테스트를 거쳐 `dist/RebootSession.exe`를 만듭니다. 현재 배포물에는 Windows에서 빌드한 EXE가 포함되어 있지 않습니다.

## 현재 지원 범위

| 기능 | v0.1 동작 |
| --- | --- |
| 상태 검토·선택 | 수집 결과와 경고 표시, 선택한 항목만 저장 |
| 저장 검증 | 임시 파일에 기록·재읽기 검증 후 교체 |
| 재시작 | 로그인 후 실행 등록이 성공한 경우에만 정상 재시작 요청. 강제 종료 안 함 |
| 로그인 후 복원 | 같은 사용자의 예약을 한 번 소비. 24시간 지난 예약은 자동 복원 보류 |
| WezTerm | 로컬 Windows 작업 경로 자동 수집. **각 패널을 별도 새 창으로 복원** |
| Codex / OpenCode | 사용자가 등록한 프로젝트·정확한 세션 ID로 대화 재개 명령 실행 |
| WSL | 사용자가 작업에 등록한 배포판·Linux 경로·AI 세션으로 실행 |
| 개발 명령 | 직접 등록한 명령만 실행. 이전 명령 기록은 자동 재실행하지 않음 |
| Excel | 실행 중인 인스턴스에서 저장된 통합 문서 경로·활성 시트 수집, COM으로 다시 열기 |
| 탐색기 | 일반 파일 시스템 폴더 수집·다시 열기 |
| Chrome | 기본 프로필의 Chrome 자체 이전 세션 복원. 아래 확장으로 정확한 URL 목록 가져오기 가능 |
| 기타 앱 | 창이 있는 프로그램 목록 제공. 기본 선택 해제. 실행 파일만 다시 실행 |
| 복원 결과 | 항목별 실행 요청·실패 기록, 실패 항목 명시적 재시도 |

**아직 지원하지 않음:** WezTerm 분할 구조·탭 배치 재현, 창 위치·모니터 배치, AI 세션 ID 자동 식별, SSH 원격 작업, 모든 Excel 인스턴스 수집, Excel 선택 셀, Chrome 스크롤·폼·활성 탭·고정 탭 재현, 저장하지 않은 내용·프로세스 메모리 복원. 브라우저·다른 앱의 자체 자동 시작과 동시에 복원하면 중복 창이 생길 수 있습니다.

실행 요청 성공은 앱 내부 작업의 복원 성공을 보장하지 않습니다. 터미널 명령 오류나 재로그인 요구는 실제 열린 화면에서 확인해야 합니다.

## 개발 작업 등록

**＋ 개발 작업**에서 이름, 프로젝트 경로, 환경, 도구와 세션 ID를 입력합니다.

- Windows: `C:\projects\my-app` 같은 경로
- WSL: `/home/me/my-app` 같은 경로와 필요한 경우 `Ubuntu` 같은 배포판 이름
- Codex: 해당 대화의 세션 ID를 입력. 복원 시 `codex resume <ID>` 실행
- OpenCode: `opencode session list`로 확인한 ID를 입력. 복원 시 `opencode --session <ID>` 실행
- shell: 해당 경로에서 셸만 열기
- command: 복원용 명령을 직접 입력. Windows는 PowerShell, WSL은 `bash -lc`에서 실행

WezTerm, Codex, OpenCode는 해당 환경의 PATH에서 실행 가능해야 합니다. 등록한 Windows 경로는 같은 경로의 자동 수집 패널을 대체합니다. 여러 패널의 같은 프로젝트 대화를 복원하려면 각 세션을 별도 작업으로 등록하세요.

등록 작업은 앱 데이터 폴더의 `tasks.json`에 있습니다. 작업을 수정·삭제하려면 앱을 닫고 이 파일을 편집할 수 있습니다. 비밀번호나 API 키를 명령에 넣지 마세요.

## Chrome 탭을 정확히 저장하려면

1. Chrome에서 `chrome://extensions`를 열고 개발자 모드를 켭니다.
2. **압축해제된 확장 프로그램을 로드합니다**에서 이 프로젝트의 `chrome_extension` 폴더를 고릅니다.
3. 확장 버튼을 누릅니다. `chrome://version`의 프로필 경로 마지막 폴더 이름(`Default`, `Profile 1` 등)을 입력합니다.
4. **현재 창·탭 내보내기**로 JSON을 저장합니다.
5. 앱에서 **Chrome JSON 가져오기**를 누릅니다. 해당 목록이 Chrome 자체 복원 항목을 대체합니다.
6. 여러 프로필은 각 프로필에서 내보내고 차례로 가져옵니다. 그 후 앱 목록에서 선택합니다.

탭 변경 후에는 다시 내보내야 합니다. 현재 확장은 재시작 준비 버튼과 자동 연결되지 않습니다. JSON에는 방문 URL이 들어 있으므로 개인 데이터로 취급하세요. 시크릿 창과 로그인 인증 정보는 내보내지 않습니다.

## 재시작을 취소했다면

Windows의 문서 저장 확인 등으로 재시작을 취소했다면 앱에서 **재시작 예약 해제**를 누르세요. 저장한 계획은 유지됩니다. 다음 로그인 때 같은 계획이 반복 실행되지 않도록 복원 직전에 예약을 제거합니다.

오류 복구가 필요하면 다음 항목을 확인할 수 있습니다.

- 데이터: `%LOCALAPPDATA%\RebootSession`
- 로그인 실행 파일: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RebootSession.cmd`
- `plans`: 저장한 계획
- `result-*.json`: 항목별 실행 결과
- `pending.json`: 로그인 후 복원 예약

복원 도중 중단된 항목은 자동 재실행하지 않습니다. **실패 항목 재시도**로 명시적으로 실행할 수 있으며, 이미 열린 창이 있다면 중복될 수 있습니다.

## 개발·검증

```sh
python3 -m unittest discover -s tests -v
python3 app.py --demo
```

`--demo`는 샘플 데이터만 표시하고 프로그램 실행·재시작을 하지 않습니다. 실제 앱은 표준 라이브러리만 사용합니다. EXE 패키징할 때만 PyInstaller가 필요합니다.

현재 Mac에서 저장·재시도·명령 생성·시작 등록 로직의 모의 테스트와 Tk 화면 초기화를 확인했습니다. Windows의 실제 COM·WezTerm·Chrome 복원, EXE 빌드와 재시작 후 복원은 Windows 실기 검증이 남아 있습니다.

참고한 공식 문서:

- [WezTerm CLI list](https://wezterm.org/cli/cli/list.html)
- [WezTerm 프로그램 실행](https://wezterm.org/config/launch.html)
- [Codex CLI 명령](https://developers.openai.com/codex/cli/reference/)
- [OpenCode CLI](https://opencode.ai/docs/cli/)
