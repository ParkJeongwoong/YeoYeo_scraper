# 코드 구조 분석 및 수정 가이드

## 프로젝트 개요
네이버 예약 관리 시스템 자동화 스크래퍼 (Flask 기반 REST API)
- **목적**: 네이버 비즈니스 예약 관리 자동화 (예약 정보 동기화, 조회)
- **주요 기술**: Flask, Flask-RESTX, Selenium, BeautifulSoup4
- **로컬 개발 실행**: `.\.venv_flask\Scripts\python.exe flaskServer.py` (Windows)
- **Swagger UI**: 서버 실행 후 `http://localhost:5000/docs` 접속

### 실행 환경 (운영)
- **플랫폼**: AWS EC2 (Linux)
- **Chrome 실행**: Headless 모드 (디스플레이 서버 없음)
- **프로세스 관리**: `/proc/<pid>` 기반 상태 확인, `pgrep`/`pkill`, `fcntl.flock` 기반 프로필 락 사용 가능
- **시그널**: SIGTERM/SIGKILL 정상 동작
- **코드 리뷰/버그 판단 기준**: Linux 동작을 우선시하고, Windows 관련 분기 코드는 로컬 개발용으로만 간주
- **FD 모니터링**: `/proc/self/fd` 로 현재 FD 수 추적 (`FD_WARNING_THRESHOLD=800`, `FD_CRITICAL_THRESHOLD=950`)
- **동시성 제어**: `MAX_CONCURRENT_BROWSERS` 세마포어 + 프로필 락(fcntl)
- **Chrome 버전**: **146 고정** (EC2에 설치된 Chrome 도 146). `version_main=146` 하드코딩은 의도된 것이며 버그가 아님. 버전 변경 시 운영팀이 수동으로 업데이트.
- **재발 방지 규칙 (2026-04-22 장애)**:
  - `SessionNotCreatedException: cannot connect to chrome at 127.0.0.1:<port>` 는 우선 `Chrome 기동 직후 비정상 종료` 로 판단할 것. 시작 실패를 곧바로 메모리 누수로 단정하지 말 것.
  - `UC_USER_MULTI_PROCS` 는 **명시적 env opt-in일 때만 활성화**할 것. "patched binary가 이미 있으니 자동 활성화" 같은 추론 기반 기본값 변경은 금지.
  - 시작 로그에 `userMultiProcs=False` 가 찍히는 것이 기본 정상 상태다. 운영에서 `true` 가 보이면 환경변수 또는 코드 경로를 다시 확인할 것.
  - `uc.Chrome()` 가 객체를 반환하기 전에 예외를 던질 수 있으므로, 시작 실패 시에도 프로필 기준 orphan cleanup 을 반드시 수행해야 한다.
  - 프로필 락/고아 프로세스 정리 로직을 수정할 때는 "동시 실행 중인 정상 세션을 죽이지 않는지" 와 "시작 실패 후 잔여 프로세스가 남지 않는지" 를 함께 검토할 것.

### 네이버 로그인 최소화 제약 (중요)
- **전제**: 네이버는 selenium 기반 자동 로그인을 **비정상 접근**으로 판별한다. 매 요청마다 로그인을 수행하면 일정 시점부터 **captcha 강제 노출 → IP 블록** 으로 이어져 서비스가 정지된다.
- **원칙**: 로그인은 **최소 횟수**만 수행한다. 한 번 획득한 세션은 Chrome 유저 프로필에 보존하고, 이후 요청은 프로필을 재사용해 쿠키/세션으로 진입해야 한다.
- **따라서 프로필 경로(`CHROME_PROFILE_PATH`)는 운영에서 반드시 유지해야 한다.** "attempt 1 실패 시 프로필을 버리고 no-profile 로 재시도" 같은 단순 폴백은 매 요청 재로그인을 유발하므로 **절대 금지**.
- **프로필 복구 전략 (getDriver)**:
  1. attempt 1: 기존 프로필로 기동 시도. 정상이면 쿠키/세션 재사용, 로그인 스킵.
  2. attempt 1 실패 시: 프로필이 깨진 것으로 간주하고 **프로필 디렉토리 내부를 초기화** (flock 이 걸린 `.profile.lock` 은 반드시 보존). 같은 경로로 attempt 2 수행. 이때 로그인 플로우가 1회 실행되며, 성공 시 세션이 해당 프로필에 저장되어 **다음 요청부터 다시 attempt 1 경로로 로그인 없이 진입**할 수 있어야 한다.
  3. attempt 2 도 실패하면 예외로 종료. no-profile 폴백은 수행하지 않는다 (재로그인 루프 방지).
