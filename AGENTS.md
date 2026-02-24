# 코드 구조 분석 및 수정 가이드

## 프로젝트 개요
네이버 예약 관리 시스템 자동화 스크래퍼 (Flask 기반 REST API)
- **목적**: 네이버 비즈니스 예약 관리 자동화 (예약 정보 동기화, 조회)
- **주요 기술**: Flask, Flask-RESTX, Selenium, BeautifulSoup4
- **실행 방법**: `.\.venv_flask\Scripts\python.exe flaskServer.py`
- **Swagger UI**: 서버 실행 후 `http://localhost:5000/docs` 접속

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
