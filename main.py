import math
import os
import random
from typing import Any, Dict, List, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="WorldForge Backend", version="8.0.0")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://worldforge-backend-production.up.railway.app").rstrip("/")
ROBLOX_TOOLBOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"
AUTO_ASSET_SEARCH = os.getenv("AUTO_ASSET_SEARCH", "true").lower() == "true"

RATE_LIMIT_STORE: Dict[str, List[float]] = {}
RATE_LIMIT_COUNT = int(os.getenv("RATE_LIMIT_COUNT", "12"))
RATE_LIMIT_WINDOW_SECONDS = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

class GenerateRequest(BaseModel):
    prompt: str = Field(default="fantasy village with quest NPCs, houses, trees, and a cave", min_length=0, max_length=1200)
    template: str = Field(default="village", max_length=80)
    biome: str = Field(default="forest", max_length=80)
    size: str = Field(default="medium", max_length=20)
    preview_only: bool = False
    capabilities: Dict[str, bool] = Field(default_factory=dict)

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    now = __import__("time").time()
    bucket = RATE_LIMIT_STORE.setdefault(client, [])
    bucket[:] = [t for t in bucket if now - t <= RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_COUNT and request.url.path == "/roblox/worldgen":
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a moment and try again."},
        )
    if request.url.path == "/roblox/worldgen":
        bucket.append(now)
    return await call_next(request)

@app.get("/")
async def root():
    return {"ok": True, "service": "worldforge-backend", "version": "8.0.0"}

@app.get("/config")
async def get_config():
    return {"endpoint": f"{PUBLIC_BASE_URL}/roblox/worldgen"}

def size_span(size: str) -> int:
    return {"small": 240, "medium": 360, "large": 520}.get(size.lower(), 360)

def biome_materials(biome: str) -> Dict[str, str]:
    table = {
        "forest": {"top": "Grass", "rock": "Rock", "path": "Ground", "wood": "WoodPlanks"},
        "plains": {"top": "Grass", "rock": "Rock", "path": "Ground", "wood": "WoodPlanks"},
        "snow": {"top": "Snow", "rock": "Slate", "path": "Ground", "wood": "WoodPlanks"},
        "desert": {"top": "Sand", "rock": "Sandstone", "path": "Sand", "wood": "WoodPlanks"},
        "mountain": {"top": "Grass", "rock": "Rock", "path": "Ground", "wood": "WoodPlanks"},
        "swamp": {"top": "Mud", "rock": "Rock", "path": "Ground", "wood": "WoodPlanks"},
    }
    return table.get(biome.lower(), table["forest"])

def lighting_for_biome(biome: str) -> Dict[str, Any]:
    presets = {
        "forest": {"ClockTime": 14.5, "Brightness": 2.1, "FogStart": 120, "FogEnd": 800, "Ambient": {"r": 100, "g": 110, "b": 100}, "OutdoorAmbient": {"r": 125, "g": 140, "b": 125}},
        "plains": {"ClockTime": 13, "Brightness": 2.2, "FogStart": 140, "FogEnd": 900, "Ambient": {"r": 110, "g": 110, "b": 110}, "OutdoorAmbient": {"r": 145, "g": 145, "b": 145}},
        "snow": {"ClockTime": 11, "Brightness": 2.4, "FogStart": 90, "FogEnd": 700, "Ambient": {"r": 145, "g": 155, "b": 170}, "OutdoorAmbient": {"r": 180, "g": 190, "b": 205}},
        "desert": {"ClockTime": 15.5, "Brightness": 2.6, "FogStart": 180, "FogEnd": 1000, "Ambient": {"r": 140, "g": 120, "b": 100}, "OutdoorAmbient": {"r": 180, "g": 165, "b": 140}},
        "mountain": {"ClockTime": 13.5, "Brightness": 2.0, "FogStart": 100, "FogEnd": 650, "Ambient": {"r": 110, "g": 110, "b": 120}, "OutdoorAmbient": {"r": 135, "g": 140, "b": 150}},
        "swamp": {"ClockTime": 16, "Brightness": 1.8, "FogStart": 80, "FogEnd": 450, "Ambient": {"r": 90, "g": 110, "b": 90}, "OutdoorAmbient": {"r": 100, "g": 130, "b": 100}},
    }
    return presets.get(biome.lower(), presets["forest"])

