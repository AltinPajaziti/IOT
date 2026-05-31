import os

"""
AI chatbot endpoint for the TrafficWatch assistant.

POST /api/chat
  Body: {
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "snapshots": [...]   ← optional; live data sent by the Angular frontend
  }
  Returns: { "reply": "...", "source": "ai"|"local" }
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Any

router = APIRouter(prefix="/api/chat", tags=["chat"])

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

ROUTE_DESCRIPTIONS: dict[str, str] = {
    "pejton":    "Rr. Agim Ramadani (Pejton) — main arterial road in west Prishtina",
    "pejton2":   "Rr. Agim Ramadani secondary segment (Pejton2)",
    "tokbashqe": "Tokbashqe corridor — connects central Prishtina to southern districts",
}

DENSITY_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatTurn]
    snapshots: list[dict[str, Any]] = []   # live data pushed from Angular


# ── Collect live stats: prefer client-supplied snapshots, fall back to workers ─

def _get_live_stats(request: Request, client_snapshots: list[dict]) -> list[dict]:
    # Use snapshots sent by the Angular frontend (always fresh from .NET API)
    if client_snapshots:
        return _normalize_snapshots(client_snapshots)

    # Fallback: try in-memory YOLO workers on this server
    try:
        mgr = request.app.state.camera_manager
        stats = []
        for worker in mgr.get_all_workers():
            s = worker.get_latest_stats()
            if s and isinstance(s, dict) and "camera_id" in s:
                stats.append(s)
        return stats
    except Exception:
        return []


def _normalize_snapshots(snaps: list[dict]) -> list[dict]:
    """Convert .NET API snapshot shape → internal stats dict shape."""
    out = []
    for s in snaps:
        camera_id   = s.get("cameraId") or s.get("camera_id", "")
        camera_name = s.get("cameraName") or s.get("camera_name", camera_id)
        density     = s.get("density", "Low")
        total       = s.get("totalVehicles") or s.get("total_vehicles", 0)
        cars        = s.get("cars") or s.get("counts", {}).get("car", 0)
        trucks      = s.get("trucks") or s.get("counts", {}).get("truck", 0)
        buses       = s.get("buses") or s.get("counts", {}).get("bus", 0)
        motos       = s.get("motorcycles") or s.get("counts", {}).get("motorcycle", 0)
        fps         = s.get("fps", 0.0)
        location    = s.get("location", "")
        out.append({
            "camera_id":   camera_id,
            "camera_name": camera_name,
            "density":     density,
            "total_vehicles": total,
            "counts": {"car": cars, "truck": trucks, "bus": buses, "motorcycle": motos},
            "fps":     fps,
            "location": location,
        })
    return out


# ── Local rule-based fallback (no OpenAI required) ────────────────────────────

def _local_answer(question: str, stats: list[dict]) -> str:
    if not stats:
        return (
            "I don't have live traffic data yet — the YOLO workers may still be starting up. "
            "Please try again in a moment."
        )

    q = question.lower()

    def line(s: dict) -> str:
        c = s.get("counts", {})
        emoji = DENSITY_EMOJI.get(s["density"], "⚪")
        return (
            f"{emoji} **{s['camera_name']}** — {s['density']} · "
            f"{s['total_vehicles']} vehicles "
            f"(🚗{c.get('car',0)} 🚛{c.get('truck',0)} "
            f"🚌{c.get('bus',0)} 🏍️{c.get('motorcycle',0)})"
        )

    total = sum(s["total_vehicles"] for s in stats)
    busiest  = max(stats, key=lambda s: s["total_vehicles"])
    clearest = min(stats, key=lambda s: s["total_vehicles"])
    high   = [s for s in stats if s["density"] == "High"]
    medium = [s for s in stats if s["density"] == "Medium"]
    low    = [s for s in stats if s["density"] == "Low"]

    # Summary / overview
    if any(w in q for w in ["summar", "overview", "status", "all route", "situation", "overall", "report"]):
        lines = ["**Current Prishtina traffic summary:**", ""]
        lines += [line(s) for s in stats]
        lines.append(f"\n📊 Total across all routes: **{total} vehicles**")
        return "\n".join(lines)

    # Busiest route
    if any(w in q for w in ["most traffic", "busiest", "heaviest", "worst", "highest"]):
        return (
            f"The busiest route right now is {line(busiest)}, "
            f"located at {ROUTE_DESCRIPTIONS.get(busiest['camera_id'], busiest['camera_id'])}."
        )

    # Clearest route
    if any(w in q for w in ["clear", "least traffic", "best route", "free", "empty", "quiet", "avoid"]):
        if low:
            return (
                f"The clearest route is {line(clearest)} — "
                f"traffic is flowing freely."
            )
        return f"No fully clear routes right now. Least congested: {line(clearest)}."

    # Congestion / alerts
    if any(w in q for w in ["congest", "block", "slow", "alert", "problem", "bad", "heavy"]):
        if not high and not medium:
            return "✅ No congestion alerts right now — all monitored routes are clear!"
        parts = []
        for s in high:
            parts.append(f"🔴 **{s['camera_name']}** is heavily congested ({s['total_vehicles']} vehicles) — avoid if possible.")
        for s in medium:
            parts.append(f"🟡 **{s['camera_name']}** has moderate traffic ({s['total_vehicles']} vehicles).")
        return "\n".join(parts)

    # Total vehicles
    if any(w in q for w in ["total", "how many", "count", "number of vehicle"]):
        detail = "\n".join(f"  • {s['camera_name']}: {s['total_vehicles']}" for s in stats)
        return f"**{total} vehicles** detected across all routes:\n{detail}"

    # Tokbashqe
    if any(w in q for w in ["tokba", "bashqe"]):
        s = next((x for x in stats if x["camera_id"] == "tokbashqe"), None)
        if s:
            return f"{line(s)}\n📍 {ROUTE_DESCRIPTIONS['tokbashqe']}"
        return "No data for Tokbashqe yet."

    # Pejton
    if "pejton" in q:
        matches = [x for x in stats if x["camera_id"].startswith("pejton")]
        if matches:
            return "\n".join(line(s) for s in matches)
        return "No data for Pejton yet."

    # Vehicle types breakdown
    if any(w in q for w in ["car", "truck", "bus", "motorcycl", "vehicle type", "breakdown", "type"]):
        parts = []
        for s in stats:
            c = s.get("counts", {})
            parts.append(
                f"**{s['camera_name']}**: 🚗 {c.get('car',0)} cars · "
                f"🚛 {c.get('truck',0)} trucks · 🚌 {c.get('bus',0)} buses · "
                f"🏍️ {c.get('motorcycle',0)} motorcycles"
            )
        return "\n".join(parts)

    # Cameras / routes list
    if any(w in q for w in ["camera", "route", "road", "monitor", "watch", "available", "cover"]):
        lines = [f"Monitoring **{len(stats)} camera(s)** in Prishtina:", ""]
        for s in stats:
            emoji = DENSITY_EMOJI.get(s["density"], "⚪")
            lines.append(f"• **{s['camera_name']}** — {ROUTE_DESCRIPTIONS.get(s['camera_id'], s['camera_id'])} {emoji}")
        return "\n".join(lines)

    # Hello / greeting
    if any(w in q for w in ["hello", "hi", "hey", "help", "what can"]):
        route_lines = "\n".join(
            f"  • **{s['camera_name']}** — {ROUTE_DESCRIPTIONS.get(s['camera_id'], s['camera_id'])} "
            f"{DENSITY_EMOJI.get(s['density'], '⚪')}"
            for s in stats
        )
        return (
            "Hi! I'm **TrafficBot** 🚦 — your AI traffic assistant for Prishtina.\n\n"
            f"I'm monitoring **{len(stats)} active route(s)**:\n{route_lines}\n\n"
            "I can help you with:\n"
            "• Current traffic conditions on any route\n"
            "• Vehicle counts (cars, trucks, buses, motorcycles)\n"
            "• Which route is busiest or clearest right now\n"
            "• Active congestion alerts\n\n"
            "Just ask away!"
        )

    # Off-topic check — handled at endpoint level before this function is called,
    # but kept here as a safety net for direct calls
    if not _is_traffic_related(question):
        return _offtopic_reply(stats)

    # Default: give full summary
    lines = ["Here's the current traffic overview:\n"]
    lines += [line(s) for s in stats]
    lines.append(f"\nTotal: **{total} vehicles** across {len(stats)} routes.")
    lines.append("\nAsk me about a specific route, vehicle types, or congestion!")
    return "\n".join(lines)


# ── OpenAI system prompt ──────────────────────────────────────────────────────

def _system_prompt(stats: list[dict]) -> str:
    if stats:
        data_lines = "\n".join(
            f"• {s['camera_name']} ({ROUTE_DESCRIPTIONS.get(s['camera_id'], s['camera_id'])}):\n"
            f"  Density={s['density']} | Vehicles={s['total_vehicles']} "
            f"(cars={s['counts'].get('car',0)}, trucks={s['counts'].get('truck',0)}, "
            f"buses={s['counts'].get('bus',0)}, motorcycles={s['counts'].get('motorcycle',0)})"
            for s in stats
        )
    else:
        data_lines = "• No live data yet."

    return f"""You are TrafficBot, an AI assistant embedded in TrafficWatch — a real-time traffic monitoring platform for Prishtina, Kosovo.

