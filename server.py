from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json

app = FastAPI()

state = {
    "cumulative": {"red": 0, "white": 0},
    "courts": {
        1: {"red": 0, "white": 0, "red_player": "", "white_player": "", "match_active": False, "match_index": 0},
        2: {"red": 0, "white": 0, "red_player": "", "white_player": "", "match_active": False, "match_index": 0},
        3: {"red": 0, "white": 0, "red_player": "", "white_player": "", "match_active": False, "match_index": 0},
        4: {"red": 0, "white": 0, "red_player": "", "white_player": "", "match_active": False, "match_index": 0},
    },
    "schedule": [],
    "history": [],
}

connected_clients: list[WebSocket] = []


def get_court_queue(court_id: int) -> list[dict]:
    result = []
    for r in sorted(state["schedule"], key=lambda x: x["round"]):
        entry = r.get("courts", {}).get(str(court_id))
        if entry:
            result.append({
                "round": r["round"],
                "time": r.get("time", ""),
                "red_player": entry.get("red_player", ""),
                "white_player": entry.get("white_player", ""),
            })
    return result


def compute_broadcast():
    totals = {"red": 0, "white": 0}
    courts_data = {}
    for court_id, court in sorted(state["courts"].items()):
        totals["red"] += court["red"]
        totals["white"] += court["white"]
        queue = get_court_queue(court_id)
        courts_data[str(court_id)] = {
            **court,
            "matches_total": len(queue),
            "queue": queue,
        }
    return {
        "type": "update",
        "cumulative": state["cumulative"].copy(),
        "totals": totals,
        "courts": courts_data,
        "schedule": state["schedule"],
        "history": state["history"],
    }


def compact_courts():
    ordered = [state["courts"][k] for k in sorted(state["courts"])]
    state["courts"] = {i + 1: v for i, v in enumerate(ordered)}


async def broadcast(message: dict):
    data = json.dumps(message)
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


@app.get("/")
async def root():
    return RedirectResponse(url="/static/display.html")

@app.get("/court")
async def court_page():
    return FileResponse("static/court.html")

@app.get("/admin")
async def admin_page():
    return FileResponse("static/admin.html")

@app.get("/schedule")
async def schedule_page():
    return FileResponse("static/schedule.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    await websocket.send_text(json.dumps(compute_broadcast()))
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            court_id = int(msg["court"])
            team = msg["team"]
            delta = int(msg["delta"])
            court = state["courts"].get(court_id)
            if court and court["match_active"] and team in ("red", "white"):
                court[team] = max(0, court[team] + delta)
            await broadcast(compute_broadcast())
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@app.post("/reset")
async def reset_all():
    for court in state["courts"].values():
        court["red"] = 0
        court["white"] = 0
    await broadcast(compute_broadcast())
    return {"status": "ok"}


@app.post("/reset/{court_id}")
async def reset_court(court_id: int):
    if court_id not in state["courts"]:
        raise HTTPException(status_code=404, detail="Court not found")
    state["courts"][court_id]["red"] = 0
    state["courts"][court_id]["white"] = 0
    await broadcast(compute_broadcast())
    return {"status": "ok"}


@app.post("/court/add")
async def add_court():
    new_id = max(state["courts"], default=0) + 1
    state["courts"][new_id] = {
        "red": 0, "white": 0, "red_player": "", "white_player": "",
        "match_active": False, "match_index": 0,
    }
    compact_courts()
    await broadcast(compute_broadcast())
    return {"status": "ok"}


@app.post("/court/remove/{court_id}")
async def remove_court(court_id: int):
    if court_id not in state["courts"]:
        raise HTTPException(status_code=404, detail="Court not found")
    del state["courts"][court_id]
    compact_courts()
    await broadcast(compute_broadcast())
    return {"status": "ok"}


class SchedulePayload(BaseModel):
    schedule: list[dict]


@app.post("/api/schedule")
async def set_schedule(payload: SchedulePayload):
    state["schedule"] = payload.schedule
    state["history"] = []
    state["cumulative"] = {"red": 0, "white": 0}
    if payload.schedule:
        n = len(payload.schedule[0].get("courts", {}))
        new_courts = {}
        for i in range(max(n, 1)):
            cid = i + 1
            # pre-load first match's players
            first = next(
                (r["courts"][str(cid)] for r in sorted(payload.schedule, key=lambda x: x["round"])
                 if str(cid) in r.get("courts", {})),
                {}
            )
            new_courts[cid] = {
                "red": 0, "white": 0,
                "red_player": first.get("red_player", ""),
                "white_player": first.get("white_player", ""),
                "match_active": False,
                "match_index": 0,
            }
        state["courts"] = new_courts
    await broadcast(compute_broadcast())
    return {"status": "ok", "rounds": len(payload.schedule)}


@app.get("/api/schedule")
async def get_schedule():
    return compute_broadcast()


class StartMatchPayload(BaseModel):
    red_player: str = ""
    white_player: str = ""


@app.post("/court/{court_id}/start")
async def start_match(court_id: int, payload: StartMatchPayload):
    if court_id not in state["courts"]:
        raise HTTPException(status_code=404, detail="Court not found")
    court = state["courts"][court_id]
    if court["match_active"]:
        raise HTTPException(status_code=400, detail="Match already active")
    court["red_player"] = payload.red_player or court["red_player"]
    court["white_player"] = payload.white_player or court["white_player"]
    court["match_active"] = True
    await broadcast(compute_broadcast())
    return {"status": "ok"}


@app.post("/court/{court_id}/end")
async def end_match(court_id: int):
    if court_id not in state["courts"]:
        raise HTTPException(status_code=404, detail="Court not found")
    court = state["courts"][court_id]
    if not court["match_active"]:
        raise HTTPException(status_code=400, detail="No active match")

    queue = get_court_queue(court_id)
    idx = court["match_index"]
    match_info = queue[idx] if idx < len(queue) else {}

    state["cumulative"]["red"] += court["red"]
    state["cumulative"]["white"] += court["white"]
    state["history"].append({
        "court": court_id,
        "round": match_info.get("round", idx + 1),
        "time": match_info.get("time", ""),
        "red_player": court["red_player"],
        "white_player": court["white_player"],
        "red": court["red"],
        "white": court["white"],
    })

    court["match_index"] = idx + 1
    court["red"] = 0
    court["white"] = 0
    court["match_active"] = False

    # pre-load next match players
    next_idx = court["match_index"]
    if next_idx < len(queue):
        court["red_player"] = queue[next_idx]["red_player"]
        court["white_player"] = queue[next_idx]["white_player"]
    else:
        court["red_player"] = ""
        court["white_player"] = ""

    await broadcast(compute_broadcast())
    return {"status": "ok"}


@app.get("/state")
async def get_state():
    return compute_broadcast()


app.mount("/static", StaticFiles(directory="static"), name="static")
