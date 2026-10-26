from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import uuid
import bcrypt
import jwt
import csv
import io
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict


# ------------------ Setup ------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_ALGORITHM = "HS256"
ACCESS_EXPIRE_MIN = 60 * 24  # 24h for convenience
JWT_SECRET = os.environ["JWT_SECRET"]

app = FastAPI(title="ChronoFlow Time Tracker")
api = APIRouter(prefix="/api")


# ------------------ Helpers ------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRE_MIN),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def serialize_user(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "email": doc["email"],
        "name": doc.get("name", ""),
        "role": doc.get("role", "employee"),
        "hourly_rate": doc.get("hourly_rate", 0) or 0,
        "created_at": doc.get("created_at"),
    }


def serialize_project(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "name": doc["name"],
        "color": doc.get("color", "#111827"),
        "client": doc.get("client", ""),
        "default_rate": doc.get("default_rate", 0) or 0,
        "created_at": doc.get("created_at"),
    }


def serialize_entry(doc: dict, user_map: Optional[dict] = None, project_map: Optional[dict] = None) -> dict:
    return {
        "id": doc["id"],
        "user_id": doc["user_id"],
        "user_name": (user_map or {}).get(doc["user_id"], doc.get("user_name", "")),
        "project_id": doc.get("project_id"),
        "project_name": (project_map or {}).get(doc.get("project_id"), doc.get("project_name", "")),
        "task": doc.get("task", ""),
        "notes": doc.get("notes", ""),
        "start_at": doc.get("start_at"),
        "end_at": doc.get("end_at"),
        "duration_minutes": doc.get("duration_minutes", 0),
        "status": doc.get("status", "pending"),
        "source": doc.get("source", "manual"),
        "billable": doc.get("billable", True),
        "created_at": doc.get("created_at"),
    }


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=ACCESS_EXPIRE_MIN * 60,
        path="/",
    )


# ------------------ Models ------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProjectIn(BaseModel):
    name: str
    color: Optional[str] = "#111827"
    client: Optional[str] = ""
    default_rate: Optional[float] = 0


class ProjectUpdateIn(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    client: Optional[str] = None
    default_rate: Optional[float] = None


class ManualEntryIn(BaseModel):
    project_id: Optional[str] = None
    task: Optional[str] = ""
    notes: Optional[str] = ""
    start_at: str
    end_at: str
    billable: Optional[bool] = True


class TimerStartIn(BaseModel):
    project_id: Optional[str] = None
    task: Optional[str] = ""
    notes: Optional[str] = ""
    billable: Optional[bool] = True


class UserUpdateIn(BaseModel):
    hourly_rate: Optional[float] = None
    name: Optional[str] = None


class EntryStatusIn(BaseModel):
    status: Literal["pending", "approved", "rejected"]


class BulkStatusIn(BaseModel):
    ids: List[str]
    status: Literal["pending", "approved", "rejected"]


class EntryUpdateIn(BaseModel):
    project_id: Optional[str] = None
    task: Optional[str] = None
    notes: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    billable: Optional[bool] = None


class InvoiceIn(BaseModel):
    scope: Literal["project", "client"]
    project_id: Optional[str] = None
    client: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    rate_override: Optional[float] = None
    use_employee_rate: Optional[bool] = False
    invoice_number: Optional[str] = None
    company_name: Optional[str] = "ChronoFlow"
    bill_to: Optional[str] = ""
    notes: Optional[str] = ""


# ------------------ Auth Endpoints ------------------
@api.post("/auth/register")
async def register(payload: RegisterIn, response: Response):
    email = payload.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name.strip(),
        "role": "employee",
        "created_at": iso(now_utc()),
    }
    await db.users.insert_one(user_doc)
    token = create_access_token(user_doc["id"], user_doc["email"], user_doc["role"])
    set_auth_cookie(response, token)
    return {"user": serialize_user(user_doc), "token": token}