- **수정 시 검토 포인트**:
  - 프로필 초기화 시 `.profile.lock` 파일을 삭제하지 않는가? (삭제하면 flock 핸들 무효화됨)
  - 초기화 전에 `_cleanup_orphan_processes_for_profile()` 이 선행되어 프로필을 잡고 있는 Chrome/chromedriver 가 없는가?
  - 로그에 "profile wiped and retried" / "session persisted to profile" 류 이벤트가 명확히 남는가? (재로그인 빈도 추적용)

---

## 모듈별 역할 및 책임

### 1. **flaskServer.py** - API 서버 엔트리포인트
**역할**:
- Flask-RESTX 웹 서버 실행 및 라우팅
- API 엔드포인트 관리 (Resource 클래스 기반)
- Swagger UI 자동 생성 (/docs)
- 인증키(activationKey) 검증
- Request/Response 모델 정의 및 검증
- 로깅 설정

**주요 엔드포인트**:
- `GET /` - 헬스체크
- `POST /` - 테스트용 엔드포인트
- `POST /sync/in` - 네이버 예약 상태 변경 (특정 날짜/방 예약 가능 → 불가능 토글)
- `POST /sync/out` - 네이버 예약 정보 조회 (N개월치 예약 내역 가져오기)

**Flask-RESTX 구조**:
- **Resource 클래스 기반**: 각 엔드포인트는 Resource 클래스로 구현
- **모델 정의**: `api.model()`로 Request/Response 스키마 정의
- **자동 검증**: `@ns.expect(model, validate=True)`로 입력 자동 검증
- **Swagger UI**: 자동으로 API 문서 생성 및 테스트 가능

**모델 정의 방법**:
- Request 모델: 필수/선택 필드, 타입, 설명, 기본값 명시
- Response 모델: 각 HTTP 상태코드별 응답 구조 정의
- Nested 모델: 복잡한 객체는 별도 모델로 정의 후 `fields.Nested()` 사용
- 필드 타입: `fields.String`, `fields.Integer`, `fields.List`, `fields.Raw` 등

**수정 시 주의사항**:
- 새로운 API 엔드포인트 추가 시 Resource 클래스로 구현
- Request/Response 모델을 먼저 정의 후 `@ns.expect()`, `@ns.response()` 데코레이터 사용
- 모든 요청에 `activationKey` 검증 필요한 경우 `checkActivationKey()` 호출
- ChromeDriver 인스턴스는 반드시 `driver.close()`로 종료
- 에러 핸들링 시 적절한 HTTP 상태 코드 반환 (200, 401, 500 등)
- `validate=True` 옵션으로 Request 자동 검증 활성화
- Swagger UI에서 API 문서 자동 생성되므로 모델 정의가 중요

**수정 방법**:
```python
# 1. Request/Response 모델 정의
new_request_model = api.model('NewRequest', {
    'activationKey': fields.String(required=True, description='인증 키'),
    'param': fields.String(required=True, description='파라미터')
})

new_success_response_model = api.model('NewSuccessResponse', {
    'message': fields.String(description='응답 메시지'),
    'data': fields.Raw(description='결과 데이터')
})

new_error_response_model = api.model('NewErrorResponse', {
    'message': fields.String(description='에러 메시지')
})

# 2. Resource 클래스로 엔드포인트 구현
@ns.route('/new-endpoint')
class NewEndpoint(Resource):
    @ns.expect(new_request_model, validate=True)
    @ns.response(200, 'Success', new_success_response_model)
    @ns.response(401, 'Unauthorized', new_error_response_model)
    @ns.response(500, 'Internal Server Error', new_error_response_model)
    def post(self):
        """새로운 엔드포인트 설명"""
        driver = chromeDriver.ChromeDriver()
        try:
            req = request.get_json()
            if not checkActivationKey(req):
                return {"message": "Invalid Access Key"}, 401
            
            # 비즈니스 로직 구현
            result = your_function(driver, req["param"])
            
            return {"message": "Success", "data": result}, 200
        except Exception as e:
            log.error("에러 메시지", e)
            return {"message": "Failed"}, 500
        finally:
            driver.close()
```

