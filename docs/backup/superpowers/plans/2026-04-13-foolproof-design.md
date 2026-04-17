# Foolproof Design (防呆设计) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add comprehensive foolproof (防呆) guards across the entire recruitment assistant to prevent HR users from making mistakes, seeing confusing errors, or losing data.

**Architecture:** Changes span 3 layers: (1) Backend Pydantic schema validators + router-level guards, (2) Frontend Vue form validation + UX feedback + confirmation dialogs, (3) Chrome extension pre-flight checks. Each task is scoped to one file or one tightly-coupled pair. No new files created except a shared frontend utils module.

**Tech Stack:** Python FastAPI + Pydantic v2 validators, Vue 3 Composition API + Element Plus, Chrome Extension Manifest V3

**Scope exclusion:** Email-to-candidate features are excluded per user request. All other防呆items from the analysis are in scope.

---

## File Map

| Task | Files Modified | Responsibility |
|------|---------------|----------------|
| 1 | `app/modules/scheduling/schemas.py` | Backend: time, phone, email, range validators |
| 2 | `app/modules/screening/schemas.py` | Backend: salary/year range validators |
| 3 | `app/modules/resume/schemas.py` | Backend: phone/email format validators |
| 4 | `app/modules/scheduling/router.py` | Backend: duplicate interview check, FK protection on delete, past-time guard |
| 5 | `app/modules/resume/router.py` | Backend: batch size limit, AI parse idempotency |
| 6 | `app/modules/screening/router.py` | Backend: FK protection on job delete |
| 7 | `app/modules/notification/router.py` | Backend: pre-flight checks (config, contact info) |
| 8 | `app/modules/meeting/router.py` | Backend: time-rounding warning in response |
| 9 | `app/main.py` | Backend: health-check endpoint enhanced with service status |
| 10 | `frontend/src/views/Dashboard.vue` | Frontend: system health cards + quick-start guide |
| 11 | `frontend/src/views/Resumes.vue` | Frontend: validation, save feedback, warnings, safer clear-all |
| 12 | `frontend/src/views/Jobs.vue` | Frontend: range validation, timeout, delete guard |
| 13 | `frontend/src/views/Interviewers.vue` | Frontend: format validation, duplicate warning, FK guard |
| 14 | `frontend/src/views/Interviews.vue` | Frontend: calendar guards, pause refresh, safer dialogs, result summaries |
| 15 | `frontend/src/views/Notifications.vue` | Frontend: repeat-send warning, channel status, safer clear-all |
| 16 | `frontend/src/views/Settings.vue` | Frontend: config guidance, restart hint |
| 17 | `frontend/src/App.vue` | Frontend: global network status bar |
| 18 | `chrome_extension/popup.js` + `popup.html` | Extension: pre-flight checks, better feedback |

---

## Task 1: Backend — Scheduling Schema Validators

**Files:**
- Modify: `app/modules/scheduling/schemas.py`

Add Pydantic model_validators to enforce: start_time < end_time on InterviewCreate/InterviewUpdate/AvailabilityCreate, phone format (11-digit Chinese mobile), email format.

- [ ] **Step 1: Add time range validator to InterviewCreate**

In `app/modules/scheduling/schemas.py`, add to `InterviewCreate`:

```python
from pydantic import model_validator, field_validator
import re

class InterviewCreate(BaseModel):
    resume_id: int
    interviewer_id: int
    job_id: int | None = None
    start_time: datetime
    end_time: datetime
    meeting_link: str = ""
    meeting_password: str = ""
    notes: str = ""

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError('结束时间必须晚于开始时间')
        return self
```

- [ ] **Step 2: Add same validator to InterviewUpdate**

```python
class InterviewUpdate(BaseModel):
    # ... existing fields ...

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError('结束时间必须晚于开始时间')
        return self
```

- [ ] **Step 3: Add time validator to AvailabilityCreate**

```python
class AvailabilityCreate(BaseModel):
    interviewer_id: int
    start_time: datetime
    end_time: datetime
    source: str = "manual"

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError('结束时间必须晚于开始时间')
        return self
```

- [ ] **Step 4: Add phone/email validators to InterviewerCreate**

