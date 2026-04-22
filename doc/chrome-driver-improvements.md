# Chrome 드라이버 개선 아이템

> **전제 환경**: AWS EC2 (Linux) / Chrome 146 고정 / `MAX_CONCURRENT_BROWSERS=3` / 공유 `CHROME_PROFILE_PATH`
> **작성일**: 2026-04-22
> **분석 대상**: `chromeDriver.py`, `syncManager.py`, `simpleManagementController.py`, `bookingListExtractor.py`, `log.py`, `run.sh`

---

## 🔴 Critical — 현재 "심각한 Chrome 드라이버 문제"의 유력한 원인

### [CD-001] 프로필 락 획득 실패 시 정상 동작 중인 형제 Chrome 을 orphan 으로 오판해 종료
- **파일**: `chromeDriver.py:809-846` (`_try_acquire_profile_lock_with_orphan_cleanup`), `chromeDriver.py:367-419` (`_find_processes_using_profile`)
- **문제**: 
  - 요청 A가 프로필 락을 쥐고 10~30초간 Chrome 을 사용 중일 때, 요청 B는 **5초(`short_timeout`)** 만 기다리다 실패 → "orphan 이 락을 잡고 있다"고 오판.
  - `_cleanup_orphan_processes_for_profile` 가 `--user-data-dir=$profile` 로 매칭되는 **모든 Chrome 을 orphan 으로 간주하고 SIGTERM/SIGKILL** → A 의 세션이 `InvalidSessionIdException` 으로 중단.
- **영향도**: ⭐⭐⭐⭐⭐ — 동시 요청 발생 시 매번 재현되는 장애.
- **수정 방향**:
  - 락 파일에 기록된 `pid=` 값을 읽어 `_is_pid_alive` 로 검증.
  - 살아있는 프로세스가 락을 쥐고 있으면 orphan cleanup 을 건너뛰고 남은 timeout 만큼 재대기.
  - 보유 pid 가 죽었거나 읽을 수 없을 때만 cleanup 실행.
- **상태**: ✅ **적용 완료 (2026-04-22)**

### [CD-002] `_acquire_profile_lock` 이 락 파일을 `open("w")` 로 열어 보유자 메타데이터를 파괴
- **파일**: `chromeDriver.py:232`
- **문제**:
  - 락 획득 **시도** 단계에서 파일이 truncate 되어 기존 보유자의 `pid=`, `time=` 기록이 사라짐.
  - CD-001 수정(보유 pid 검증)의 전제 조건이 깨짐.
- **영향도**: ⭐⭐⭐⭐ — CD-001 수정과 함께 반드시 해결되어야 함.
- **수정 방향**: `os.open(..., O_CREAT|O_RDWR)` + `os.fdopen("r+")` 로 열고, **flock 획득 성공 후에만** `seek(0)+truncate()+write()` 로 메타 갱신.
- **상태**: ✅ **적용 완료 (2026-04-22)**

### [CD-003] `_applyLanguageOverrides` 실패 시 정상 시작된 브라우저를 죽임
- **파일**: `chromeDriver.py:1046-1055`
- **문제**: 
  - 헬스체크 통과 후 CDP 명령(`Network.enable`, `Emulation.setLocaleOverride`, `Page.addScriptToEvaluateOnNewDocument`)이 간헐적으로 실패 시 `_force_kill_browser` + `BrowserStartupError` 로 500 반환.
  - Language override 는 non-critical 기능(네이버는 한국어 기본).
- **영향도**: ⭐⭐⭐ — 간헐적 500 에러의 원인.
- **수정 방향**: 실패를 warning 으로 남기고 브라우저는 유지.
- **상태**: ✅ **적용 완료 (2026-04-22)**

---

## 🟠 High — 안정성 저해

### [CD-004] `ensure_chromedriver_patched` 타임아웃 후 패치 스레드 잔존
- **파일**: `chromeDriver.py:168-190`
- **문제**: 120초 타임아웃 시 `_patcher_initialized=False` 상태로 스레드가 백그라운드에서 계속 동작 → 동일 chromedriver 바이너리에 대한 쓰기 경합.
- **수정 방향**: 타임아웃 시 명시적 실패로 서버 기동 중단, 또는 이후 `ChromeDriver()` 호출이 patching 완료까지 공유 이벤트로 대기.
- **상태**: 📋 TODO

### [CD-005] `_should_enable_uc_multi_procs` 가 매 인스턴스 생성 시 `uc.Patcher(146)` 재생성
- **파일**: `chromeDriver.py:902-923`
- **문제**: 매번 경로 탐색 I/O 발생 + 첫 요청과 이후 요청의 `user_multi_procs` 값이 다를 수 있음.
- **수정 방향**: 서버 기동 시 1회 판정 후 모듈 전역에 캐싱.
- **상태**: 📋 TODO

### [CD-006] `_terminate_process_tree` 가 2세대(손자)까지만 재귀
- **파일**: `chromeDriver.py:508-517`
- **문제**: Chrome 은 3~4세대 프로세스를 spawn. 증손자 프로세스가 좀비로 남아 FD/공유메모리 누수.
- **수정 방향**: BFS 로 모든 자손 수집.
- **상태**: 📋 TODO

