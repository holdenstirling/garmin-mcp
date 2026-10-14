"""HTTP routes for plan imports (``planimport``), for a linked coach with ``can_edit_plan``
(``/app/api/coach/athletes/{athlete_id}/plan/import...``) and for the athlete themself
(``/app/api/plan/import...``). Built by ``webapp.build_app_routes`` from its own helpers so
the same guards apply: ``plan_api`` (session, Host, Origin + JSON on mutating calls, coach
accounts limited to coach paths) and, for the raw-body file upload, the same checks as chat
attachments.

    GET  .../plan/import               status: undo available?, last import, file reads left
    GET  .../plan/import/draft         current plan as grid rows + week templates
    GET  .../plan/import/template.csv  the CSV template
    POST .../plan/import/rows          {rows, name?, source?} -> preview
    POST .../plan/import/file?name=&start=&via=   raw file -> preview
    POST .../plan/import/{id}/apply    install the previewed plan (athlete notified)
    POST .../plan/import/undo          put the previous plan back (7 days)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .attachments import MAX_UPLOAD
from .logs import log_event
from .planbuilder import PlanError
from .planimport import (
    AI_PER_DAY, INTENSITIES, SPORTS, ImportService, PlanImportError, csv_template, detect,
    extract, next_monday, plan_rows, week_templates,
)

logger = logging.getLogger(__name__)
MAX_ROWS_BODY = 512 * 1024
SOURCE_LABEL = {"csv": "CSV", "xlsx": "Excel", "ics": "calendar file", "pdf": "PDF",
                "image": "photo", "text": "text"}


def make_routes(*, importer: ImportService, plans: Any, coach: Any, links: Any, auth: Any,
                settings: Any, host_ok: Callable[[Request], bool],
                plan_api: Callable[..., Callable[[Request], Awaitable[Response]]],
                plan_call: Callable[[Callable[[], Any]], Awaitable[Any]],
                user_error: type[Exception], public_plan: Callable[..., Any],
                notify: Callable[..., None], coach_chat: Any,
                structured: Callable[..., Awaitable[dict[str, Any]]] | None,
                now: Callable[[str], datetime]) -> list[Route]:

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def who(request: Request, user_id: str, *, edit: bool = True) -> tuple[str, str, dict[str, Any] | None]:
        """(athlete id, role, coach link). Coach routes check the link (and edit access)."""
        aid = request.path_params.get("athlete_id")
        if aid is None:
            return user_id, "athlete", None
        link = links.require(user_id, str(aid), perm="can_edit_plan" if edit else None)
        return str(aid), "coach", link

    def actor_name(user_id: str, link: dict[str, Any] | None) -> str:
        name = (auth.profile(user_id).get("name") or "").strip()
        if name:
            return name
        return link["email"].split("@")[0] if link else "You"

    def start_param(request: Request, aid: str) -> date:
        s = request.query_params.get("start")
        if s:
            try:
                return date.fromisoformat(s)
            except ValueError:
                raise user_error("start must be YYYY-MM-DD") from None
        return next_monday(plans.today(aid))

    async def status(request: Request, user_id: str) -> Response:
        def run() -> dict[str, Any]:
            aid, role, link = who(request, user_id, edit=False)
            today = plans.today(aid)
            return importer.status(aid) | {
                "can_edit": role == "athlete" or bool((link or {}).get("can_edit_plan")),
                "ai_left": importer.ai_left(user_id, today) if structured else 0,
                "ai_per_day": AI_PER_DAY if structured else 0,
                "next_monday": next_monday(today).isoformat(), "today": today.isoformat()}
        return JSONResponse(await plan_call(run))

    async def draft(request: Request, user_id: str) -> Response:
        def run() -> dict[str, Any]:
            aid, _, _ = who(request, user_id)
            today = plans.today(aid)
            return {"rows": plan_rows(plans.get(aid), today),
                    "templates": week_templates(coach.athlete(aid), coach.active_goal(aid)),
                    "sports": [s for s in SPORTS if s != "rest"], "intensities": list(INTENSITIES),
                    "next_monday": next_monday(today).isoformat(), "today": today.isoformat()}
        return JSONResponse(await plan_call(run))

    async def template(request: Request, user_id: str) -> Response:
        aid, _, _ = await plan_call(lambda: who(request, user_id, edit=False))
        return Response(csv_template(plans.today(aid)), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="rabbit-plan-template.csv"'})

    async def rows(request: Request, user_id: str) -> Response:
        raw = await request.body()
        if len(raw) > MAX_ROWS_BODY:
            raise user_error("That plan is too large to send at once.", 413)
        body = json.loads(raw or b"null")
        if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            aid, _, _ = who(request, user_id)
            src = body.get("source") if body.get("source") in ("grid", "template") else "grid"
            return importer.preview(aid, body["rows"], actor=user_id, source="Rabbit" if src == "grid" else "template",
                                    name=body.get("name") if isinstance(body.get("name"), str) else None)
        return JSONResponse({"preview": await plan_call(run)})

    async def file_preview(request: Request, user_id: str, data: bytes) -> dict[str, Any]:
        aid, _, _ = await plan_call(lambda: who(request, user_id))
        name = (request.query_params.get("name") or "plan")[:120]
        via_tp = request.query_params.get("via") == "trainingpeaks"
        start = start_param(request, aid)
        today = plans.today(aid)
        kind = await plan_call(lambda: detect(data, name))
        parsed = await plan_call(lambda: importer.rows_from_file(kind, data, tz=now(aid).tzinfo))
        label = ("TrainingPeaks " if via_tp else "") + SOURCE_LABEL.get(kind, kind)
        pname = name.rsplit(".", 1)[0][:80]
        if parsed is None:
            if structured is None:
                raise user_error("Reading PDFs and photos isn't available on this server. "
                                 "Use the CSV template instead.")
            await plan_call(lambda: importer.take_ai(user_id, today))
            try:
                got, warns, mname = await extract(structured, kind, data, name, today=today, start=start)
            except PlanError as e:
                raise user_error(str(e)) from None
            except Exception as e:  # model down, rate limited, refused
                log_event(logger, logging.WARNING, "plan_import_model_failed", error=type(e).__name__)
                raise user_error("Rabbit couldn't read that file just now. Try again in a minute, "
                                 "or use the CSV template.", 502) from None
            label += " (read by Rabbit)"
            pname = mname or pname
            warns = ["Rabbit read this file: check the sessions before you apply."] + warns
        else:
            got, warns = parsed
        return await plan_call(lambda: importer.preview(aid, got, actor=user_id, source=label,
                                                        name=pname, start=start, warnings=warns))

    async def apply(request: Request, user_id: str) -> Response:
        iid = request.path_params["import_id"]

        def run() -> tuple[dict[str, Any], dict[str, Any], str, str, dict[str, Any] | None]:
            aid, role, link = who(request, user_id)
            name = actor_name(user_id, link)
            plan, summary = importer.apply(aid, iid, actor=user_id, actor_name=name, actor_role=role)
            return plan, summary, aid, role, link
        plan, summary, aid, role, link = await plan_call(run)
        if role == "coach" and link is not None:
            first = summary["by_name"].split(" ")[0]
            starts = date.fromisoformat(summary["first_day"])
            text = (f"{first} loaded your plan: {summary['weeks']} week{'s' if summary['weeks'] != 1 else ''}, "
                    f"starts {starts:%a %b %-d}. Open Plan to see what changed.")
            try:
                t = coach_chat.open_thread(aid, link["email"])
                coach_chat.post(aid, t["id"], sender="coach", text=text, coach=link["email"])
            except Exception as e:  # the plan is in; the message is best effort
                log_event(logger, logging.WARNING, "plan_import_message_failed", error=type(e).__name__)
            notify(aid, summary["by_name"] or "Your coach", text)
        log_event(logger, logging.INFO, "plan_imported", user_id=aid, role=role, weeks=summary["weeks"],
                  sessions=summary["sessions"], source=summary["source"])
        return JSONResponse({"plan": public_plan(plan, plans.today(aid)), "summary": summary})

    async def undo(request: Request, user_id: str) -> Response:
        def run() -> tuple[Any, str, str, dict[str, Any] | None]:
            aid, role, link = who(request, user_id)
            # The athlete may always undo a coach's import of their own plan.
            restored = importer.undo(aid, actor=user_id, may_undo_others=role == "athlete")
            return restored, aid, role, link
        restored, aid, role, link = await plan_call(run)
        if role == "coach" and link is not None:
            name = actor_name(user_id, link).split(" ")[0]
            text = f"{name} undid the plan they loaded; your previous plan is back."
            try:
                t = coach_chat.open_thread(aid, link["email"])
                coach_chat.post(aid, t["id"], sender="coach", text=text, coach=link["email"])
            except Exception as e:
                log_event(logger, logging.WARNING, "plan_import_message_failed", error=type(e).__name__)
            notify(aid, name or "Your coach", text)
        return JSONResponse({"plan": public_plan(plans.get(aid), plans.today(aid)), "restored": restored is not None})

    async def upload(request: Request) -> Response:
        """Raw-body file upload. Same guards as _api, minus the JSON content type."""
        if not host_ok(request):
            return err(400, "bad host")
        user_id = auth.user_for(request)
        if user_id is None:
            return err(401, "not signed in")
        if request.headers.get("origin", "") != settings.public_base_url:
            return err(403, "bad origin")
        if user_id.startswith("coach_") and "athlete_id" not in request.path_params:
            return err(403, "Coach accounts can only use the coach view.")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            return err(400, "bad request")
        if declared > MAX_UPLOAD:
            return err(413, "That file is too large (max 10 MB).")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > MAX_UPLOAD:
                return err(413, "That file is too large (max 10 MB).")
        try:
            pv = await file_preview(request, user_id, bytes(buf))
        except user_error as e:  # type: ignore[misc]
            return err(getattr(e, "status", 400), getattr(e, "message", str(e)))
        except PlanImportError as e:
            return err(400, str(e))
        except Exception as e:
            log_event(logger, logging.ERROR, "app_unexpected_error", path=request.url.path,
                      error=type(e).__name__)
            return err(500, f"Internal error ({type(e).__name__})")
        resp = JSONResponse({"preview": pv}, status_code=201)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    out: list[Route] = []
    for base in ("/app/api/coach/athletes/{athlete_id}/plan/import", "/app/api/plan/import"):
        out += [
            Route(base, plan_api(status, mutating=False), methods=["GET"]),
            Route(f"{base}/draft", plan_api(draft, mutating=False), methods=["GET"]),
            Route(f"{base}/template.csv", plan_api(template, mutating=False), methods=["GET"]),
            Route(f"{base}/rows", plan_api(rows, mutating=True), methods=["POST"]),
            Route(f"{base}/file", upload, methods=["POST"]),
            Route(f"{base}/undo", plan_api(undo, mutating=True), methods=["POST"]),
            Route(base + "/{import_id}/apply", plan_api(apply, mutating=True), methods=["POST"]),
        ]
    return out


__all__ = ["make_routes"]