---

### 2. **driver.py** - 웹드라이버 추상 인터페이스
**역할**:
- Selenium WebDriver의 추상 베이스 클래스
- 브라우저 드라이버 구현체의 공통 인터페이스 정의
- 코드 재사용성 및 확장성 제공

**주요 메서드**:
- `getOptions()` - 브라우저 옵션 설정
- `getDriver()` - 드라이버 인스턴스 생성
- `close()` - 브라우저 종료
- `goTo(url)` - 페이지 이동
- `findBySelector/ID/Xpath()` - 엘리먼트 탐색
- `login(id, pw)` - 네이버 로그인 자동화
- `copyPaste(text)` - 클립보드 복붙
- `executeScript()` - JavaScript 실행

**수정 시 주의사항**:
- 새로운 메서드 추가 시 `@abstractmethod` 데코레이터 필수
- 모든 구현체(ChromeDriver, FirefoxDriver)에서 동일하게 구현 필요
- 인터페이스 변경 시 모든 구현체 동시 수정

---

### 3. **chromeDriver.py** - Chrome 웹드라이버 구현체
**역할**:
- Chrome 브라우저 자동화
- 봇 감지 회피 설정 (selenium-stealth 적용)
- Headless 모드 실행

**주요 특징**:
- `--headless=new` 옵션으로 백그라운드 실행
- User-Agent 위장
- `navigator.webdriver` 속성 제거
- WebGL 정보 조작으로 봇 감지 우회

**수정 시 주의사항**:
- 봇 감지가 강화되면 `getDriver()` 메서드의 JavaScript 조작 코드 수정
- Headless 모드 해제 시 `--headless=new` 옵션 제거
- 브라우저 버전 업데이트 시 ChromeDriver 버전 확인
- `user_multi_procs` 는 기본값으로 자동 활성화하지 말 것. 필요 시 `UC_USER_MULTI_PROCS=true` 를 운영에서 명시한 경우에만 켤 것
- 시작 직후 `cannot connect to chrome at 127.0.0.1:<port>` 가 발생하면 `메모리 누수` 보다 `기동 실패 + 잔여 프로세스/프로필 상태` 를 먼저 의심할 것
- 시작 실패 후 재시도 전에 `_cleanup_partial_browser()` 만으로 충분하다고 가정하지 말 것. `uc.Chrome()` 반환 전 예외 경로에서도 orphan cleanup 이 필요하다
- 안정성 수정 시에는 반드시 로그로 `userMultiProcs`, 프로필 락 획득/해제, orphan cleanup 수행 여부를 확인할 것

**수정 방법**:
```python
# Headless 모드 해제 (디버깅용)
def getOptions(self) -> Options:
    options = Options()
    # options.add_argument("--headless=new")  # 주석 처리
    # ... 나머지 옵션
    return options

# 새로운 봇 감지 우회 스크립트 추가
def getDriver(self, options):
    driver = webdriver.Chrome(options=options)
    driver.execute_script("/* 새로운 우회 코드 */")
    return driver
```

---

### 4. **firefoxDriver.py** - Firefox 웹드라이버 구현체
**역할**:
- Firefox 브라우저 자동화 (Chrome 대체용)
- ChromeDriver와 동일한 인터페이스 제공

**주요 차이점**:
- `Options` 설정 방식이 Chrome과 다름 (`set_preference` 사용)
- selenium-stealth 미사용
- WebDriverWait 없이 로그인 (chromeDriver와 차이)

**수정 시 주의사항**:
- Chrome과 동일한 동작 보장 필요
- Firefox 특화 설정은 `set_preference()` 사용
- 현재 프로젝트는 주로 ChromeDriver 사용 중

---

### 5. **syncManager.py** - 예약 동기화 로직 핵심
**역할**:
- 네이버 예약 관리 비즈니스 로직 담당
- 로그인 → 페이지 이동 → 예약 상태 변경/조회

**주요 함수**:

#### `SyncNaver(driver, targetDateStr, targetRoom)` - 예약 상태 변경
- **파라미터**:
  - `targetDateStr`: 변경할 날짜 문자열 (예: `"2024-09-02,2024-09-03"`)
  - `targetRoom`: 방 타입 (`"Yeoyu"` 또는 `"Yeohang"`)
- **동작 흐름**:
  1. 네이버 로그인
  2. 간단예약관리 페이지 이동
  3. 날짜별로 순회하며 예약 상태 토글
- **반환값**: 성공한 날짜 리스트

#### `getNaverReservation(driver, monthSize)` - 예약 정보 조회
- **파라미터**:
  - `monthSize`: 조회할 월 개수 (1~N)
- **동작 흐름**:
  1. 네이버 로그인
  2. 예약자관리 페이지 이동
  3. N개월치 예약 정보 크롤링
  4. 중복 제거 및 필터링 (오늘 이후 예약만)
- **반환값**: `(취소 미포함 예약 리스트, 전체 예약 리스트)`

**수정 시 주의사항**:
- 네이버 URL 변경 시 상단 상수 수정 (`naverBizUrl`, `simpleReservationManagementUrl` 등)
- 로그인 실패 시 `randomSleep()`, `randomRealSleep()` 시간 조정
- 날짜 파싱 로직은 `makeTargetDateList()`, `makeTargetDate()` 함수에서 처리
- `.env` 파일에 `ID`, `PASSWORD` 환경변수 필수

**수정 방법**:
```python
# 새로운 방 타입 추가
class RoomType(Enum):
    Yeoyu = 0
    Yeohang = 1
    NewRoom = 2  # 추가

# URL 변경
naverBizUrl = "https://new-url.naver.com/..."

# 대기 시간 조정
def randomSleep(driver):
    sleepTime = randint(20, 40) / 10  # 기존 15~30 → 20~40
```

---

### 6. **simpleManagementController.py** - 간단예약관리 페이지 컨트롤러
**역할**:
- 네이버 간단예약관리 페이지의 DOM 조작
- 특정 날짜/방의 예약 버튼 찾기

**주요 메서드**:

#### `findTargetPage(driver, targetDate)` - 타겟 날짜 페이지 찾기
- 현재 표시된 날짜 범위에서 타겟 날짜 찾기
- 없으면 "다음" 버튼 클릭하며 최대 30회 검색
- **반환값**: 날짜의 인덱스 (0부터 시작), 없으면 -1

#### `findTargetPeriod(targetDate, html, driver)` - 날짜 범위 파싱
- HTML에서 날짜 정보 추출 (정규표현식 사용)
- 시작일~종료일 범위 계산
- **반환값**: targetDate의 상대 인덱스

#### `findTargetBtn(driver, idxOfDate, targetRoomValue)` - 예약 버튼 찾기
- 예약 테이블에서 특정 날짜/방의 버튼 엘리먼트 반환
- **반환값**: WebElement (클릭 가능한 버튼)

**수정 시 주의사항**:
- 네이버 페이지 HTML 구조 변경 시 CSS 선택자 수정 필요
  - `DatePeriodCalendar__date-info` (날짜 정보)
  - `DatePeriodCalendar__next` (다음 버튼)
  - `SimpleManagement__management-tbody` (예약 테이블)
- 정규표현식 `>(.*?)<` 패턴이 깨지면 파싱 로직 수정

**수정 방법**:
```python
# CSS 선택자 변경 시
def findTargetPeriod(self, targetDate, html, driver):
    soup = bs(html, "html.parser")
    dateInfo = soup.select('NEW_SELECTOR')  # 여기 수정
    # ...

# 검색 시도 횟수 변경
def findTargetPage(self, driver, targetDate):
    searchLimit = 50  # 기존 30 → 50
```

---

### 7. **bookingListExtractor.py** - 예약 정보 파싱
**역할**:
- 예약자관리 페이지 HTML을 파싱하여 예약 정보 추출
- BeautifulSoup4 사용

**주요 함수**:

#### `extractBookingList(html)` - 예약 목록 추출
- HTML에서 모든 예약 카드 파싱
- **반환값**: 예약 정보 딕셔너리 리스트

