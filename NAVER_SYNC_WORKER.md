# Naver sync worker operations

The worker, rather than the Application scheduler, owns the Naver synchronization schedule.

Required environment variables:

- `APPLICATION_SERVER_URL`: Application API origin, for example `https://api.example.com`
- `APPLICATION_SYNC_ACCESS_KEY`: must match the Application server's `scraping.accessKey`
- `NAVER_SYNC_LOCK_FILE`: optional; defaults to `/tmp/yeoyeo_naver_sync.lock`
- `CHROME_BINARY_PATH`: executable Chrome path. HomeServer uses
  `/home/dvlprjw/.local/bin/yeoyeo-google-chrome`.
- `CHROME_PROFILE_PATH`: persistent Chrome profile directory. It must remain
  stable between cron executions.

Verify the configured browser without opening Naver:

```bash
"$CHROME_BINARY_PATH" --version
```

The current HomeServer wrapper launches Google Chrome 146.0.7680.164 from
`/home/dvlprjw/.local/google-chrome-146` with its user-local shared libraries.

Example cron entry (KST host):

```cron
11 * * * * cd /home/dvlprjw/src/YeoYeo_scraper && ./venv/bin/python naver_sync_worker.py >> logs/naver-sync-worker.log 2>&1
```

Use logrotate for `logs/naver-sync-worker.log`. Each event is JSON and contains a `runId`, direction, stage, and independent status. Reservation PII is intentionally excluded.

The worker obtains a plan first, but every Application API independently enforces Dynamic Config. A disabled direction is skipped even if a stale or modified worker calls an endpoint directly. Browser/login failures are not retried by the worker.

## Cutover

1. Deploy and verify the Application APIs while both sync configs are disabled.
2. Configure the worker environment without printing either key.
3. Run unit tests and one approved manual worker execution in a non-production environment.
4. Install the cron entry with both directions disabled and confirm `DISABLED` logs.
5. Restrict the Application API security group/reverse proxy so `/internal/naver-sync/*` is reachable only from the Scraping server private IP, in addition to the sync key.
6. Enable one direction at a time and verify Application and worker logs using the same `runId`.

## Rollback

1. Disable both Dynamic Config directions.
2. Remove/disable the worker cron entry and wait for the lock holder to finish.
3. To temporarily restore the legacy Application schedules, set:
   - `naver.sync.legacy-day-cron=11 11 9-23 * * *`
   - `naver.sync.legacy-overnight-cron=35 27 0,2,5,7 * * *`
4. Re-enable directions one at a time and verify both servers' logs.

Do not run the worker cron and legacy schedules at the same time.
