import math
import os
import random
import time
from typing import Any, Dict, List, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="WorldForge Backend", version="9.0.0")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://YOUR-RAILWAY-APP.up.railway.app").rstrip("/")
ROBLOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"

RATE_BUCKET: dict[str, list[float]] = {}
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1400)
    template: str = "custom"
    size: str = "medium"
    biome: str = "plains"
    density: str = "normal"
    capabilities: Dict[str, bool] = Field(default_factory=dict)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    try:
        client = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = RATE_BUCKET.setdefault(client, [])
        bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(bucket) >= RATE_LIMIT_COUNT:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please wait a moment."})
        bucket.append(now)
    except Exception:
        pass
    return await call_next(request)


@app.get("/")
async def root():
    return {"ok": True, "service": "worldforge-backend", "version": "9.0.0"}


@app.get("/config")
async def get_config():
    return {"endpoint": f"{PUBLIC_BASE_URL}/roblox/worldgen"}


def rgb(r: int, g: int, b: int) -> Dict[str, int]:
    return {"r": int(r), "g": int(g), "b": int(b)}


def vec(x: float, y: float, z: float) -> Dict[str, float]:
    return {"x": float(x), "y": float(y), "z": float(z)}


def clamp_material(name: str) -> str:
    allowed = {
        "Grass", "Ground", "Rock", "Slate", "Sand", "Snow", "Mud", "Basalt",
        "Wood", "WoodPlanks", "Cobblestone", "Concrete", "Glass", "Neon", "Fabric",
        "Brick", "LeafyGrass", "CrackedLava",
    }
    return name if name in allowed else "SmoothPlastic"


def part(
    name: str,
    position: Tuple[float, float, float],
    size: Tuple[float, float, float],
    material: str,
    color: Tuple[int, int, int],
    shape: str = "Block",
) -> Dict[str, Any]:
    return {
        "kind": "Part",
        "Name": name,
        "Shape": shape,
        "Position": vec(*position),
        "Size": vec(*size),
        "Material": clamp_material(material),
        "Color": rgb(*color),
    }


def model(name: str, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"kind": "Model", "Name": name, "parts": parts}


def biome_materials(biome: str) -> Dict[str, Any]:
    biome = (biome or "plains").lower()
    defaults = {
        "ground": "Grass",
        "road": "Ground",
        "rock": "Rock",
        "wall": "Cobblestone",
        "water_color": (70, 120, 170),
        "leaf": (80, 150, 80),
        "wood": (110, 82, 55),
        "fog": 700,
        "ambient": (105, 105, 115),
        "outdoor": (135, 135, 145),
    }
    table = {
        "forest": defaults,
        "plains": defaults,
        "mountain": {**defaults, "ground": "Rock", "road": "Slate", "rock": "Slate", "leaf": (90, 130, 90), "fog": 800},
        "snow": {**defaults, "ground": "Snow", "road": "Slate", "rock": "Slate", "leaf": (210, 220, 210), "ambient": (125, 125, 140), "outdoor": (160, 160, 180)},
        "desert": {**defaults, "ground": "Sand", "road": "Sand", "rock": "Rock", "wall": "Brick", "leaf": (130, 160, 80), "ambient": (125, 115, 90), "outdoor": (160, 145, 110)},
        "swamp": {**defaults, "ground": "Mud", "road": "Ground", "rock": "Rock", "leaf": (70, 105, 65), "ambient": (90, 100, 90), "outdoor": (110, 125, 110), "fog": 550},
    }
    return table.get(biome, defaults)


def size_span(size: str) -> int:
    return {"small": 320, "medium": 520, "large": 760}.get((size or "medium").lower(), 520)


def density_count(density: str) -> int:
    return {"light": 1, "normal": 2, "dense": 3}.get((density or "normal").lower(), 2)