```python
class InterviewerCreate(BaseModel):
    name: str
    phone: str = ""
    email: str = ""
    department: str = ""
    feishu_user_id: str = ""

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确，需为11位中国手机号')
        return v

    @field_validator('email')
    @classmethod  
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('邮箱格式不正确')
        return v

    @model_validator(mode='after')
    def at_least_one_contact(self):
        if not self.phone and not self.email and not self.feishu_user_id:
            raise ValueError('手机号、邮箱、飞书ID至少填写一项')
        return self
```

- [ ] **Step 5: Verify by starting server**

Run: `cd /c/bzli/boss_feishu && python -c "from app.modules.scheduling.schemas import InterviewCreate, InterviewerCreate; print('OK')"`

- [ ] **Step 6: Commit**

```
git add app/modules/scheduling/schemas.py
git commit -m "feat: add time-range, phone, email validators to scheduling schemas"
```

---

## Task 2: Backend — Screening Schema Validators

**Files:**
- Modify: `app/modules/screening/schemas.py`

- [ ] **Step 1: Add range validators to JobCreate**

```python
from pydantic import model_validator

class JobCreate(BaseModel):
    # ... existing fields ...

    @model_validator(mode='after')
    def validate_ranges(self):
        if self.work_years_min is not None and self.work_years_max is not None:
            if self.work_years_max < self.work_years_min:
                raise ValueError('最大工作年限不能小于最小工作年限')
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_max < self.salary_min:
                raise ValueError('最高薪资不能低于最低薪资')
        return self
```

- [ ] **Step 2: Add same validator to JobUpdate**

Same `validate_ranges` logic, but check fields are not None before comparing.

- [ ] **Step 3: Verify import**

Run: `python -c "from app.modules.screening.schemas import JobCreate; print('OK')"`

- [ ] **Step 4: Commit**

```
git add app/modules/screening/schemas.py
git commit -m "feat: add salary/year range validators to job schemas"
```

---

## Task 3: Backend — Resume Schema Validators

**Files:**
- Modify: `app/modules/resume/schemas.py`

- [ ] **Step 1: Add phone/email format validators**

```python
from pydantic import field_validator
import re

class ResumeCreate(BaseModel):
    # ... existing fields ...

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确')
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('邮箱格式不正确')
        return v
```

- [ ] **Step 2: Add same validators to ResumeUpdate**

Same field_validators for phone and email on the update schema.

- [ ] **Step 3: Verify**

Run: `python -c "from app.modules.resume.schemas import ResumeCreate; print('OK')"`

- [ ] **Step 4: Commit**

```
git add app/modules/resume/schemas.py
git commit -m "feat: add phone/email format validators to resume schemas"
```

---

## Task 4: Backend — Scheduling Router Guards

**Files:**
- Modify: `app/modules/scheduling/router.py`

- [ ] **Step 1: Add duplicate interview check for same candidate**

In the `POST /interviews` endpoint, after the existing conflict check, add:

```python
# 同一候选人是否已有待面试安排
existing_for_candidate = db.query(Interview).filter(
    Interview.resume_id == data.resume_id,
    Interview.status != "cancelled",
).first()
if existing_for_candidate:
    raise HTTPException(
        status_code=409,
        detail=f"该候选人已有待面试安排（面试ID: {existing_for_candidate.id}），请先取消旧面试或编辑现有面试"
    )
```

- [ ] **Step 2: Add past-time guard**

In the `POST /interviews` endpoint, check start_time is in the future:

```python
from datetime import datetime, timezone
if data.start_time.replace(tzinfo=None) < datetime.utcnow():
    raise HTTPException(status_code=400, detail="面试时间不能早于当前时间")
```

- [ ] **Step 3: Add FK protection on interviewer delete**

In `DELETE /interviewers/{id}`, before deleting check for linked interviews:

```python
linked = db.query(Interview).filter(
    Interview.interviewer_id == interviewer_id,
    Interview.status != "cancelled",
).count()
if linked > 0:
    raise HTTPException(
        status_code=409,
        detail=f"该面试官有 {linked} 场待面试，请先取消或重新分配后再删除"
    )
```

- [ ] **Step 4: Add duplicate interviewer check**

In `POST /interviewers`, check name+phone/email uniqueness:

```python
if data.phone:
    dup = db.query(Interviewer).filter(Interviewer.phone == data.phone).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"手机号 {data.phone} 已被面试官「{dup.name}」使用")
```

- [ ] **Step 5: Verify server starts**

Run: `cd /c/bzli/boss_feishu && python -c "from app.modules.scheduling.router import router; print('OK')"`

- [ ] **Step 6: Commit**