Your ONLY purpose is to answer questions about live road conditions, vehicle counts, congestion, and the monitored routes.

If the user asks about ANYTHING unrelated to traffic (e.g. weather, general knowledge, jokes, coding, etc.), respond with:
"I'm your Traffic AI Assistant 🚦 — I'm specialised in live road conditions for Prishtina. I can only help with traffic-related questions about the active routes. Try asking: 'Which route is busiest?' or 'Is Pejton congested?'"

Density levels: Low = clear traffic, Medium = moderate, High = congested.
Routes: pejton (Rr. Agim Ramadani), pejton2 (same corridor), tokbashqe (southern corridor).

LIVE DATA:
{data_lines}

Rules: be concise (2-5 sentences or bullet list), use 🟢🟡🔴, never invent data, suggest alternatives for congested routes."""


TRAFFIC_KEYWORDS = {
    "traffic", "route", "road", "vehicle", "car", "truck", "bus", "motorcycl",
    "camera", "pejton", "tokba", "prishtina", "congest", "density", "clear",
    "busy", "slow", "block", "drive", "travel", "commut", "speed", "count",
    "sensor", "monitor", "yolo", "detect", "alert", "summary", "status",
}

GREETING_WORDS = {"hello", "hi", "hey", "sup", "howdy", "greetings", "help"}


def _is_greeting(question: str) -> bool:
    q = question.lower().strip().rstrip("!.,?")
    return q in GREETING_WORDS or any(q.startswith(w + " ") for w in GREETING_WORDS)


def _is_traffic_related(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TRAFFIC_KEYWORDS)


def _greeting_reply(stats: list[dict]) -> str:
    count = len(stats)
    if stats:
        parts = " · ".join(
            f"{DENSITY_EMOJI.get(s['density'], '⚪')} {s['camera_name']} ({s['density']})"
            for s in stats
        )
        status = f"Currently watching **{count} route(s)**: {parts}"
    else:
        status = "Waiting for live traffic data…"
    return (
        f"Hello! 👋 I'm **TrafficBot** — your live traffic assistant for Prishtina.\n\n"
        f"{status}\n\n"
        "Ask me about road conditions, vehicle counts, or congestion!"
    )


def _offtopic_reply() -> str:
    return (
        "I'm your **Traffic AI Assistant** 🚦 — I only answer questions about "
        "live road conditions in Prishtina.\n\n"
        "Try: *\"Which route has the most traffic?\"*, *\"Is Pejton congested?\"*, "
        "or *\"Give me a traffic summary\"*."
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("")
async def chat(body: ChatRequest, request: Request):
    if not body.messages:
        return {"reply": "Please send a message.", "source": "local"}

    last_user_msg = next(
        (m.content for m in reversed(body.messages) if m.role == "user"), ""
    )
    live_stats = _get_live_stats(request, body.snapshots)

    # Greeting — simple, friendly, no data dump
    if _is_greeting(last_user_msg):
        return {"reply": _greeting_reply(live_stats), "source": "local"}

    # Off-topic guard — checked before OpenAI to avoid wasting the timeout
    if not _is_traffic_related(last_user_msg):
        return {"reply": _offtopic_reply(), "source": "local"}

    # Try OpenAI first; fall back to local on any failure
    try:
        from openai import AsyncOpenAI
        # max_retries=0 and a short timeout so quota/network errors fail fast
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=0, timeout=8.0)

        messages = [{"role": "system", "content": _system_prompt(live_stats)}]
        for turn in body.messages:
            if turn.role in ("user", "assistant"):
                messages.append({"role": turn.role, "content": turn.content})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=450,
            temperature=0.4,
        )
        reply = response.choices[0].message.content or _local_answer(last_user_msg, live_stats)
        return {"reply": reply, "source": "ai"}

    except Exception:
        # OpenAI unavailable (quota exceeded, network error, etc.)
        # — return a local answer from live traffic data instead
        return {"reply": _local_answer(last_user_msg, live_stats), "source": "local"}