def terrain_ops(span: int, biome: str, template: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    ops: List[Dict[str, Any]] = [
        {"kind": "FillBlock", "position": vec(0, -10, 0), "size": vec(span, 20, span), "material": mats["ground"]},
        {"kind": "FillBlock", "position": vec(0, 1, 0), "size": vec(28, 2, span * 0.55), "material": mats["road"]},
        {"kind": "FillBlock", "position": vec(0, 1, span * 0.18), "size": vec(span * 0.45, 2, 28), "material": mats["road"]},
        {"kind": "FillBall", "position": vec(-span * 0.28, 24, -span * 0.16), "radius": 46, "material": mats["rock"]},
        {"kind": "FillBall", "position": vec(span * 0.26, 20, span * 0.12), "radius": 34, "material": mats["ground"]},
        {"kind": "FillBall", "position": vec(span * 0.05, 16, -span * 0.28), "radius": 28, "material": mats["ground"]},
    ]
    if biome in {"swamp", "forest"}:
        ops.append({"kind": "FillBlock", "position": vec(-span * 0.2, 0, span * 0.28), "size": vec(120, 6, 70), "material": "Mud" if biome == "swamp" else "Grass"})
    if biome in {"snow", "mountain"} or template == "dungeon":
        ops.append({"kind": "ClearSphere", "position": vec(-span * 0.28, 22, -span * 0.16), "radius": 18})
    if template == "survival":
        ops.append({"kind": "FillBlock", "position": vec(0, 1, -span * 0.2), "size": vec(160, 2, 24), "material": mats["road"]})
    return ops


def tree_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [
        part("Trunk", (x, 6, z), (2.2, 12, 2.2), "Wood", mats["wood"]),
        part("Leaves", (x, 14, z), (10, 9, 10), "Grass", mats["leaf"], "Ball"),
    ])


def rock_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [part("Rock", (x, 3, z), (7, 6, 6), mats["rock"], (118, 118, 124), "Ball")])


def lamp_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("Post", (x, 5, z), (1, 10, 1), "Wood", (95, 70, 50)),
        part("Light", (x, 10.5, z), (2, 2, 2), "Neon", (255, 220, 120)),
    ])


def crate_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [part("Crate", (x, 1.5, z), (3, 3, 3), "WoodPlanks", (145, 108, 70))])


def chest_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("Base", (x, 1.25, z), (3.2, 2.5, 2.5), "WoodPlanks", (135, 95, 55)),
        part("Lid", (x, 2.9, z), (3.3, 1.2, 2.6), "Wood", (90, 60, 35)),
    ])


def bridge_model(name: str, x: float, z: float) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    for i in range(-4, 5):
        parts.append(part(f"Board_{i}", (x + i * 4, 2.5, z), (3.5, 0.8, 10), "WoodPlanks", (130, 95, 60)))
    parts.append(part("RailLeft", (x, 4.5, z - 5), (38, 1, 1), "Wood", (95, 70, 50)))
    parts.append(part("RailRight", (x, 4.5, z + 5), (38, 1, 1), "Wood", (95, 70, 50)))
    return model(name, parts)


def npc_marker(name: str, x: float, z: float, color: Tuple[int, int, int]) -> Dict[str, Any]:
    return part(name, (x, 2, z), (3, 1, 3), "Neon", color, "Cylinder")


def quest_board(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("PostA", (x - 1.5, 3.5, z), (1, 7, 1), "Wood", (95, 70, 50)),
        part("PostB", (x + 1.5, 3.5, z), (1, 7, 1), "Wood", (95, 70, 50)),
        part("Board", (x, 7, z), (8, 4, 1), "WoodPlanks", (160, 125, 85)),
    ])


def house_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [
        part("Base", (x, 2, z), (18, 4, 18), "WoodPlanks", (150, 110, 75)),
        part("Roof", (x, 8.5, z), (20, 3, 20), "Brick", (112, 54, 48)),
        part("Door", (x, 4, z + 9.2), (3, 6, 1), "Wood", (90, 60, 40)),
        part("WindowLeft", (x - 5, 6, z + 9.25), (3, 3, 1), "Glass", (125, 190, 255)),
        part("WindowRight", (x + 5, 6, z + 9.25), (3, 3, 1), "Glass", (125, 190, 255)),
        part("Chimney", (x + 6, 11, z - 5), (2, 5, 2), mats["rock"], (120, 120, 125)),
    ])