```
git add app/modules/scheduling/router.py
git commit -m "feat: add duplicate check, past-time guard, FK protection to scheduling router"
```

---

## Task 5: Backend — Resume Router Guards

**Files:**
- Modify: `app/modules/resume/router.py`

- [ ] **Step 1: Add batch size limit**

In `POST /batch`, limit the list length:

```python
@router.post("/batch", status_code=201)
def batch_create(items: list[ResumeCreate], ...):
    if len(items) > 100:
        raise HTTPException(status_code=400, detail="单次批量导入不能超过100条")
    # ... existing logic
```

- [ ] **Step 2: Add AI parse idempotency guard**

In `POST /ai-parse-all`, prevent multiple concurrent starts:

```python
from app.modules.resume._ai_parse_worker import _status

@router.post("/ai-parse-all")
async def ai_parse_all(...):
    if _status.get("running"):
        return {"status": "already_running", "message": "AI解析任务已在运行中，请勿重复启动"}
    # ... existing logic
```

- [ ] **Step 3: Add FK check before clear-all**

In `DELETE /clear-all`, return a count breakdown so frontend can show what will be deleted:

The current implementation already cascades. Just enhance the response:

```python
interview_count = db.query(Interview).count()
notification_count = db.query(NotificationLog).count()
# ... delete logic ...
return {"deleted_resumes": count, "deleted_interviews": interview_count, "deleted_notifications": notification_count}
```

- [ ] **Step 4: Verify**

Run: `python -c "from app.modules.resume.router import router; print('OK')"`

- [ ] **Step 5: Commit**

```
git add app/modules/resume/router.py
git commit -m "feat: add batch limit, AI parse guard, enhanced clear-all to resume router"
```

---

## Task 6: Backend — Screening Router FK Protection

**Files:**
- Modify: `app/modules/screening/router.py`

- [ ] **Step 1: Add FK check on job delete**

```python
@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, service = Depends(get_service), db: Session = Depends(get_db)):
    from app.modules.scheduling.models import Interview
    linked = db.query(Interview).filter(
        Interview.job_id == job_id,
        Interview.status != "cancelled",
    ).count()
    if linked > 0:
        raise HTTPException(
            status_code=409,
            detail=f"该岗位下有 {linked} 场待面试，请先处理后再删除"
        )
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="岗位不存在")
    return {"status": "ok"}
```

- [ ] **Step 2: Verify and commit**

```
git add app/modules/screening/router.py
git commit -m "feat: add FK protection on job delete"
```

---

## Task 7: Backend — Notification Pre-flight Checks

**Files:**
- Modify: `app/modules/notification/router.py`

- [ ] **Step 1: Add pre-flight config and contact checks**

Replace the existing `/send` endpoint to check config and contact info before sending:

```python
@router.post("/send", response_model=SendNotificationResponse)
async def send_notifications(request: SendNotificationRequest, service = Depends(get_service), db: Session = Depends(get_db)):
    from app.modules.scheduling.models import Interview, Interviewer
    from app.modules.resume.models import Resume
    from app.config import settings

    interview = db.query(Interview).filter(Interview.id == request.interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    warnings = []

    # Check meeting link
    if not interview.meeting_link:
        raise HTTPException(status_code=400, detail="请先创建腾讯会议后再发送面试通知")

    # Check interviewer feishu config
    interviewer = db.query(Interviewer).filter(Interviewer.id == interview.interviewer_id).first()
    if request.send_feishu_to_interviewer:
        if not settings.feishu_app_id or not settings.feishu_app_secret:
            warnings.append("飞书未配置，将跳过飞书通知")
            request.send_feishu_to_interviewer = False
        elif interviewer and not interviewer.feishu_user_id:
            warnings.append(f"面试官「{interviewer.name}」无飞书ID，将跳过飞书通知")
            request.send_feishu_to_interviewer = False

    # Check candidate email (skip - user said no email to candidate)
    # But still warn if generate_template and no contact info
    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    if resume and not resume.phone and not resume.email:
        warnings.append("候选人无联系方式，消息模板生成后请手动联系")

    result = await service.send_interview_notifications(
        request.interview_id,
        send_email=request.send_email_to_candidate,
        send_feishu=request.send_feishu_to_interviewer,
        generate_template=request.generate_template,
    )
    if warnings:
        result["warnings"] = warnings
    return result
```

- [ ] **Step 2: Verify and commit**