#### `extractBookingInfo(booking)` - 개별 예약 정보 추출
- **추출 항목**:
  - `name`: 예약자명
  - `phone`: 전화번호
  - `reservationNumber`: 예약번호
  - `startDate`, `endDate`: 체크인/아웃 날짜 (YYYYMMDD 형식)
  - `room`: 객실명
  - `option`: 예약 옵션
  - `comment`: 요청사항
  - `price`: 총 가격
  - `status`: 예약 상태 (예: "예약확정", "취소")

#### `parseDateInfo(dateStr)` - 날짜 형식 변환
- 입력: `"24. 8. 19.(월)"`
- 출력: `"20240819"`

**수정 시 주의사항**:
- 네이버 HTML 구조 변경 시 CSS 클래스명 수정
  - `BookingListView__contents-user`
  - `BookingListView__name`
  - `BookingListView__phone` 등
- 날짜 형식 변경 시 `parseDateInfo()` 로직 수정
- 새로운 정보 추출 시 `extractBookingInfo()`에 필드 추가

**수정 방법**:
```python
# 새로운 정보 추가
def extractBookingInfo(booking):
    # ... 기존 코드
    paymentMethod = booking.select_one('NEW_SELECTOR')
    bookingInfo["paymentMethod"] = paymentMethod.get_text(strip=True) if paymentMethod else None
    return bookingInfo

# CSS 선택자 업데이트
def extractBookingList(html):
    soup = bs(html, "html.parser")
    bookingList = soup.select('UPDATED_SELECTOR')  # 변경됨
```

---

### 8. **log.py** - 로깅 유틸리티
**역할**:
- 파일 및 콘솔 로깅 설정
- 간편한 로깅 함수 제공

**주요 함수**:
- `getLogger(path)` - 로거 생성 (파일 + 콘솔 핸들러)
- `info(*messages)` - INFO 레벨 로그
- `error(message, e)` - ERROR 레벨 로그 + 예외 스택트레이스

**수정 시 주의사항**:
- 로그 포맷 변경 시 `formatter` 패턴 수정
- 로그 레벨 조정 시 `logger.setLevel()` 호출
- 새로운 로그 레벨 추가 시 함수 추가 (예: `debug()`, `warning()`)

---

## 환경 설정 파일

### **.env** (환경변수)
```
ID=네이버_아이디
PASSWORD=네이버_비밀번호
ACTIVATION_KEY=API_인증키
```

### **requirements.txt** (주요 의존성)
- `flask==3.0.3` - 웹 서버
- `selenium==4.23.1` - 브라우저 자동화
- `selenium-stealth==1.0.6` - 봇 감지 우회
- `beautifulsoup4==4.12.3` - HTML 파싱
- `python-dotenv==1.0.1` - 환경변수 로드

---

## 일반적인 수정 시나리오

### 1. 네이버 페이지 구조 변경 대응
**증상**: 예약 정보를 가져오지 못함, 버튼 클릭 실패

**수정 파일**:
- `bookingListExtractor.py` - CSS 선택자 업데이트
- `simpleManagementController.py` - XPath/선택자 업데이트

**확인 방법**:
1. Headless 모드 해제 (`chromeDriver.py`)
2. 브라우저에서 직접 엘리먼트 검사
3. 새로운 클래스명/ID 확인
4. 선택자 수정 후 테스트

### 2. 새로운 방 타입 추가
**수정 파일**:
- `syncManager.py` - `RoomType` Enum에 추가
- `simpleManagementController.py` - 방 인덱스 확인 (필요 시)

**예시**:
```python
class RoomType(Enum):
    Yeoyu = 0
    Yeohang = 1
    NewRoom = 2  # 추가
```

### 3. 새로운 API 엔드포인트 추가
**수정 파일**: `flaskServer.py`

**템플릿**:
```python
@app.route("/new-api", methods=["POST"])
def new_api():
    driver = chromeDriver.ChromeDriver()
    try:
        req = request.get_json()
        if not checkActivationKey(req):
            return jsonify({"message": "Invalid Access Key"}), 401
        
        result = your_logic(driver, req)
        return jsonify({"message": "Success", "data": result}), 200
    except Exception as e:
        log.error("에러 발생", e)
        return jsonify({"message": "Failed"}), 500
    finally:
        driver.close()
```

### 4. 로그인 실패 대응
**증상**: "로그인 성공" 로그 후 예외 발생