@api.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"], user["email"], user["role"])
    set_auth_cookie(response, token)
    return {"user": serialize_user(user), "token": token}


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": serialize_user(user)}


# ------------------ Projects ------------------
@api.get("/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    docs = await db.projects.find({}).sort("created_at", -1).to_list(500)
    return [serialize_project(d) for d in docs]


@api.post("/projects")
async def create_project(payload: ProjectIn, user: dict = Depends(require_admin)):
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "color": payload.color or "#111827",
        "client": (payload.client or "").strip(),
        "default_rate": float(payload.default_rate or 0),
        "created_at": iso(now_utc()),
    }
    await db.projects.insert_one(doc)
    return serialize_project(doc)


@api.patch("/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdateIn, user: dict = Depends(require_admin)):
    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.color is not None:
        updates["color"] = payload.color
    if payload.client is not None:
        updates["client"] = payload.client.strip()
    if payload.default_rate is not None:
        updates["default_rate"] = float(payload.default_rate)
    if updates:
        res = await db.projects.update_one({"id": project_id}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(404, "Project not found")
    doc = await db.projects.find_one({"id": project_id})
    return serialize_project(doc)


@api.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(require_admin)):
    res = await db.projects.delete_one({"id": project_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Project not found")
    return {"ok": True}


# ------------------ Timer ------------------
@api.get("/timer/active")
async def active_timer(user: dict = Depends(get_current_user)):
    active = await db.time_entries.find_one({"user_id": user["id"], "end_at": None})
    if not active:
        return {"active": None}
    projects = {p["id"]: p["name"] async for p in db.projects.find({}, {"id": 1, "name": 1})}
    return {"active": serialize_entry(active, project_map=projects)}


@api.post("/timer/start")
async def start_timer(payload: TimerStartIn, user: dict = Depends(get_current_user)):
    existing = await db.time_entries.find_one({"user_id": user["id"], "end_at": None})
    if existing:
        raise HTTPException(400, "A timer is already running")
    project_name = ""
    if payload.project_id:
        p = await db.projects.find_one({"id": payload.project_id})
        if not p:
            raise HTTPException(400, "Invalid project")
        project_name = p["name"]
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_name": user.get("name", ""),
        "project_id": payload.project_id,
        "project_name": project_name,
        "task": (payload.task or "").strip(),
        "notes": (payload.notes or "").strip(),
        "start_at": iso(now_utc()),
        "end_at": None,
        "duration_minutes": 0,
        "status": "pending",
        "source": "timer",
        "billable": bool(payload.billable) if payload.billable is not None else True,
        "created_at": iso(now_utc()),
    }
    await db.time_entries.insert_one(doc)
    return serialize_entry(doc)


@api.post("/timer/stop")
async def stop_timer(user: dict = Depends(get_current_user)):
    active = await db.time_entries.find_one({"user_id": user["id"], "end_at": None})
    if not active:
        raise HTTPException(400, "No active timer")
    end = now_utc()
    start = parse_iso(active["start_at"])
    duration = max(0, int((end - start).total_seconds() // 60))
    await db.time_entries.update_one(
        {"id": active["id"]},
        {"$set": {"end_at": iso(end), "duration_minutes": duration}},
    )
    active["end_at"] = iso(end)
    active["duration_minutes"] = duration
    return serialize_entry(active)


# ------------------ Time Entries ------------------
@api.post("/entries")
async def create_manual_entry(payload: ManualEntryIn, user: dict = Depends(get_current_user)):
    start = parse_iso(payload.start_at)
    end = parse_iso(payload.end_at)
    if not start or not end or end <= start:
        raise HTTPException(400, "Invalid start/end time")
    project_name = ""
    if payload.project_id:
        p = await db.projects.find_one({"id": payload.project_id})
        if not p:
            raise HTTPException(400, "Invalid project")
        project_name = p["name"]
    duration = int((end - start).total_seconds() // 60)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_name": user.get("name", ""),
        "project_id": payload.project_id,
        "project_name": project_name,
        "task": (payload.task or "").strip(),
        "notes": (payload.notes or "").strip(),
        "start_at": iso(start),
        "end_at": iso(end),
        "duration_minutes": duration,
        "status": "pending",
        "source": "manual",
        "billable": bool(payload.billable) if payload.billable is not None else True,
        "created_at": iso(now_utc()),
    }
    await db.time_entries.insert_one(doc)
    return serialize_entry(doc)


@api.get("/entries")
async def list_entries(
    user: dict = Depends(get_current_user),
    scope: str = Query("mine"),  # mine | all
    start: Optional[str] = None,
    end: Optional[str] = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = None,
):
    query: dict = {}
    if scope == "all":
        if user.get("role") != "admin":
            raise HTTPException(403, "Admin only")
        if user_id:
            query["user_id"] = user_id
    else:
        query["user_id"] = user["id"]
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    if start:
        query.setdefault("start_at", {})["$gte"] = start
    if end:
        query.setdefault("start_at", {})["$lte"] = end

    docs = await db.time_entries.find(query).sort("start_at", -1).to_list(2000)
    project_ids = {d["project_id"] for d in docs if d.get("project_id")}
    user_ids = {d["user_id"] for d in docs if d.get("user_id")}
    project_map = {p["id"]: p["name"] async for p in db.projects.find({"id": {"$in": list(project_ids)}}, {"id": 1, "name": 1})} if project_ids else {}
    user_map = {u["id"]: u.get("name", "") async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"id": 1, "name": 1})} if user_ids else {}
    return [serialize_entry(d, user_map=user_map, project_map=project_map) for d in docs]


@api.patch("/entries/{entry_id}")
async def update_entry(entry_id: str, payload: EntryUpdateIn, user: dict = Depends(get_current_user)):
    entry = await db.time_entries.find_one({"id": entry_id})
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    updates = {}
    if payload.task is not None:
        updates["task"] = payload.task.strip()
    if payload.notes is not None:
        updates["notes"] = payload.notes.strip()
    if payload.billable is not None:
        updates["billable"] = bool(payload.billable)
    if payload.project_id is not None:
        if payload.project_id == "":
            updates["project_id"] = None
            updates["project_name"] = ""
        else:
            p = await db.projects.find_one({"id": payload.project_id})
            if not p:
                raise HTTPException(400, "Invalid project")
            updates["project_id"] = payload.project_id
            updates["project_name"] = p["name"]
    if payload.start_at or payload.end_at:
        s = parse_iso(payload.start_at) if payload.start_at else parse_iso(entry["start_at"])
        e = parse_iso(payload.end_at) if payload.end_at else parse_iso(entry.get("end_at"))
        if s and e and e > s:
            updates["start_at"] = iso(s)
            updates["end_at"] = iso(e)
            updates["duration_minutes"] = int((e - s).total_seconds() // 60)
    if updates:
        await db.time_entries.update_one({"id": entry_id}, {"$set": updates})
    updated = await db.time_entries.find_one({"id": entry_id})
    return serialize_entry(updated)


@api.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    entry = await db.time_entries.find_one({"id": entry_id})
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    await db.time_entries.delete_one({"id": entry_id})
    return {"ok": True}


@api.patch("/entries/{entry_id}/status")
async def change_status(entry_id: str, payload: EntryStatusIn, user: dict = Depends(require_admin)):
    res = await db.time_entries.update_one({"id": entry_id}, {"$set": {"status": payload.status}})
    if res.matched_count == 0:
        raise HTTPException(404, "Entry not found")
    updated = await db.time_entries.find_one({"id": entry_id})
    return serialize_entry(updated)


@api.post("/entries/bulk-status")
async def bulk_change_status(payload: BulkStatusIn, user: dict = Depends(require_admin)):
    if not payload.ids:
        return {"updated": 0}
    res = await db.time_entries.update_many(
        {"id": {"$in": payload.ids}},
        {"$set": {"status": payload.status}},
    )
    return {"updated": res.modified_count}



# ------------------ Dashboard ------------------
@api.get("/dashboard/me")
async def dashboard_me(user: dict = Depends(get_current_user)):
    now = now_utc()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    entries = await db.time_entries.find(
        {"user_id": user["id"], "end_at": {"$ne": None}}
    ).sort("start_at", -1).to_list(2000)

    def sum_since(since: datetime) -> int:
        total = 0
        for e in entries:
            s = parse_iso(e["start_at"])
            if s and s >= since:
                total += e.get("duration_minutes", 0)
        return total

    # Past 7 days bar chart
    chart = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day + timedelta(days=1)
        mins = 0
        for e in entries:
            s = parse_iso(e["start_at"])
            if s and day <= s < next_day:
                mins += e.get("duration_minutes", 0)
        chart.append({"day": day.strftime("%a"), "date": day.strftime("%Y-%m-%d"), "minutes": mins})

    recent_entries = entries[:8]
    project_ids = {e.get("project_id") for e in recent_entries if e.get("project_id")}
    project_map = {p["id"]: p["name"] async for p in db.projects.find({"id": {"$in": list(project_ids)}}, {"id": 1, "name": 1})} if project_ids else {}
    recent = [serialize_entry(e, project_map=project_map) for e in recent_entries]

    return {
        "today_minutes": sum_since(today_start),
        "week_minutes": sum_since(week_start),
        "month_minutes": sum_since(month_start),
        "total_entries": len(entries),
        "chart": chart,
        "recent": recent,
    }


@api.get("/dashboard/admin")
async def dashboard_admin(user: dict = Depends(require_admin)):
    now = now_utc()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    users = await db.users.find({}).to_list(1000)
    user_map = {u["id"]: u.get("name", "") for u in users}
    employees = [serialize_user(u) for u in users]

    # Only fetch last 90 days for dashboard stats — historical data not needed for live KPIs
    cutoff = (now - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
    entries = await db.time_entries.find({
        "end_at": {"$ne": None},
        "start_at": {"$gte": iso(cutoff)},
    }).to_list(5000)

    total_minutes_week = 0
    per_user_week: dict = {}
    per_project: dict = {}
    pending_count = 0

    for e in entries:
        s = parse_iso(e["start_at"])
        mins = e.get("duration_minutes", 0)
        if s and s >= week_start:
            total_minutes_week += mins
            per_user_week[e["user_id"]] = per_user_week.get(e["user_id"], 0) + mins
        pname = e.get("project_name") or "Unassigned"
        per_project[pname] = per_project.get(pname, 0) + mins
        if e.get("status") == "pending":
            pending_count += 1

    top = sorted(
        [{"user_id": uid, "name": user_map.get(uid, ""), "minutes": m} for uid, m in per_user_week.items()],
        key=lambda x: x["minutes"], reverse=True
    )[:5]

    # 7-day org chart
    chart = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day + timedelta(days=1)
        mins = 0
        for e in entries:
            s = parse_iso(e["start_at"])
            if s and day <= s < next_day:
                mins += e.get("duration_minutes", 0)
        chart.append({"day": day.strftime("%a"), "date": day.strftime("%Y-%m-%d"), "minutes": mins})

    by_project = [{"project": k, "minutes": v} for k, v in per_project.items()]
    by_project.sort(key=lambda x: x["minutes"], reverse=True)

    return {
        "total_employees": len([u for u in users if u.get("role") != "admin"]) + sum(1 for u in users if u.get("role") == "admin"),
        "active_today_count": len({e["user_id"] for e in entries if parse_iso(e["start_at"]) and parse_iso(e["start_at"]) >= now.replace(hour=0, minute=0, second=0, microsecond=0)}),
        "pending_count": pending_count,
        "week_minutes": total_minutes_week,
        "top_performers": top,
        "chart": chart,
        "by_project": by_project[:8],
        "employees": employees,
    }


@api.get("/users")
async def list_users(user: dict = Depends(require_admin)):
    docs = await db.users.find({}).sort("created_at", -1).to_list(1000)
    return [serialize_user(d) for d in docs]


@api.patch("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdateIn, user: dict = Depends(require_admin)):
    updates = {}
    if payload.hourly_rate is not None:
        updates["hourly_rate"] = float(payload.hourly_rate)
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if updates:
        res = await db.users.update_one({"id": user_id}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(404, "User not found")
    doc = await db.users.find_one({"id": user_id})
    return serialize_user(doc)


# ------------------ Clients ------------------
@api.get("/clients")
async def list_clients(user: dict = Depends(get_current_user)):
    projects = await db.projects.find({}).to_list(500)
    clients = {}
    for p in projects:
        c = (p.get("client") or "").strip()
        if not c:
            continue
        clients.setdefault(c, []).append({"id": p["id"], "name": p["name"]})
    return [{"name": c, "projects": v} for c, v in clients.items()]


# ------------------ CSV Export ------------------
@api.get("/export/csv")
async def export_csv(
    user: dict = Depends(get_current_user),
    scope: str = Query("mine"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    query: dict = {"end_at": {"$ne": None}}
    if scope == "all":
        if user.get("role") != "admin":
            raise HTTPException(403, "Admin only")
    else:
        query["user_id"] = user["id"]
    if start:
        query.setdefault("start_at", {})["$gte"] = start
    if end:
        query.setdefault("start_at", {})["$lte"] = end

    docs = await db.time_entries.find(query).sort("start_at", -1).to_list(5000)
    user_ids = {d["user_id"] for d in docs if d.get("user_id")}
    user_map = {u["id"]: u.get("name", "") async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"id": 1, "name": 1})} if user_ids else {}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Employee", "Project", "Task", "Start", "End", "Hours", "Status", "Notes"])
    for d in docs:
        s = parse_iso(d["start_at"])
        e = parse_iso(d.get("end_at"))
        hours = round((d.get("duration_minutes", 0)) / 60, 2)
        writer.writerow([
            s.strftime("%Y-%m-%d") if s else "",
            user_map.get(d["user_id"], d.get("user_name", "")),
            d.get("project_name", ""),
            d.get("task", ""),
            s.strftime("%H:%M") if s else "",
            e.strftime("%H:%M") if e else "",
            hours,
            d.get("status", ""),
            (d.get("notes", "") or "").replace("\n", " "),
        ])

    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=timesheet.csv"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


# ------------------ Invoice ------------------
def _generate_invoice_pdf(meta: dict, line_items: list, totals: dict) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=28, leading=32, textColor=colors.HexColor("#111827"))
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#6b7280"),
                           leading=10, spaceAfter=2)
    value = ParagraphStyle("value", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#111827"), leading=12)

    elements = []
    # Header
    header = Table([[
        Paragraph(f"<b>{meta['company_name']}</b>", h1),
        Paragraph(
            f"<font size=8 color='#6b7280'>INVOICE</font><br/><font size=14 color='#111827'><b>#{meta['invoice_number']}</b></font><br/>"
            f"<font size=8 color='#6b7280'>Issued {meta['issued']}</font>", value
        ),
    ]], colWidths=[3.6 * inch, 3.6 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    elements.append(header)
    elements.append(Spacer(1, 0.25 * inch))

    # Bill to + period
    info = Table([[
        Paragraph("<b>BILL TO</b>", label), Paragraph("<b>PERIOD</b>", label), Paragraph("<b>SCOPE</b>", label),
    ], [
        Paragraph(meta["bill_to"] or "—", value),
        Paragraph(meta["period"], value),
        Paragraph(meta["scope_label"], value),
    ]], colWidths=[2.4 * inch, 2.4 * inch, 2.4 * inch])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
    ]))
    elements.append(info)
    elements.append(Spacer(1, 0.3 * inch))

    # Line items
    data = [["Date", "Employee", "Project / Task", "Hours", "Rate", "Amount"]]
    for li in line_items:
        data.append([li["date"], li["employee"], f"{li['project']} · {li['task']}", f"{li['hours']:.2f}",
                     f"${li['rate']:.2f}", f"${li['amount']:.2f}"])
    table = Table(data, colWidths=[0.8 * inch, 1.2 * inch, 2.6 * inch, 0.7 * inch, 0.8 * inch, 1.0 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ffffff"), colors.HexColor("#f9fafb")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.3 * inch))

    # Totals
    totals_table = Table([
        ["Total hours", f"{totals['hours']:.2f}"],
        ["Subtotal", f"${totals['subtotal']:.2f}"],
        ["Total due", f"${totals['total']:.2f}"],
    ], colWidths=[5.2 * inch, 1.9 * inch], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, 1), 10),
        ("FONTSIZE", (0, 2), (-1, 2), 13),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 1, colors.HexColor("#111827")),
        ("TOPPADDING", (0, 2), (-1, 2), 8),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 8),
    ]))
    elements.append(totals_table)

    if meta.get("notes"):
        elements.append(Spacer(1, 0.4 * inch))
        elements.append(Paragraph("<b>NOTES</b>", label))
        elements.append(Paragraph(meta["notes"].replace("\n", "<br/>"), value))

    elements.append(Spacer(1, 0.6 * inch))
    elements.append(Paragraph(
        "<font size=8 color='#6b7280'>Generated by ChronoFlow · Time tracked, billable, paid.</font>", value))

    doc.build(elements)
    buf.seek(0)
    return buf.read()