def ruin_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [
        part("WallA", (x - 8, 4, z), (2, 8, 16), mats["wall"], (125, 125, 125)),
        part("WallB", (x + 8, 4, z), (2, 8, 16), mats["wall"], (125, 125, 125)),
        part("Arch", (x, 8, z - 7), (14, 2, 2), mats["wall"], (125, 125, 125)),
        part("PillarA", (x - 5, 4, z - 7), (2, 8, 2), mats["wall"], (125, 125, 125)),
        part("PillarB", (x + 5, 4, z - 7), (2, 8, 2), mats["wall"], (125, 125, 125)),
    ])


def cave_gate(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [
        part("RockA", (x - 10, 8, z), (12, 16, 10), mats["rock"], (120, 120, 125), "Ball"),
        part("RockB", (x + 10, 8, z), (12, 16, 10), mats["rock"], (120, 120, 125), "Ball"),
        part("Top", (x, 16, z), (22, 6, 10), mats["rock"], (120, 120, 125)),
    ])


def scatter_ring(center_x: float, center_z: float, radius: float, count: int) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for i in range(count):
        angle = (math.pi * 2 / max(count, 1)) * i
        pts.append((center_x + math.cos(angle) * radius, center_z + math.sin(angle) * radius))
    return pts


def zone_layout(span: int, template: str) -> Dict[str, Tuple[float, float]]:
    return {
        "spawn": (0.0, -span * 0.23),
        "hub": (0.0, 0.0),
        "poi_left": (-span * 0.22, span * 0.18),
        "poi_right": (span * 0.24, span * 0.16),
        "far": (0.0, span * 0.32 if template != "dungeon" else span * 0.26),
    }