```
git add app/modules/notification/router.py
git commit -m "feat: add pre-flight config/contact checks to notification send"
```

---

## Task 8: Backend — Meeting Time-Rounding Warning

**Files:**
- Modify: `app/modules/meeting/router.py`

- [ ] **Step 1: Add rounding detection and warning in response**

After computing `start_time_str`, check if minutes were rounded:

```python
# 检测时间取整
original_minutes = beijing_start.minute
rounded_minutes = (original_minutes // 30) * 30
time_rounded = original_minutes != rounded_minutes
if time_rounded:
    rounded_start = beijing_start.replace(minute=rounded_minutes, second=0)
    start_time_str = rounded_start.strftime("%H:%M")

# ... after create_meeting success ...
response = {
    "status": "ok",
    "link": result["link"],
    "meeting_id": result["meeting_id"],
    "account": account,
}
if time_rounded:
    response["warning"] = f"腾讯会议仅支持整点/半点，开始时间已从 {beijing_start.strftime('%H:%M')} 调整为 {start_time_str}"
return response
```

- [ ] **Step 2: Commit**

```
git add app/modules/meeting/router.py
git commit -m "feat: add time-rounding warning to meeting auto-create"
```

---

## Task 9: Backend — Enhanced Health Check

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Enhance /api/health to include service status**

```python
@app.get("/api/health")
def health_check():
    from app.config import settings
    
    feishu_configured = bool(settings.feishu_app_id and settings.feishu_app_secret)
    ai_configured = bool(settings.ai_enabled and settings.ai_api_key)
    smtp_configured = bool(settings.smtp_host and settings.smtp_user)
    meeting_accounts = settings.tencent_meeting_accounts.split(",") if settings.tencent_meeting_accounts else []

    return {
        "status": "ok",
        "app_name": settings.app_name,
        "services": {
            "feishu": {"configured": feishu_configured},
            "ai": {"enabled": settings.ai_enabled, "configured": ai_configured, "model": settings.ai_model if ai_configured else ""},
            "email": {"configured": smtp_configured},
            "meeting": {"configured": len(meeting_accounts) > 0, "account_count": len(meeting_accounts)},
        }
    }
```

- [ ] **Step 2: Commit**

```
git add app/main.py
git commit -m "feat: enhance health-check with service status for dashboard"
```

---

## Task 10: Frontend — Dashboard Health & Quick-Start

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: Add service status cards**

After the existing 4 stat cards, add a "系统状态" section that calls `/api/health` and shows colored status for each service (feishu, AI, email, meeting). Green = configured, yellow = not configured.

- [ ] **Step 2: Add quick-start guide**

Below stats, add a "快速开始" card with numbered steps:
1. 配置系统 (Settings) — if services not configured
2. 添加面试官 (Interviewers)
3. 创建岗位 (Jobs)
4. 采集简历 (Chrome Extension)
5. 筛选/AI评估简历 (Resumes)
6. 安排面试 (Interviews)

Each step links to the relevant page and shows check/pending icon based on data.

- [ ] **Step 3: Commit**

```
git add frontend/src/views/Dashboard.vue
git commit -m "feat: add system health cards and quick-start guide to dashboard"
```

---

## Task 11: Frontend — Resumes Page Foolproofing

**Files:**
- Modify: `frontend/src/views/Resumes.vue`

- [ ] **Step 1: Add save feedback (green flash)**

On successful field save (`saveField`), flash a green border + checkmark icon on the input for 1.5s:

```javascript
const saveField = async (resume, field) => {
  try {
    await resumeApi.update(resume.id, { [field]: resume[field] })
    // Flash green feedback
    resume._savedField = field
    setTimeout(() => { resume._savedField = '' }, 1500)
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
    loadResumes()
  }
}
```

Add `:class="{ 'save-success': resume._savedField === 'phone' }"` to inputs, with CSS `.save-success { border-color: #67c23a; transition: border-color 0.3s; }`.

- [ ] **Step 2: Add phone/email format validation**

On blur of phone input, validate format before saving:

```javascript
const saveField = async (resume, field) => {
  if (field === 'phone' && resume.phone && !/^1[3-9]\d{9}$/.test(resume.phone)) {
    ElMessage.warning('手机号格式不正确，需为11位中国手机号')
    return
  }
  if (field === 'email' && resume.email && !/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(resume.email)) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  // ... existing save logic
}
```