@api.post("/invoices/preview")
async def invoice_preview(payload: InvoiceIn, user: dict = Depends(require_admin)):
    return await _compute_invoice(payload)


@api.post("/invoices/generate")
async def invoice_generate(payload: InvoiceIn, user: dict = Depends(require_admin)):
    data = await _compute_invoice(payload)
    pdf_bytes = _generate_invoice_pdf(data["meta"], data["line_items"], data["totals"])
    filename = f"invoice_{data['meta']['invoice_number']}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


async def _compute_invoice(payload: InvoiceIn) -> dict:
    # Resolve target projects only — scope-specific query
    if payload.scope == "project":
        if not payload.project_id:
            raise HTTPException(400, "Invalid project_id")
        target_projects = await db.projects.find({"id": payload.project_id}).to_list(1)
        if not target_projects:
            raise HTTPException(400, "Invalid project_id")
        scope_label = f"Project · {target_projects[0]['name']}"
        client_name = target_projects[0].get("client") or ""
    else:
        if not payload.client:
            raise HTTPException(400, "client required for client scope")
        target_projects = await db.projects.find(
            {"client": {"$regex": f"^{payload.client.strip()}$", "$options": "i"}}
        ).to_list(200)
        if not target_projects:
            raise HTTPException(400, "No projects for that client")
        scope_label = f"Client · {payload.client}"
        client_name = payload.client

    p_map = {p["id"]: p for p in target_projects}
    target_project_ids = list(p_map.keys())

    # Fetch approved + billable entries in range
    query: dict = {
        "project_id": {"$in": target_project_ids},
        "status": "approved",
        "billable": True,
        "end_at": {"$ne": None},
    }
    if payload.start:
        query["start_at"] = {"$gte": payload.start}
    if payload.end:
        query.setdefault("start_at", {})["$lte"] = payload.end

    entries = await db.time_entries.find(query).sort("start_at", 1).to_list(5000)
    user_ids = {e["user_id"] for e in entries if e.get("user_id")}
    users = await db.users.find({"id": {"$in": list(user_ids)}}).to_list(len(user_ids) or 1) if user_ids else []
    u_map = {u["id"]: u for u in users}

    line_items = []
    subtotal = 0.0
    total_hours = 0.0
    for e in entries:
        hours = (e.get("duration_minutes", 0) or 0) / 60.0
        if hours <= 0:
            continue
        # Determine rate: override > employee rate > project default
        proj = p_map.get(e.get("project_id"), {})
        usr = u_map.get(e.get("user_id"), {})
        if payload.rate_override and payload.rate_override > 0:
            rate = float(payload.rate_override)
        elif payload.use_employee_rate and float(usr.get("hourly_rate", 0) or 0) > 0:
            rate = float(usr.get("hourly_rate", 0))
        else:
            rate = float(proj.get("default_rate", 0) or 0)
            if rate == 0 and float(usr.get("hourly_rate", 0) or 0) > 0:
                rate = float(usr.get("hourly_rate", 0))
        amount = hours * rate
        subtotal += amount
        total_hours += hours
        s = parse_iso(e["start_at"])
        line_items.append({
            "date": s.strftime("%Y-%m-%d") if s else "",
            "employee": usr.get("name", e.get("user_name", "")),
            "project": proj.get("name", e.get("project_name", "")),
            "task": e.get("task", "") or "—",
            "hours": round(hours, 2),
            "rate": round(rate, 2),
            "amount": round(amount, 2),
        })

    now = now_utc()
    inv_no = payload.invoice_number or now.strftime("INV-%Y%m%d-%H%M")
    period_label = "All time"
    if payload.start or payload.end:
        s_label = parse_iso(payload.start).strftime("%Y-%m-%d") if payload.start else "…"
        e_label = parse_iso(payload.end).strftime("%Y-%m-%d") if payload.end else "…"
        period_label = f"{s_label} → {e_label}"

    return {
        "meta": {
            "company_name": payload.company_name or "ChronoFlow",
            "bill_to": payload.bill_to or client_name or "—",
            "invoice_number": inv_no,
            "issued": now.strftime("%Y-%m-%d"),
            "period": period_label,
            "scope_label": scope_label,
            "notes": payload.notes or "",
        },
        "line_items": line_items,
        "totals": {
            "hours": round(total_hours, 2),
            "subtotal": round(subtotal, 2),
            "total": round(subtotal, 2),
        },
    }


