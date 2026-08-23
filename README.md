# 실행 커맨드

Windows:

```powershell
.\.venv_flask\Scripts\python.exe flaskServer.py
```

## 테스트 환경

운영 의존성과 테스트 도구는 각각 `requirements.txt`,
`requirements-dev.txt`에서 관리합니다. CI와 동일하게 Linux에서는 Python 3.12
가상환경 사용을 권장합니다.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
ACTIVATION_KEY=test_key python -m pytest
```

Windows PowerShell에서는 다음 명령을 사용합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
$env:ACTIVATION_KEY = "test_key"
python -m pytest
```

Pull Request와 `main` 브랜치 push에서는 GitHub Actions가 Python 3.12로 전체
테스트를 실행합니다. 테스트에서는 실제 네이버 로그인이나 운영 서버 연결을
수행하지 않아야 하며 외부 동작은 mock으로 대체합니다.
