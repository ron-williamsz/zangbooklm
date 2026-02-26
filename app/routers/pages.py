"""Rotas de páginas HTML."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["Pages"])


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/notebooks/{session_id}", response_class=HTMLResponse)
async def notebook_page(request: Request, session_id: int):
    return templates.TemplateResponse("notebook.html", {"request": request, "session_id": session_id})


@router.get("/admin/skills", response_class=HTMLResponse)
async def skills_admin_page(request: Request):
    return templates.TemplateResponse("admin/skills.html", {"request": request})


@router.get("/admin/skills/new", response_class=HTMLResponse)
async def skill_new_page(request: Request):
    return templates.TemplateResponse("admin/skill_editor.html", {"request": request, "skill_id": 0})


@router.get("/admin/skills/{skill_id}", response_class=HTMLResponse)
async def skill_editor_page(request: Request, skill_id: int):
    return templates.TemplateResponse("admin/skill_editor.html", {"request": request, "skill_id": skill_id})