- [ ] **Step 3: Add missing contact info warning banner**

On each resume card, if phone and email are both empty, show an orange warning bar:

```html
<div v-if="!resume.phone && !resume.email" class="contact-warning">
  <el-icon><WarningFilled /></el-icon> 联系方式缺失，无法发送面试通知
</div>
```

- [ ] **Step 4: Safer clear-all with text input confirmation**

Replace the simple confirm dialog with a typed confirmation:

```javascript
const clearAll = async () => {
  try {
    await ElMessageBox.prompt(
      '此操作将永久删除所有简历、面试和通知记录，且不可恢复。\n请输入「确认清空」以继续：',
      '危险操作',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'error',
        inputValidator: (val) => val === '确认清空' || '请输入「确认清空」',
        inputPlaceholder: '确认清空',
      }
    )
    const res = await resumeApi.clearAll()
    ElMessage.success(`已清空 ${res.data.deleted_resumes} 条简历`)
    loadResumes()
  } catch { /* cancelled */ }
}
```

- [ ] **Step 5: AI parse timeout**

Add a 3-minute timeout to the polling mechanism. If no progress changes in 180 seconds, stop polling and show warning:

```javascript
let lastProgressTime = Date.now()
let lastProgressCount = 0

// Inside polling callback:
if (currentParsed !== lastProgressCount) {
  lastProgressTime = Date.now()
  lastProgressCount = currentParsed
}
if (Date.now() - lastProgressTime > 180000) {
  stopPolling()
  ElMessage.warning('AI解析超过3分钟无进度，已暂停。请稍后重试。')
}
```

- [ ] **Step 6: Confirm before rejecting a passed resume**

```javascript
const setStatus = async (resume, newStatus) => {
  if (resume.status === 'passed' && newStatus === 'rejected') {
    try {
      await ElMessageBox.confirm(`确定将「${resume.name}」从"已通过"改为"已淘汰"？`, '确认操作')
    } catch { return }
  }
  // ... existing logic
}
```

- [ ] **Step 7: Commit**

```
git add frontend/src/views/Resumes.vue
git commit -m "feat: add validation, save feedback, warnings, safer clear-all to Resumes"
```

---

## Task 12: Frontend — Jobs Page Foolproofing

**Files:**
- Modify: `frontend/src/views/Jobs.vue`

- [ ] **Step 1: Add range validation in job form**

In the save handler, validate before submit:

```javascript
const saveJob = async () => {
  if (!form.title?.trim()) {
    ElMessage.warning('请填写岗位名称')
    return
  }
  if (form.work_years_min != null && form.work_years_max != null && form.work_years_max < form.work_years_min) {
    ElMessage.warning('最大工作年限不能小于最小工作年限')
    return
  }
  if (form.salary_min != null && form.salary_max != null && form.salary_max < form.salary_min) {
    ElMessage.warning('最高薪资不能低于最低薪资')
    return
  }
  // ... existing save logic
}
```

- [ ] **Step 2: Add AI evaluate timeout (60s)**

```javascript
const evaluateJob = async (job) => {
  job._evaluating = true
  const timer = setTimeout(() => {
    job._evaluating = false
    ElMessage.warning('AI评估超时，请稍后重试')
  }, 60000)
  try {
    const res = await aiApi.batchEvaluate(job.id)
    clearTimeout(timer)
    // ... show results
  } catch (e) {
    clearTimeout(timer)
    ElMessage.error('评估失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    job._evaluating = false
  }
}
```

- [ ] **Step 3: FK-aware delete**

The backend now returns 409 if job has linked interviews. Handle it in frontend:

```javascript
const deleteJob = async (job) => {
  try {
    await ElMessageBox.confirm(`确定删除岗位「${job.title}」？`, '确认删除')
    await jobApi.delete(job.id)
    ElMessage.success('已删除')
    loadJobs()
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response.data.detail)
    } else if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}
```

- [ ] **Step 4: Commit**

```
git add frontend/src/views/Jobs.vue
git commit -m "feat: add range validation, timeout, FK-aware delete to Jobs"
```

---

## Task 13: Frontend — Interviewers Page Foolproofing

**Files:**
- Modify: `frontend/src/views/Interviewers.vue`

- [ ] **Step 1: Add phone/email format validation**

In save handler:

```javascript
const saveInterviewer = async () => {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (form.phone && !/^1[3-9]\d{9}$/.test(form.phone)) {
    ElMessage.warning('手机号格式不正确，需为11位中国手机号')
    return
  }
  if (form.email && !/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(form.email)) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  if (!form.phone && !form.email && !form.feishu_user_id) {
    ElMessage.warning('手机号、邮箱、飞书ID至少填写一项')
    return
  }
  // ... existing save
}
```

- [ ] **Step 2: Handle 409 on duplicate and FK-protected delete**

```javascript
// Save handler catch:
catch (e) {
  if (e.response?.status === 409) {
    ElMessage.warning(e.response.data.detail)
  } else {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || '请检查飞书配置'))
  }
}

// Delete handler catch:
catch (e) {
  if (e.response?.status === 409) {
    ElMessage.warning(e.response.data.detail)
  } else if (e !== 'cancel') {
    ElMessage.error('删除失败')
  }
}
```

- [ ] **Step 3: Better feishu lookup error message**

Replace generic 422 error with friendly message:

```javascript
// In save catch block, check for 422:
if (e.response?.status === 422) {
  const detail = e.response.data?.detail
  if (typeof detail === 'string' && detail.includes('飞书')) {
    ElMessage.warning('未在飞书通讯录中找到该用户，请确认信息是否正确。面试官已保存，飞书ID可稍后补充。')
  } else {
    ElMessage.warning('输入信息有误: ' + (Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : detail))
  }
}
```

- [ ] **Step 4: Commit**

```
git add frontend/src/views/Interviewers.vue
git commit -m "feat: add format validation, duplicate/FK guards to Interviewers"
```

---

## Task 14: Frontend — Interviews Page Foolproofing

**Files:**
- Modify: `frontend/src/views/Interviews.vue`

This is the largest and most critical page. Changes:

- [ ] **Step 1: Pause auto-refresh when dialog is open**

```javascript
// In dialog open handler:
const openDialog = () => {
  showDialog.value = true
  stopAutoRefresh()  // pause 15s polling
}

// In dialog close:
const closeDialog = () => {
  showDialog.value = false
  startAutoRefresh()  // resume
}
```

- [ ] **Step 2: Show candidate contact warning**

When selecting a candidate in the dialog, if they have no phone and no email, show orange alert:

```html
<el-alert v-if="selectedCandidate && !selectedCandidate.phone && !selectedCandidate.email"
  title="该候选人无联系方式，将无法发送面试通知"
  type="warning" :closable="false" show-icon style="margin-bottom: 10px;" />
```

- [ ] **Step 3: Prevent selecting past time**

Configure FullCalendar `selectAllow` to block past times:

```javascript
selectAllow: (selectInfo) => {
  return selectInfo.start >= new Date()
},
```

Add `validRange` to grey out past dates:

```javascript
validRange: {
  start: new Date().toISOString().slice(0, 10)
},
```

- [ ] **Step 4: Warn when selecting over busy slots**

After a time selection in `handleDateSelect`, check if it overlaps any busy events:

```javascript
const handleDateSelect = (selectInfo) => {
  // Check overlap with busy slots
  const busyOverlap = calendarEvents.value.some(evt =>
    evt.color === '#f56c6c' && // red = feishu busy
    selectInfo.start < new Date(evt.end) &&
    selectInfo.end > new Date(evt.start)
  )
  if (busyOverlap) {
    ElMessageBox.confirm(
      '所选时段与面试官已有日程冲突，确认安排？',
      '时间冲突提示',
      { confirmButtonText: '仍然安排', cancelButtonText: '重新选择', type: 'warning' }
    ).then(() => {
      form.start_time = selectInfo.start
      form.end_time = selectInfo.end
    }).catch(() => {
      calendarRef.value?.getApi().unselect()
    })
    return
  }
  form.start_time = selectInfo.start
  form.end_time = selectInfo.end
}
```

- [ ] **Step 5: Handle duplicate candidate 409**

```javascript
// In save handler catch:
if (e.response?.status === 409) {
  ElMessage.warning(e.response.data.detail)
  return
}
```

- [ ] **Step 6: Safer clear-all with text input**

Same pattern as Resumes: require typing "确认清空".

- [ ] **Step 7: Show notification result summary**

After sending notifications, show a detailed breakdown:

```javascript
const sendNotification = async (interview) => {
  // ... send logic ...
  const results = res.data.results || []
  const warnings = res.data.warnings || []
  
  let summary = results.map(r => {
    const icon = r.status === 'sent' ? '✓' : r.status === 'generated' ? '✓' : '✗'
    const channelName = { email: '邮件', feishu: '飞书消息', feishu_pdf: '简历PDF', calendar: '飞书日程', template: '消息模板' }[r.channel] || r.channel
    return `${icon} ${channelName} → ${r.recipient}`
  }).join('\n')

  if (warnings.length) {
    summary += '\n\n⚠ ' + warnings.join('\n⚠ ')
  }

  ElMessageBox.alert(summary, '通知发送结果', { dangerouslyUseHTMLString: false })
}
```

- [ ] **Step 8: Show time-rounding warning from meeting creation**

```javascript
const createMeeting = async (interview) => {
  // ... existing logic ...
  if (res.data.warning) {
    ElMessage.warning(res.data.warning)
  }
  ElMessage.success(`会议已创建 (账号: ${res.data.account})`)
}
```

- [ ] **Step 9: Repeat-send detection**

Check notification logs before sending. If already sent, warn:

```javascript
const sendNotification = async (interview) => {
  // Check if already sent
  const logs = await notificationApi.listLogs(interview.id)
  const hasSent = logs.data?.items?.some(l => l.status === 'sent')
  if (hasSent) {
    try {
      await ElMessageBox.confirm('该面试已发送过通知，确认再次发送？', '重复发送提示', { type: 'warning' })
    } catch { return }
  }
  // ... proceed to send
}
```

- [ ] **Step 10: Meeting account full - friendly message**

```javascript
// In createMeeting catch:
if (e.response?.status === 409) {
  ElMessage.warning('当前时段所有会议账号已占用，请调整面试时间或等待其他会议结束')
} else {
  ElMessage.error('创建失败: ' + (e.response?.data?.detail || e.message))
}
```

- [ ] **Step 11: Commit**

```
git add frontend/src/views/Interviews.vue
git commit -m "feat: comprehensive foolproofing for Interviews page"
```

---

## Task 15: Frontend — Notifications Page Foolproofing

**Files:**
- Modify: `frontend/src/views/Notifications.vue`

- [ ] **Step 1: Safer clear-all with text input**

Same pattern: require typing "确认清空".

- [ ] **Step 2: Add pagination**

```javascript
const page = ref(1)
const pageSize = 20
const pagedItems = computed(() => {
  const start = (page.value - 1) * pageSize
  return allItems.value.slice(start, start + pageSize)
})
```

Add `<el-pagination>` at bottom.

- [ ] **Step 3: Commit**

```
git add frontend/src/views/Notifications.vue
git commit -m "feat: add safer clear-all and pagination to Notifications"
```

---

## Task 16: Frontend — Settings Page Guidance

**Files:**
- Modify: `frontend/src/views/Settings.vue`

- [ ] **Step 1: Add configuration file path hint and restart guidance**

Add a yellow alert at the top:

```html
<el-alert type="warning" :closable="false" show-icon style="margin-bottom: 20px;">
  <template #title>配置修改说明</template>
  配置文件位于程序目录下的 <b>.env</b> 文件中。修改后需要<b>重启服务</b>才能生效。
</el-alert>
```

- [ ] **Step 2: Add real-time connectivity test per service**

For each tab, add a "测试连接" button that pings the service:

```javascript
const testFeishu = async () => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    if (data.services?.feishu?.configured) {
      ElMessage.success('飞书已配置')
    } else {
      ElMessage.warning('飞书未配置，请在 .env 中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET')
    }
  } catch {
    ElMessage.error('无法连接服务器')
  }
}
```

- [ ] **Step 3: Commit**

```
git add frontend/src/views/Settings.vue
git commit -m "feat: add config guidance and connectivity test to Settings"
```

---

## Task 17: Frontend — Global Network Status Bar

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add network status detection**

```javascript
const networkOk = ref(true)
let healthTimer = null

const checkHealth = async () => {
  try {
    const res = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
    networkOk.value = res.ok
  } catch {
    networkOk.value = false
  }
}

onMounted(() => {
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
})
onUnmounted(() => clearInterval(healthTimer))
```

- [ ] **Step 2: Add disconnection banner**

At the top of the layout, above the content area:

```html
<div v-if="!networkOk" class="network-bar">
  <el-icon><WarningFilled /></el-icon>
  与服务器断开连接，请检查服务是否正在运行
</div>
```