**수정 파일**:
- `syncManager.py` - `randomSleep()` 시간 증가
- `chromeDriver.py` - 봇 감지 우회 스크립트 추가

**체크리스트**:
- [ ] 네이버 계정 정상 여부
- [ ] 2단계 인증 설정 확인
- [ ] User-Agent 차단 여부
- [ ] IP 차단 여부

### 5. 성능 최적화
**방법**:
- `syncManager.py`의 대기 시간 최소화
- 불필요한 `randomRealSleep()` 제거
- Selenium 대신 requests + BeautifulSoup 사용 고려 (로그인 불필요 시)

---

## 디버깅 팁

### 1. Headless 모드 해제
`chromeDriver.py:26-28` 주석 처리:
```python
# options.add_argument("--headless=new")
```

### 2. 로그 레벨 상향
`flaskServer.py:20`:
```python
logger.setLevel(logging.DEBUG)
```

### 3. 브라우저 스크린샷 저장
```python
driver.driver.save_screenshot("debug.png")
```

### 4. HTML 소스 덤프
```python
with open("debug.html", "w", encoding="utf-8") as f:
    f.write(driver.getPageSource())
```

---

## 주의사항 및 제약사항

1. **네이버 로그인 제한**
   - 짧은 시간에 여러 번 로그인 시도 시 일시적 차단 가능
   - `randomSleep()`, `randomRealSleep()` 시간 충분히 확보

2. **Selenium WebDriver 버전**
   - Chrome/Firefox 브라우저 버전과 호환되는 WebDriver 필요
   - 자동 다운로드되지만, 실패 시 수동 설치

3. **환경변수 보안**
   - `.env` 파일은 절대 Git에 커밋하지 말 것
   - `.gitignore`에 포함 확인

4. **동시 실행 제한**
   - 현재 구조는 동시 요청 처리 미지원
   - 여러 요청이 동시에 들어오면 ChromeDriver 충돌 가능
   - 해결: Queue 또는 Celery 같은 작업 큐 도입
   - 단, `user_multi_procs` 자동 활성화로 이 문제를 우회하려고 하지 말 것. 이 프로젝트에서는 명시적 운영 설정 없이 자동 활성화하면 오히려 기동 실패/잔여 프로세스 문제를 악화시킨 이력이 있음

5. **예약 정보 정확성**
   - 네이버 페이지 로딩 시간에 따라 데이터 누락 가능
   - `wait()` 시간 충분히 확보

---

## 파일 구조 요약
```
be_scraper/
├── flaskServer.py              # API 서버 (엔트리포인트)
├── driver.py                   # 웹드라이버 인터페이스
├── chromeDriver.py             # Chrome 드라이버 구현체 ⭐
├── firefoxDriver.py            # Firefox 드라이버 구현체
├── syncManager.py              # 예약 동기화 핵심 로직 ⭐
├── simpleManagementController.py  # 간단예약관리 페이지 컨트롤 ⭐
├── bookingListExtractor.py     # 예약 정보 파싱 ⭐
├── log.py                      # 로깅 유틸리티
├── .env                        # 환경변수 (민감 정보)
├── requirements.txt            # Python 의존성
└── logs/                       # 로그 파일 디렉토리
    └── server.log

⭐ = 네이버 페이지 변경 시 주로 수정되는 파일
```

---

## 빠른 참조 (Quick Reference)

| 작업 | 수정 파일 | 핵심 함수/클래스 |
|------|----------|----------------|
| API 엔드포인트 추가 | `flaskServer.py` | `@app.route()` |
| 예약 상태 변경 로직 수정 | `syncManager.py` | `SyncNaver()` |
| 예약 조회 로직 수정 | `syncManager.py` | `getNaverReservation()` |
| HTML 파싱 오류 수정 | `bookingListExtractor.py` | `extractBookingInfo()` |
| 버튼 클릭 오류 수정 | `simpleManagementController.py` | `findTargetBtn()` |
| 로그인 문제 해결 | `chromeDriver.py` | `getDriver()`, `login()` |
| 방 타입 추가 | `syncManager.py` | `RoomType` Enum |
| 대기 시간 조정 | `syncManager.py` | `randomSleep()`, `randomRealSleep()` |

---

**최종 업데이트**: 2026-02-24
**작성자**: AI 코드 분석 에이전트
