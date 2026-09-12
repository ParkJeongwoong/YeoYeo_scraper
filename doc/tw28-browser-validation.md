# TW-28 검증 기록

## 2026-09-07 로컬 검증

Chrome for Testing / ChromeDriver 146.0.7680.165, Selenium 4.23.1로
임시 프로필과 로컬 HTML만 사용했다. 운영 계정과 예약 데이터는 사용하지 않았다.

실측한 기존 문제: `Network.setUserAgentOverride`에 UA metadata 없이
언어를 전달하면 `navigator.userAgentData.brands`가 빈 배열이 되고
`platform`이 빈 문자열이 됐다. 해당 호출을 제거한 후 Chromium 146
브랜드와 Linux 플랫폼이 유지되는 것을 확인했다.

Headless Chrome의 기본 User-Agent에는 `HeadlessChrome/146.0.0.0` 토큰이
포함됐다. 실제 브라우저에서 읽은 UA-CH high entropy metadata를 CDP override에
그대로 전달하고 UA 토큰만 같은 버전의 `Chrome/146.0.0.0`으로 정규화했다.
수정 후 JavaScript의 `navigator.userAgent`와 루프백 HTTP 서버가 받은
User-Agent 모두 `HeadlessChrome`을 포함하지 않았다. UA-CH의 Chromium 146,
Linux, mobile=false 값은 수정 전후 동일했다. HomeServer가 Google Chrome
빌드를 사용하면 해당 빌드가 제공하는 브랜드 목록을 그대로 사용한다.

언어는 `intl.accept_languages` Chrome 프로필 설정으로 지정하고 Intl 로케일만
CDP로 설정한다. 운영 프로필 전체 초기화나 세션 폐기는 추가하지 않는다.
시간대는 호스트의 실제 시간대를 유지한다. 한국어 사용자라는 이유만으로
시간대를 바꾸지 않는다. HomeServer에서 실제 시간대를 별도로 확인해야 한다.

실제 Chrome에서 검증한 동작:

- 기존 값이 있는 로그인 필드에 키 입력으로 새 값을 넣으면 DOM 값과
  input 이벤트 리스너의 값이 함께 갱신된다.
- 키 입력 및 input 이벤트의 `isTrusted`가 true다.
- 숨겨진 체크박스도 연결된 label의 표준 클릭으로 토글된다.
- 달력 역할의 버튼에 표준 클릭 이벤트가 전달된다.

추가로 실제 ChromeDriver 클래스의 프로필 락/기동/종료 경로와
undetected-chromedriver 3.5.5를 사용하여 임시 프로필을 두 번 열었다.
두 실행 모두 한국어 언어/Intl 로케일, UA-CH Chromium 146/Linux가 유지됐고
첫 실행에서 기록한 테스트 localStorage가 두 번째 실행에서도 보존됐다.
Chrome 146은 해당 환경에서 navigator.languages를 [ko-KR]로 노출했다.

루프백 HTTP 서버에서도 Accept-Language가 ko-KR로 시작하고 UA-CH 헤더에
Chromium/Linux가 유지됨을 확인했다. 지속 쿠키는 기존 uc.quit()의 SIGTERM
종료 후 소실되는 실패가 재현됐다. Browser.close로 Chrome 정상 종료를 먼저
요청하고 최대 5초 대기한 후 기존 cleanup을 수행하도록 수정한 결과, 동일
테스트 쿠키가 두 번째 실행에도 보존됐다. 프로필 락은 cleanup 완료까지 유지한다.