CSS:
```css
.network-bar {
  background: #f56c6c;
  color: white;
  text-align: center;
  padding: 8px;
  font-size: 14px;
  position: fixed;
  top: 0;
  left: 200px;
  right: 0;
  z-index: 9999;
}
```

- [ ] **Step 3: Add beforeunload guard**

```javascript
// In App.vue or as a global mixin:
window.addEventListener('beforeunload', (e) => {
  // Check if any dialog is open (using a global ref or event bus)
  const hasOpenDialog = document.querySelector('.el-overlay')
  if (hasOpenDialog) {
    e.preventDefault()
    e.returnValue = ''
  }
})
```

- [ ] **Step 4: Commit**

```
git add frontend/src/App.vue
git commit -m "feat: add global network status bar and beforeunload guard"
```

---

## Task 18: Chrome Extension — Pre-flight Checks & Better Feedback

**Files:**
- Modify: `chrome_extension/popup.js`
- Modify: `chrome_extension/popup.html`

- [ ] **Step 1: Add page detection before batch collect**

In popup.js, before sending `batchCollect` message, check if content script is on the right page:

```javascript
// Send a ping first
chrome.tabs.sendMessage(tab.id, { action: 'ping' }, (response) => {
  if (chrome.runtime.lastError || !response) {
    showResult('请先刷新Boss直聘页面（插件需要页面刷新后才能工作）', 'error')
    return
  }
  if (!response.onMessagePage) {
    showResult('请先打开Boss直聘的「消息」页面再进行批量采集', 'error')
    return
  }
  // Proceed with batch collect
})
```

In content.js, add ping handler:

```javascript
if (message.action === 'ping') {
  const onMessagePage = !!document.querySelector('.geek-item') || window.location.href.includes('/web/geek/chat')
  sendResponse({ ok: true, onMessagePage })
  return
}
```

- [ ] **Step 2: Show batch collect pre-warning**

Before starting batch collect, show reminder:

```javascript
const startBatch = () => {
  if (!confirm('采集过程中请勿操作Boss直聘页面，点击页面会暂停采集。\n\n确认开始？')) return
  // ... proceed
}
```

- [ ] **Step 3: Enhanced result summary**

After batch collect, show categorized summary:

```javascript
const showBatchSummary = (results) => {
  const withPdf = results.filter(r => r.method === 'pdf').length
  const pageOnly = results.filter(r => r.method === 'page').length
  const failed = results.filter(r => r.status === 'failed').length
  const noContact = results.filter(r => !r.phone && !r.email).length

  let html = `<b>采集完成</b><br>`
  html += `✓ 成功: ${withPdf + pageOnly} 份 (${withPdf} 份含PDF, ${pageOnly} 份仅页面)`
  if (failed) html += `<br>✗ 失败: ${failed} 份`
  if (noContact) html += `<br><span style="color:orange">⚠ ${noContact} 份缺少联系方式</span>`

  resultDiv.innerHTML = html
}
```

- [ ] **Step 4: Disable buttons when server unreachable**

In health check failure handler, disable all action buttons:

```javascript
const setButtonsEnabled = (enabled) => {
  document.querySelectorAll('.action-btn').forEach(btn => {
    btn.disabled = !enabled
    btn.style.opacity = enabled ? '1' : '0.5'
  })
}

// In health check:
if (!serverOk) {
  statusDiv.textContent = '请先启动招聘助手'
  statusDiv.style.color = 'red'
  setButtonsEnabled(false)
}
```

- [ ] **Step 5: Commit**

```
git add chrome_extension/popup.js chrome_extension/popup.html chrome_extension/content.js
git commit -m "feat: add pre-flight checks and better feedback to Chrome extension"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] Start backend: `python launcher.py` — no import errors
- [ ] Start frontend: `cd frontend && npm run dev` — compiles without errors
- [ ] Load Chrome extension — no manifest errors
- [ ] Test each page manually:
  - Dashboard: health cards show, quick-start renders
  - Resumes: phone validation, save feedback flash, safer clear-all
  - Jobs: range validation, AI timeout, FK delete guard
  - Interviewers: format validation, duplicate check, FK delete guard
  - Interviews: past-time blocked, busy overlap warning, pause refresh in dialog
  - Notifications: safer clear-all, pagination
  - Settings: config guidance, connectivity test
- [ ] Network bar appears when backend stops
- [ ] Chrome extension: ping check works, batch summary shows categories
