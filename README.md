# IOM Exam Routine Watcher

Watches https://iom.edu.np/examination/exam-routine/ and sends a free push
notification (ntfy.sh) when a **new exam routine** is posted. Routines only.
Runs on GitHub Actions, so it costs nothing.

## Files
```
check_routines.py
requirements.txt
state.json
README.md
.github/workflows/check-routines.yml
```

## Setup

### 1. Create the repo
New repository, e.g. `iom-routine-watcher`. Upload all files above.
The workflow file must end up at exactly `.github/workflows/check-routines.yml`.
On phone: **Add file → Create new file**, type that full path as the filename,
and paste the content.

### 2. Notifications (ntfy)
Use the same ntfy topic as your results watcher, or a new random one.
Subscribe to it in the ntfy app.

### 3. Add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value | Required |
|------|-------|----------|
| `NTFY_TOPIC` | your ntfy topic name | yes |
| `HEALTHCHECK_URL` | healthchecks.io ping URL | optional |

### 4. First run
**Actions** tab → **Check IOM Exam Routines** → **Run workflow**.
This only records the routines already on the page (no notification).
Check the log shows `First run: state initialized`.

### 5. Automatic triggering (every 5 minutes)
The workflow is `workflow_dispatch` only. Use an external cron service
(e.g. cron-job.org) to call:

- **Method:** POST
- **URL:** `https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/check-routines.yml/dispatches`
- **Headers:**
  - `Authorization: Bearer <fine-grained token>`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
- **Body:** `{"ref":"main"}`
- **Schedule:** every 5 minutes

Create the token under GitHub → Settings → Developer settings → Fine-grained
tokens. Limit it to this one repo with **Actions: Read and write**. Keep it
only in the cron service, never in the repo.

## Testing
- Local dry run (prints what it parses, changes nothing):
  `python check_routines.py --dry-run`
- Force a test alert: delete one entry from `"seen"` in `state.json`, commit,
  run the workflow. You should get a notification for that routine.

## Behavior
- Tracks routines by Google Drive file ID. An amended routine with a new link alerts.
- Any unseen routine alerts, whatever its date.
- If the site is down or the page parses to zero entries, state is untouched.
- If the notification fails, state is not updated, so the next run retries.
- Remembers the last 200 routines.

## Known limitations
- If IOM replaces the file behind an existing Drive link, it can't be detected.
- Only page 1 is read. If IOM deletes a routine, an older one may shift onto
  page 1 and trigger one false alert.
- If the site's HTML changes, parsing returns zero entries. Use the healthchecks.io
  ping so you're told when the watcher goes quiet.