def search_store_assets(keyword: str, limit: int = 6) -> List[Dict[str, Any]]:
    if not AUTO_ASSET_SEARCH:
        return []
    try:
        response = requests.get(
            ROBLOX_TOOLBOX_SEARCH_URL,
            params={"keyword": keyword, "limit": limit, "includeOnlyVerifiedCreators": "false"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    results: List[Dict[str, Any]] = []
    for item in payload.get("data", []):
        asset_id = item.get("asset", {}).get("id") or item.get("id")
        if not asset_id:
            continue
        results.append({"assetId": int(asset_id)})
    return results

def world_queries(template: str, biome: str, prompt: str) -> List[str]:
    text = f"{template} {biome} {prompt}".lower()
    queries: List[str] = []
    if "village" in text or "town" in text:
        queries.extend(["medieval house", "market stall", "wood fence"])
    if "forest" in text or biome == "forest":
        queries.extend(["tree", "pine tree", "bush"])
    if "cave" in text or "mountain" in text or biome == "mountain":
        queries.extend(["cave entrance", "rock", "boulder"])
    if biome == "desert":
        queries.extend(["cactus", "desert ruin", "sandstone rock"])
    if biome == "snow":
        queries.extend(["snow pine", "winter cabin", "ice rock"])
    if "dungeon" in text or "ruin" in text:
        queries.extend(["stone ruin", "dungeon prop", "torch"])
    return queries[:8] if queries else ["tree", "rock", "crate"]

def plan_store_assets(template: str, biome: str, prompt: str) -> List[Dict[str, Any]]:
    assets: List[Dict[str, Any]] = []
    seen = set()
    offsets = [(-35, 4, 18), (35, 4, -22), (55, 4, 38), (-62, 4, -28), (18, 4, 60), (-18, 4, -55)]
    for idx, query in enumerate(world_queries(template, biome, prompt)):
        for item in search_store_assets(query, limit=3):
            aid = item["assetId"]
            if aid in seen:
                continue
            seen.add(aid)
            x, y, z = offsets[len(assets) % len(offsets)]
            assets.append({"assetId": aid, "position": {"x": x, "y": y, "z": z}})
            break
        if len(assets) >= 6:
            break
    return assets

def terrain_plan(template: str, biome: str, size: str, prompt: str) -> List[Dict[str, Any]]:
    span = size_span(size)
    mats = biome_materials(biome)
    ops: List[Dict[str, Any]] = [
        {"kind": "FillBlock", "position": {"x": 0, "y": -8, "z": 0}, "size": {"x": span, "y": 16, "z": span}, "material": mats["top"]},
        {"kind": "FillBlock", "position": {"x": 0, "y": -4, "z": 0}, "size": {"x": span - 18, "y": 4, "z": span - 18}, "material": mats["top"]},
        {"kind": "FillBall", "position": {"x": -88, "y": 28, "z": -42}, "radius": 54, "material": mats["rock"]},
        {"kind": "FillBall", "position": {"x": 90, "y": 18, "z": 40}, "radius": 42, "material": mats["top"]},
        {"kind": "FillCylinder", "position": {"x": 0, "y": 1, "z": 0}, "height": 2, "radius": span / 3.6, "material": mats["path"]},
    ]
    if "cave" in prompt.lower() or template.lower() in {"dungeon", "survival"}:
        ops.append({"kind": "FillBall", "position": {"x": -110, "y": 36, "z": -10}, "radius": 62, "material": mats["rock"]})
        ops.append({"kind": "ClearSphere", "position": {"x": -92, "y": 30, "z": -8}, "radius": 18})
    if biome.lower() == "swamp":
        ops.append({"kind": "FillBlock", "position": {"x": 72, "y": -2, "z": -78}, "size": {"x": 68, "y": 3, "z": 54}, "material": "Water"})
    return ops

def part(name: str, pos: Tuple[float, float, float], size: Tuple[float, float, float], material: str, color: Tuple[int, int, int], shape: str = "Block") -> Dict[str, Any]:
    return {
        "kind": "Part",
        "Name": name,
        "Position": {"x": pos[0], "y": pos[1], "z": pos[2]},
        "Size": {"x": size[0], "y": size[1], "z": size[2]},
        "Material": material,
        "Color": {"r": color[0], "g": color[1], "b": color[2]},
        "Shape": shape,
    }

def house_model(name: str, x: float, z: float, mats: Dict[str, str]) -> Dict[str, Any]:
    return {
        "kind": "Model",
        "Name": name,
        "parts": [
            part("Base", (x, 5, z), (20, 10, 16), mats["wood"], (145, 108, 74)),
            part("Roof", (x, 12, z), (22, 4, 18), "Slate", (85, 70, 70)),
            part("Door", (x, 3, z + 8.5), (3, 6, 1), mats["wood"], (92, 65, 44)),
            part("WindowLeft", (x - 5, 6, z + 8.3), (3, 3, 1), "Glass", (120, 190, 255)),
            part("WindowRight", (x + 5, 6, z + 8.3), (3, 3, 1), "Glass", (120, 190, 255)),
        ],
    }

def tree_model(name: str, x: float, z: float, snow: bool = False) -> Dict[str, Any]:
    leaf_color = (220, 230, 230) if snow else (68, 126, 61)
    leaf_mat = "Snow" if snow else "Grass"
    return {
        "kind": "Model",
        "Name": name,
        "parts": [
            part("Trunk", (x, 7, z), (2, 14, 2), "Wood", (102, 68, 44)),
            part("Leaves", (x, 16, z), (9, 9, 9), leaf_mat, leaf_color, "Ball"),
        ],
    }

def lamp_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return {
        "kind": "Model",
        "Name": name,
        "parts": [
            part("Pole", (x, 6, z), (1, 12, 1), "Metal", (90, 90, 95)),
            part("Lamp", (x, 12.5, z), (2, 2, 2), "Neon", (255, 230, 125)),
        ],
    }

def crate_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return {
        "kind": "Model",
        "Name": name,
        "parts": [
            part("Crate", (x, 2, z), (4, 4, 4), "WoodPlanks", (126, 90, 58)),
        ],
    }

def quest_npcs() -> List[Dict[str, Any]]:
    names = ["Bram", "Mira", "Liora"]
    spots = [(8, 10), (20, -8), (-18, 16)]
    props: List[Dict[str, Any]] = []
    for name, (x, z) in zip(names, spots):
        props.append(part(f"{name}_Marker", (x, 3, z), (3, 1, 3), "Neon", (255, 214, 80), "Cylinder"))
        props.append({
            "kind": "Model",
            "Name": f"{name}_QuestSign",
            "parts": [
                part("Post", (x + 4, 4, z), (1, 6, 1), "Wood", (120, 85, 60)),
                part("Board", (x + 4, 7, z), (5, 3, 1), "WoodPlanks", (150, 115, 75)),
            ],
        })
    return props

def village_props(biome: str, size: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    snow = biome.lower() == "snow"
    props: List[Dict[str, Any]] = [
        part("SpawnPad", (0, 3, 0), (12, 1, 12), "Neon", (0, 170, 255), "Cylinder"),
        house_model("House_A", -38, 0, 0, mats),
        house_model("House_B", 0, 0, 90, mats),
        house_model("House_C", 38, 0, 180, mats,),
        lamp_model("Lamp_A", -16, 10),
        lamp_model("Lamp_B", 16, 10),
        crate_model("Crate_A", 6, 18),
        crate_model("Crate_B", -10, 20),
        {
            "kind": "Model",
            "Name": "QuestBoard",
            "parts": [
                part("BoardPost", (0, 5, 18), (1, 8, 1), "Wood", (110, 78, 52)),
                part("BoardFace", (0, 9, 18), (10, 5, 1), "WoodPlanks", (158, 124, 84)),
            ],
        },
    ]
    tree_spots = [(-70, -25), (-84, 25), (78, -18), (86, 24), (48, 72), (-38, 72), (0, -76)]
    for idx, (x, z) in enumerate(tree_spots):
        props.append(tree_model(f"Tree_{idx+1}", x, z, snow=snow))
    props.extend(quest_npcs())
    if size.lower() == "large":
        props.append(house_model("House_D", -72, 40, mats))
        props.append(house_model("House_E", 72, -26, mats))
    return props

def dungeon_props(biome: str) -> List[Dict[str, Any]]:
    props = [
        part("SpawnPad", (0, 3, 0), (12, 1, 12), "Neon", (0, 170, 255), "Cylinder"),
        {
            "kind": "Model",
            "Name": "DungeonGate",
            "parts": [
                part("LeftPillar", (-10, 9, -18), (4, 18, 4), "Slate", (90, 90, 90)),
                part("RightPillar", (10, 9, -18), (4, 18, 4), "Slate", (90, 90, 90)),
                part("TopArch", (0, 18, -18), (24, 4, 4), "Slate", (95, 95, 95)),
            ],
        },
        crate_model("SupplyCrate", 14, -8),
        crate_model("TreasureCrate", -15, -8),
        lamp_model("TorchLeft", -8, -8),
        lamp_model("TorchRight", 8, -8),
    ]
    props.extend(quest_npcs())
    return props

def survival_props(biome: str) -> List[Dict[str, Any]]:
    props = village_props(biome, "small")
    props.append({
        "kind": "Model",
        "Name": "Campfire",
        "parts": [
            part("FireCore", (14, 2, 14), (3, 3, 3), "Neon", (255, 120, 0), "Ball"),
            part("LogA", (13, 1, 14), (5, 1, 1), "Wood", (100, 70, 44)),
            part("LogB", (15, 1, 14), (5, 1, 1), "Wood", (100, 70, 44)),
        ],
    })
    return props

def scripts_for_world(template: str) -> List[Dict[str, str]]:
    quest_module = """return {
    Quests = {
        {Name = "Gather Village Supplies", Objective = "Collect 5 items", Reward = 50},
        {Name = "Explore the Cave", Objective = "Reach the cave entrance", Reward = 100},
        {Name = "Deliver a Message", Objective = "Talk to Mira", Reward = 35},
    }
}"""
    npc_script = """print('WorldForge NPC content created. Add your own dialogue UI or ProximityPrompt wiring here.')"""
    ambient_script = """local Lighting = game:GetService('Lighting')
while task.wait(8) do
    Lighting.ClockTime = (Lighting.ClockTime + 0.12) % 24
end"""
    chest_script = """local folder = workspace:FindFirstChild('WorldForge_Output')
if folder then
    print('WorldForge generated world is ready.')
end"""
    return [
        {"className": "Script", "name": "AmbientCycle", "source": ambient_script},
        {"className": "ModuleScript", "name": "QuestConfig", "source": quest_module},
        {"className": "Script", "name": "NPCInteractionStarter", "source": npc_script},
        {"className": "Script", "name": "WorldReady", "source": chest_script},
    ]

def choose_props(template: str, biome: str, size: str) -> List[Dict[str, Any]]:
    t = template.lower()
    if t == "dungeon":
        return dungeon_props(biome)
    if t == "survival":
        return survival_props(biome)
    return village_props(biome, size)

@app.post("/roblox/worldgen")
async def roblox_worldgen(body: GenerateRequest):
    prompt = (body.prompt or "").strip()
    template = (body.template or "village").strip().lower()
    biome = (body.biome or "forest").strip().lower()
    size = (body.size or "medium").strip().lower()
    caps = body.capabilities or {}

    plan: Dict[str, Any] = {
        "folders": ["Gameplay", "Spawns", "Decor"],
        "lighting": lighting_for_biome(biome) if caps.get("lighting", True) else {},
        "terrain": terrain_plan(template, biome, size, prompt) if caps.get("terrain", True) else [],
        "primitiveProps": choose_props(template, biome, size) if caps.get("props", True) else [],
        "storeAssets": plan_store_assets(template, biome, prompt) if caps.get("props", True) else [],
        "scripts": scripts_for_world(template) if caps.get("scripts", True) else [],
        "selectionTargets": ["SpawnPad"],
        "meta": {
            "template": template,
            "biome": biome,
            "size": size,
            "preview_only": body.preview_only,
            "summary": "WorldForge v8 builds a fuller starter world with terrain, structures, NPC markers, quests, and optional live asset search.",
        }
    }

    if body.preview_only:
        return plan
    return plan