def village_props(span: int, biome: str, density: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    zones = zone_layout(span, "village")
    props: List[Dict[str, Any]] = []

    house_positions = [(-46, 6), (0, 2), (46, 6), (-72, -28), (72, -28)]
    for idx, (hx, hz) in enumerate(house_positions, start=1):
        props.append(house_model(f"House_{idx}", hx, hz, mats))

    props.extend([
        quest_board("QuestBoard", 0, 24),
        npc_marker("NPC_QuestGiver", 0, 12, (255, 220, 80)),
        npc_marker("NPC_Merchant", -18, 14, (100, 220, 255)),
        npc_marker("NPC_Guard", 20, 14, (255, 120, 120)),
        chest_model("RewardChest", 12, 30),
        ruin_model("ShrineRuin", zones["far"][0], zones["far"][1], mats),
    ])

    for idx, (lx, lz) in enumerate([(-24, -6), (24, -6), (-24, 34), (24, 34), (0, 64)], start=1):
        props.append(lamp_model(f"Lamp_{idx}", lx, lz))

    for idx, (cx, cz) in enumerate([(-10, -12), (10, -12), (-18, 28), (18, 28)], start=1):
        props.append(crate_model(f"Crate_{idx}", cx, cz))

    ring_count = 8 + density_count(density) * 4
    for idx, (tx, tz) in enumerate(scatter_ring(0, 10, span * 0.35, ring_count), start=1):
        props.append(tree_model(f"Tree_{idx}", tx, tz, mats))
    for idx, (rx, rz) in enumerate(scatter_ring(0, 6, span * 0.27, 5 + density_count(density)), start=1):
        props.append(rock_model(f"Rock_{idx}", rx, rz, mats))
    return props


def survival_props(span: int, biome: str, density: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    zones = zone_layout(span, "survival")
    props: List[Dict[str, Any]] = [
        model("CampTent_A", [part("Tent", (-16, 2.5, -24), (12, 5, 10), "Fabric", (170, 140, 90)), part("Pole", (-16, 5, -24), (1, 6, 1), "Wood", mats["wood"])]),
        model("CampTent_B", [part("Tent", (16, 2.5, -22), (12, 5, 10), "Fabric", (135, 160, 100)), part("Pole", (16, 5, -22), (1, 6, 1), "Wood", mats["wood"])]),
        quest_board("CampBoard", 0, -6),
        npc_marker("NPC_Survivor", 0, 10, (255, 220, 80)),
        npc_marker("NPC_Scout", 18, -2, (100, 220, 255)),
        chest_model("SupplyChest", -12, -4),
        bridge_model("CampBridge", zones["hub"][0], zones["hub"][1] + 112),
        cave_gate("CaveEntrance", zones["far"][0], zones["far"][1], mats),
    ]
    for idx, (tx, tz) in enumerate(scatter_ring(0, 18, span * 0.32, 10 + density_count(density) * 4), start=1):
        props.append(tree_model(f"Tree_{idx}", tx, tz, mats))
    for idx, (rx, rz) in enumerate(scatter_ring(0, 22, span * 0.24, 7 + density_count(density)), start=1):
        props.append(rock_model(f"Rock_{idx}", rx, rz, mats))
    for idx, (cx, cz) in enumerate([(-26, -10), (-6, -8), (9, -12), (22, -6)], start=1):
        props.append(crate_model(f"CampCrate_{idx}", cx, cz))
    return props


def dungeon_props(span: int, biome: str, density: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    zones = zone_layout(span, "dungeon")
    props: List[Dict[str, Any]] = [
        npc_marker("NPC_DungeonGuide", 0, -26, (255, 220, 80)),
        quest_board("WarningBoard", 0, -12),
        cave_gate("DungeonEntrance", 0, 42, mats),
        ruin_model("OuterRuin_A", -48, 78, mats),
        ruin_model("OuterRuin_B", 48, 78, mats),
        chest_model("BossChest", 0, 132),
    ]
    for idx, (lx, lz) in enumerate([(-18, 10), (18, 10), (-18, 48), (18, 48)], start=1):
        props.append(lamp_model(f"Torch_{idx}", lx, lz))
    for idx, (rx, rz) in enumerate(scatter_ring(0, 58, span * 0.18, 8 + density_count(density)), start=1):
        props.append(rock_model(f"DungeonRock_{idx}", rx, rz, mats))
    return props


def adventure_props(span: int, biome: str, density: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    props = village_props(span, biome, density)
    props.append(cave_gate("AdventureCave", 0, span * 0.26, mats))
    props.append(bridge_model("AdventureBridge", 0, span * 0.12))
    props.append(chest_model("AdventureChest", -18, span * 0.18))
    return props


def choose_props(template: str, span: int, biome: str, density: str) -> List[Dict[str, Any]]:
    template = (template or "custom").lower()
    if template == "survival":
        return survival_props(span, biome, density)
    if template == "dungeon":
        return dungeon_props(span, biome, density)
    if template == "adventure":
        return adventure_props(span, biome, density)
    return village_props(span, biome, density)


def script_bundle(template: str) -> List[Dict[str, str]]:
    quest_state_module = {
        "className": "ModuleScript",
        "name": "QuestState",
        "source": (
            "local QuestState = {}\n"
            "QuestState.ActiveQuest = nil\n"
            "QuestState.Completed = {}\n"
            "return QuestState\n"
        ),
    }
    ambient_script = {
        "className": "Script",
        "name": "AmbientCycle",
        "source": (
            "local Lighting = game:GetService('Lighting')\n"
            "while task.wait(8) do\n"
            "    Lighting.ClockTime = (Lighting.ClockTime + 0.12) % 24\n"
            "end\n"
        ),
    }
    npc_hint = {
        "className": "Script",
        "name": "NPCInteractionStarter",
        "source": (
            "print('WorldForge generated NPC markers and quest props. Replace markers with NPC models and connect dialogue UI here.')\n"
        ),
    }
    template_hint = {
        "className": "Script",
        "name": "TemplateNotes",
        "source": f"print('World template: {template}. Add enemies, loot, and interactives to finish the gameplay loop.')\n",
    }
    return [quest_state_module, ambient_script, npc_hint, template_hint]


def asset_queries_for_prompt(prompt: str, biome: str, template: str) -> List[str]:
    text = f"{prompt} {biome} {template}".lower()
    queries: List[str] = []
    if "village" in text or template == "village":
        queries += ["medieval house", "market stall", "cart"]
    if template == "survival":
        queries += ["camp tent", "campfire", "wooden crate"]
    if "dungeon" in text or template == "dungeon":
        queries += ["ruins", "torch", "cave"]
    if biome in {"forest", "plains", "swamp"}:
        queries += ["tree", "bush"]
    if biome == "snow":
        queries += ["snow tree", "winter cabin"]
    if biome == "desert":
        queries += ["cactus", "desert ruin"]
    if not queries:
        queries = ["tree", "rock"]
    return queries[:6]


def search_creator_store_assets(keyword: str, limit: int = 3) -> List[Dict[str, Any]]:
    params = {"keyword": keyword, "limit": limit, "includeOnlyVerifiedCreators": "false"}
    try:
        response = requests.get(ROBLOX_SEARCH_URL, params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    results: List[Dict[str, Any]] = []
    for item in payload.get("data", []):
        asset_id = item.get("asset", {}).get("id") or item.get("id")
        if not asset_id:
            continue
        results.append({"assetId": int(asset_id), "position": vec(0, 4, 0), "query": keyword})
    return results


def pick_assets(prompt: str, biome: str, template: str, span: int) -> List[Dict[str, Any]]:
    positions = [(-span * 0.18, 4, -span * 0.04), (span * 0.18, 4, -span * 0.04), (0, 4, span * 0.2)]
    found: List[Dict[str, Any]] = []
    seen: set[int] = set()
    pos_index = 0
    for query in asset_queries_for_prompt(prompt, biome, template):
        for item in search_creator_store_assets(query, 2):
            asset_id = item["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            px, py, pz = positions[pos_index % len(positions)]
            pos_index += 1
            item["position"] = vec(px, py, pz)
            found.append(item)
            if len(found) >= 4:
                return found
    return found


@app.post("/roblox/worldgen")
async def roblox_worldgen(body: GenerateRequest):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    template = (body.template or "custom").lower()
    if template == "custom":
        if "dungeon" in prompt.lower() or "ruin" in prompt.lower():
            template = "dungeon"
        elif "survival" in prompt.lower() or "camp" in prompt.lower():
            template = "survival"
        elif "adventure" in prompt.lower() or "bridge" in prompt.lower():
            template = "adventure"
        else:
            template = "village"

    biome = (body.biome or "plains").lower()
    size = (body.size or "medium").lower()
    density = (body.density or "normal").lower()
    caps = body.capabilities or {}

    span = size_span(size)
    mats = biome_materials(biome)
    props = choose_props(template, span, biome, density) if caps.get("props", True) else []
    assets = pick_assets(prompt, biome, template, span) if caps.get("props", True) else []

    lighting = {
        "ClockTime": 15 if biome != "swamp" else 17,
        "Brightness": 2,
        "FogStart": 100,
        "FogEnd": mats["fog"],
        "Ambient": rgb(*mats["ambient"]),
        "OutdoorAmbient": rgb(*mats["outdoor"]),
    }

    plan: Dict[str, Any] = {
        "folders": ["Gameplay", "Spawns", "Decor", "GeneratedScripts"],
        "lighting": lighting,
        "terrain": terrain_ops(span, biome, template) if caps.get("terrain", True) else [],
        "primitiveProps": [
            part("SpawnPad", (0, 3, -span * 0.23), (14, 1, 14), "Neon", (0, 170, 255), "Cylinder"),
            quest_board("StartBoard", 0, -span * 0.18),
        ] + props,
        "storeAssets": assets,
        "scripts": script_bundle(template) if caps.get("scripts", True) else [],
        "selectionTargets": ["SpawnPad"],
    }
    return plan