# ------------------ Mount + CORS ------------------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost(:\d+)?|.*\.preview\.emergentagent\.com|.*\.emergentagent\.com|.*\.emergent\.host)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ------------------ Startup ------------------
@app.on_event("startup")
async def on_startup():
    await db.users.create_index("email", unique=True)
    await db.time_entries.create_index("user_id")
    await db.time_entries.create_index("start_at")
    await db.projects.create_index("name")

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin",
            "role": "admin",
            "created_at": iso(now_utc()),
        })
        logger.info("Seeded admin user: %s", admin_email)
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password), "role": "admin"}},
        )
        logger.info("Updated admin password")

    # Seed sample employee + projects if none
    if not await db.users.find_one({"email": "employee@chronoflow.com"}):
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": "employee@chronoflow.com",
            "password_hash": hash_password("Employee@123"),
            "name": "Sample Employee",
            "role": "employee",
            "created_at": iso(now_utc()),
        })
    if await db.projects.count_documents({}) == 0:
        await db.projects.insert_many([
            {"id": str(uuid.uuid4()), "name": "Internal Operations", "color": "#111827", "client": "Internal", "created_at": iso(now_utc())},
            {"id": str(uuid.uuid4()), "name": "Client Acme", "color": "#002fa7", "client": "Acme Corp", "created_at": iso(now_utc())},
            {"id": str(uuid.uuid4()), "name": "Product R&D", "color": "#34c759", "client": "Internal", "created_at": iso(now_utc())},
        ])


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