### [CD-007] `_find_processes_using_profile` 가 chromedriver 서비스 프로세스를 놓침
- **파일**: `chromeDriver.py:411-414`
- **문제**: `_capture_cleanup_metadata` 전에 실패하면 `service_pid` 미저장 → chromedriver 좀비 누적 + 포트 점유.
- **수정 방향**: `_startBrowser` 시점에서 service.process.pid 를 즉시 별도 저장.
- **상태**: 📋 TODO

### [CD-008] `MAX_CONCURRENT_BROWSERS=3` 와 공유 프로필 락 설계 불일치
- **문제**: 세마포어는 3개 허용하지만 프로필 락은 1개만 통과 → 실질 직렬화. 대기하는 2개 요청이 CD-001 의 orphan 공격 트리거.
- **수정 방향** (택1):
  - (a) `MAX_CONCURRENT_BROWSERS=1` 로 고정.
  - (b) 요청별 임시 프로필 복사본 사용 (`tempfile.mkdtemp`) — 로그인 세션은 쿠키 복사로 유지.
- **상태**: 📋 TODO (CD-001 수정으로 급한 불은 꺼지지만 근본 해결 필요)

### [CD-009] `close()` 의 고정 500ms sleep
- **파일**: `chromeDriver.py:1361`
- **문제**: 모든 요청 종료 시 최소 0.5초 지연 누적.
- **수정 방향**: 짧은 폴링 루프로 변경.
- **상태**: 📋 TODO

### [CD-010] `FD_CRITICAL_THRESHOLD=950` 이 EC2 기본 ulimit(1024) 대비 과도하게 임계
- **파일**: `chromeDriver.py:38`
- **수정 방향**: systemd unit 에 `LimitNOFILE=65536` 적용 + 임계치 재조정.
- **상태**: 📋 TODO (인프라 작업 필요)

---

## 🟡 Medium

### [CD-011] `atexit` + `WeakSet` 조합으로 정리 누락 가능
- **파일**: `chromeDriver.py:49, 122-138`
- **수정 방향**: 일반 `set` 사용 + `close()`/`__del__` 에서 명시적 `discard()`.

### [CD-012] `getDriver` retry 예외 체인 불일치
- **파일**: `chromeDriver.py:1023-1025`
- **수정 방향**: `from e` 로 변경하거나 두 예외 모두 메시지에 기록.

### [CD-013] `log.py` 루트 로거 핸들러 중복 추가
- **파일**: `log.py:4-13`
- **수정 방향**: 기존 핸들러 체크 후 추가.

### [CD-014] `simpleManagementController.findTargetPeriod` 의 `re.search` NPE
- **파일**: `simpleManagementController.py:25`
- **수정 방향**: 매치 결과 None 체크 및 적절한 예외 전환.

### [CD-015] `bookingListExtractor.parseDateInfo` IndexError
- **파일**: `bookingListExtractor.py:64-79`
- **수정 방향**: 길이 검증 + 안전한 파싱.

### [CD-016] `run.sh` 의 nohup 방식 → systemd 로 전환
- **파일**: `run.sh`
- **수정 방향**: systemd service unit 작성 (`Restart=on-failure`, `LimitNOFILE=65536`, `KillMode=mixed`).

---

## 📊 우선순위 요약

| 순위 | 항목 | 상태 |
|---|---|---|
| 1 | CD-001 orphan 오판 방지 | ✅ 완료 |
| 2 | CD-002 락 파일 truncate 방지 | ✅ 완료 |
| 3 | CD-003 language override non-fatal | ✅ 완료 |
| 4 | CD-007 chromedriver service_pid 추적 | 📋 TODO |
| 5 | CD-006 자손 프로세스 BFS 정리 | 📋 TODO |
| 6 | CD-010 + CD-016 ulimit/systemd 인프라 | 📋 TODO |
| 7 | CD-008 프로필 격리 전환 | 📋 TODO |
| 8 | CD-004 / CD-005 패처 경합 정리 | 📋 TODO |

---

## 🧪 검증 방법

### CD-001, CD-002 검증
```bash
# 동시 요청 3개 발사 후 로그 관찰
for i in 1 2 3; do
  curl -X POST http://localhost:5000/sync/out \
    -H "Content-Type: application/json" \
    -d '{"activationKey":"...","monthSize":1}' &
done
wait

# 다음 로그가 **나오지 않아야** 정상:
#   "Found N orphan processes for profile ..."
#   "Profile lock acquisition failed (timeout=5.0s), attempting orphan cleanup"
# 대신 아래 로그가 나와야 함:
#   "Profile lock held by live process pid=..., waiting (remaining=...)"
```

### CD-003 검증
```bash
# 브라우저가 잘 뜨는데 language override CDP 명령이 실패하는 상황 유도 불가능하므로,
# 로그에서 아래 메시지가 warning 으로 남는지 확인 (에러 500 없이 정상 응답):
#   "Language override failed (non-fatal), continuing without overrides: ..."
```

---

## 📝 변경 이력

- **2026-04-22**: 초기 분석 및 CD-001/002/003 적용