기존 창은 1920x1080이지만 가상 화면은 800x600이었다. Chrome의 공식
`--screen-info={1920x1080}` 옵션으로 가상 화면을 창과 일치시킨다.
근거: [Chromium screen-info 문서](https://chromium.googlesource.com/chromium/src/+/HEAD/components/headless/screen_info/).

이 검증은 일반 GUI Chrome과의 비교 및 실제 네이버 DOM 회귀 검증을
대신하지 않는다. 해당 검증과 HomeServer 실행 설정 확인은 아직 남아 있다.

## 실행

`browser_diagnostics.html`은 외부 요청이나 쿠키/저장소 조회 없이 지문을 표시한다.
일반 Chrome과 테스트용 Scraper Chrome에서 각각 열어 비교한다.

```bash
TW28_CHROME=/path/to/chrome TW28_DRIVER=/path/to/chromedriver \
  python -m pytest -q -s test_browser_runtime.py
```

실행 파일을 지정하지 않으면 실제 브라우저 테스트는 skip한다.
GUI 비교는 DISPLAY가 지정된 환경에서 같은 테스트가 추가 실행된다.
2026-09-08 로컬 Xvfb 실행은 시스템 /usr/bin/xkbcomp 부재로 실패했다.
시스템 패키지 설치는 수행하지 않았다. 따라서 GUI 비교 결과는 아직 없다.
지원 버전은 Chrome 146 / undetected-chromedriver 3.5.5 / Selenium 4.23.1이다.

## HomeServer Chrome 경로

HomeServer에서 발견한 영구 설치본은 Google Chrome 146.0.7680.164이며,
설치 루트는 `/home/dvlprjw/.local/google-chrome-146`이다. 시스템에는 libgbm이
설치돼 있지 않아 설치본에 포함된 사용자 로컬 라이브러리가 필요하다.

`/home/dvlprjw/.local/bin/yeoyeo-google-chrome` 래퍼가 해당 라이브러리 경로를
설정한 뒤 설치본을 실행한다. `.env`의 `CHROME_BINARY_PATH`를 이 래퍼로
지정했다. ChromeDriver는 설정 경로가 실행 가능한지 시작 전에 검사하고,
명시된 경로가 없을 때만 PATH의 표준 Chrome/Chromium 이름을 탐색한다.

이 영구 경로로 Chrome 146 실제 테스트 2개를 다시 실행해 UA/UA-CH,
한국어 요청 헤더, 가상 화면, 표준 입력, CAPTCHA 판별 및 두 실행 간 쿠키와
localStorage 보존을 확인했다.

## 인증 관측

`NAVER_AUTH` 로그의 `status`는 LOGIN_ATTEMPT, LOGIN_SUBMITTED,
SESSION_REUSED, SESSION_RECOVERED, CAPTCHA, ACCESS_BLOCKED,
ADDITIONAL_AUTH, SESSION_UNCONFIRMED, SESSION_RECOVERY_FAILED를 사용한다.
상태와 세션 식별자만 기록한다.
보호조치 탐지는 표시 중인 CAPTCHA 요소와 제한된 인증 안내 문구를 사용하므로
새로운 네이버 화면을 모두 검출한다고 가정하지 않는다.

HomeServer cron, 지속 Chrome 프로필 및 worker의 인증 실패 이후 중단 정책은
계속 유지해야 한다. 운영 배포는 별도 승인 대상이다.

## 2026-09-10 HomeServer headed 검증

Ubuntu 패키지의 Xvfb를 로컬 루프백 디스플레이 `127.0.0.1:99`에
1920x1080, 96 DPI, 24-bit로 구성했다. Chrome 운영 기본값에서 headless를
제거했으며, 디스플레이가 없을 때 자동으로 headless로 강등하지 않는다.
Xvfb는 권한 `600`의 전용 Xauthority 파일을 요구하며 인증 파일 없는 접속이
거부되는 것을 확인했다.
cron wrapper는 Chrome 프로세스에 `TZ=Asia/Seoul`을 전달한다. worker의 구조화
이벤트 로그는 코드에서 UTC를 명시하므로 기존 timestamp 형식은 유지된다.

네이버에 접속하지 않고 로컬 진단 페이지만 사용해 다음을 확인했다.

- Chrome 런타임 메타데이터의 `headless=false`
- User-Agent에 `HeadlessChrome`이 없고 Google Chrome 146으로 표시됨
- `screen`이 1920x1080, color depth 24로 표시됨
- undetected-chromedriver 경로에서 `navigator.webdriver=false`
- 같은 임시 프로필을 두 번 열었을 때 쿠키와 localStorage가 유지됨
- 전체 단위 테스트 176개 통과 및 실제 브라우저 테스트 3개 통과

물리 GPU가 없는 Xvfb의 headed Chrome에서는 진단 페이지의 WebGL context가
`null`이었다. headless 제거가 물리 데스크톱과 동일한 렌더링 지문을 보장하지
않으므로 이 차이는 잔여 위험으로 기록한다.
