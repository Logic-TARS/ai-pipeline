# Publishing Runbook

**⚠️ DANGER: Publishing is real.** Every action in this document actually publishes content to social platforms. Follow each step carefully.

## Pre-flight

```bash
ai-popline doctor
```

Verify:
- [ ] All external tool paths resolve
- [ ] Output directory is writable
- [ ] Browser profile is accessible (for Photo-Process pipelines)

## Platform-Specific Guides

### Douyin (抖音)

1. **Pre-flight**: Log into Douyin Creator account in the SAU-authenticated browser session.
2. **Dry-run**: Run the task with `"publish": false` first. Review the generated video.
3. **Publish**: Set `"publish": true` and run with target:
   ```json
   {"platform": "douyin", "account": "account-name"}
   ```
4. **Verify**: Check `publish_results` in status.json. Must show "仅自己可见" proof.
5. **Rollback**: Delete the video from Douyin Creator Center if needed.

### Kuaishou (快手)

1. **Pre-flight**: Log into Kuaishou Creator account.
2. **Dry-run**: Same as Douyin.
3. **Publish**: Set `"publish": true` with target:
   ```json
   {"platform": "kuaishou", "account": "account-name"}
   ```
4. **Verify**: Check private visibility proof in publish_results.
5. **Rollback**: Delete from Kuaishou Creator Center.

### Bilibili (B站)

1. **Pre-flight**: Verify `SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1` in `.env`.
2. **Dry-run**: Same as above.
3. **Publish**: Requires `tid` (category ID) in publish target:
   ```json
   {"platform": "bilibili", "account": "account-name", "tid": 27}
   ```
4. **Verify**: Upload must include `--is-only-self 1`. Blocked if private args are missing.
5. **Rollback**: Delete from Bilibili Creator Center.

### Tencent (腾讯/视频号)

1. **Pre-flight**: Log into Tencent Creator account.
2. **Publish**: Saved as draft only:
   ```json
   {"platform": "tencent", "account": "account-name"}
   ```
3. **Verify**: Confirm draft was saved. Manual review required before publishing.

## Safety Rules (Fail-Closed)

- All publish defaults to `false`. Explicit `"publish": true` required.
- Douyin/Kuaishou: must prove "仅自己可见" (private visibility).
- Bilibili: must pass `--is-only-self 1`. Blocked if missing.
- Tencent: saves as draft — never auto-publishes.
- Any uncertainty → `BLOCKED` status. No silent publication.

## Troubleshooting

| Problem | Check |
|---|---|
| `PRIVATE_VISIBILITY_UNSUPPORTED` | SAU version supports private args? Account logged in? |
| `ALREADY_PUBLISHED` | Video hash matches a prior upload. Force re-encode or change content. |
| `PUBLISH_FAILED` | Check SAU logs. Account session valid? Platform rate limits? |
| `BLOCKED` on Bilibili | `SAU_BILIBILI_PRIVATE_ARGS` env var set? |
