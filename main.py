import os
import math
import random
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://worldforge-backend-production.up.railway.app",
).rstrip("/")

ROBLOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"

RATE_BUCKET: dict[str, list[float]] = {}
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1200)
    template: str = "custom"
    size: str = "medium"
    biome: str = "plains"
    capabilities: Dict[str, bool] = Field(default_factory=dict)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    try:
        client = request.client.host if request.client else "unknown"
        now = __import__("time").time()
        bucket = RATE_BUCKET.setdefault(client, [])
        bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(bucket) >= RATE_LIMIT_COUNT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please wait a moment."},
            )
        bucket.append(now)
    except Exception:
        pass
    return await call_next(request)


@app.get("/")
async def root():
    return {"ok": True, "service": "worldforge-backend", "version": "8.1.0"}


@app.get("/config")
async def get_config():
    return {"endpoint": f"{PUBLIC_BASE_URL}/roblox/worldgen"}


def safe_material(name: str) -> str:
    allowed = {
        "Grass", "Ground", "Rock", "Slate", "Sand", "Snow", "Mud",
        "Basalt", "Wood", "WoodPlanks", "Cobblestone", "Concrete",
        "Glass", "Neon", "Fabric", "Brick",
    }
    return name if name in allowed else "SmoothPlastic"


def rgb(r: int, g: int, b: int) -> Dict[str, int]:
    return {"r": int(r), "g": int(g), "b": int(b)}


def vec(x: float, y: float, z: float) -> Dict[str, float]:
    return {"x": float(x), "y": float(y), "z": float(z)}


def part(
    name: str,
    position: tuple[float, float, float],
    size: tuple[float, float, float],
    material: str,
    color: tuple[int, int, int],
    shape: str = "Block",
) -> Dict[str, Any]:
    return {
        "kind": "Part",
        "Name": name,
        "Shape": shape,
        "Position": vec(*position),
        "Size": vec(*size),
        "Material": safe_material(material),
        "Color": rgb(*color),
    }


def model(name: str, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"kind": "Model", "Name": name, "parts": parts}


def biome_materials(biome: str) -> Dict[str, Any]:
    biome = biome.lower()
    if biome == "snow":
        return {
            "ground": "Snow",
            "rock": "Slate",
            "wood": "WoodPlanks",
            "leaf_color": rgb(220, 235, 220),
            "ground_color": rgb(235, 235, 245),
        }
    if biome == "desert":
        return {
            "ground": "Sand",
            "rock": "Sandstone",
            "wood": "WoodPlanks",
            "leaf_color": rgb(120, 170, 80),
            "ground_color": rgb(220, 200, 120),
        }
    if biome == "swamp":
        return {
            "ground": "Mud",
            "rock": "Rock",
            "wood": "WoodPlanks",
            "leaf_color": rgb(90, 120, 70),
            "ground_color": rgb(90, 90, 70),
        }
    if biome == "mountain":
        return {
            "ground": "Rock",
            "rock": "Slate",
            "wood": "WoodPlanks",
            "leaf_color": rgb(90, 140, 90),
            "ground_color": rgb(120, 120, 120),
        }
    return {
        "ground": "Grass",
        "rock": "Rock",
        "wood": "WoodPlanks",
        "leaf_color": rgb(80, 150, 80),
        "ground_color": rgb(100, 180, 100),
    }


def tree_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Trunk", (x, 5, z), (2, 10, 2), "Wood", (110, 82, 55)),
            part("Leaves", (x, 12, z), (8, 8, 8), "Grass", (
                mats["leaf_color"]["r"],
                mats["leaf_color"]["g"],
                mats["leaf_color"]["b"],
            )),
        ],
    )


def lamp_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Post", (x, 4, z), (1, 8, 1), "Wood", (95, 70, 50)),
            part("Light", (x, 9, z), (2, 2, 2), "Neon", (255, 220, 120)),
        ],
    )


def crate_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [part("Crate", (x, 1.5, z), (3, 3, 3), "WoodPlanks", (140, 105, 70))]
    )


def rock_model(name: str, x: float, z: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    return model(
        name,
        [part("Rock", (x, 3, z), (6, 6, 6), mats["rock"], (120, 120, 125), "Ball")]
    )


def house_model(name: str, x: float, z: float, rot: float, mats: Dict[str, Any]) -> Dict[str, Any]:
    # rot is kept for future use; currently layout is axis-aligned
    _ = rot
    return model(
        name,
        [
            part("Base", (x, 2, z), (16, 4, 16), "WoodPlanks", (150, 110, 75)),
            part("Roof", (x, 9, z), (18, 4, 18), "Brick", (110, 50, 45)),
            part("Door", (x, 4, z + 8.2), (3, 6, 1), "Wood", (95, 65, 45)),
            part("WindowLeft", (x - 5, 6, z + 8.3), (3, 3, 1), "Glass", (120, 190, 255)),
            part("WindowRight", (x + 5, 6, z + 8.3), (3, 3, 1), "Glass", (120, 190, 255)),
        ],
    )


def quest_board(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [
            part("PostA", (x - 1.5, 3, z), (1, 6, 1), "Wood", (95, 70, 50)),
            part("PostB", (x + 1.5, 3, z), (1, 6, 1), "Wood", (95, 70, 50)),
            part("Board", (x, 6, z), (8, 4, 1), "WoodPlanks", (160, 125, 85)),
        ],
    )


def npc_marker(name: str, x: float, z: float) -> Dict[str, Any]:
    return part(name, (x, 2, z), (3, 1, 3), "Neon", (255, 220, 80), "Cylinder")


def size_span(size: str) -> int:
    return {"small": 220, "medium": 340, "large": 520}.get(size, 340)


def make_terrain(size: str, biome: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    span = size_span(size)

    terrain = [
        {
            "kind": "FillBlock",
            "position": vec(0, -8, 0),
            "size": vec(span, 16, span),
            "material": mats["ground"],
        },
        {
            "kind": "FillBall",
            "position": vec(-80, 22, -30),
            "radius": 40,
            "material": mats["rock"],
        },
        {
            "kind": "FillBall",
            "position": vec(85, 16, 45),
            "radius": 30,
            "material": mats["ground"],
        },
        {
            "kind": "FillBlock",
            "position": vec(0, 1, 0),
            "size": vec(18, 2, 80),
            "material": "Ground" if biome != "desert" else "Sand",
        },
    ]

    if biome in {"mountain", "snow"}:
        terrain.append(
            {"kind": "ClearSphere", "position": vec(-82, 22, -30), "radius": 14}
        )

    return terrain


def village_props(biome: str, size: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    props: List[Dict[str, Any]] = []

    houses = [
        house_model("House_A", -38, 0, 0, mats),
        house_model("House_B", 0, 0, 0, mats),
        house_model("House_C", 38, 0, 0, mats),
    ]
    props.extend(houses)

    props.extend(
        [
            lamp_model("Lamp_A", -18, 18),
            lamp_model("Lamp_B", 18, 18),
            crate_model("Crate_A", -10, -14),
            crate_model("Crate_B", 10, -12),
            rock_model("Rock_A", -60, 20, mats),
            rock_model("Rock_B", 62, -25, mats),
            tree_model("Tree_A", -75, -10, mats),
            tree_model("Tree_B", -90, 30, mats),
            tree_model("Tree_C", 75, -18, mats),
            tree_model("Tree_D", 90, 26, mats),
            quest_board("QuestBoard", 0, 22),
            npc_marker("NPC_QuestGiver", 0, 12),
            npc_marker("NPC_Merchant", -20, 10),
            npc_marker("NPC_Guard", 22, 12),
        ]
    )

    if size == "large":
        props.extend(
            [
                house_model("House_D", -76, -20, 0, mats),
                house_model("House_E", 76, -20, 0, mats),
                tree_model("Tree_E", -110, -60, mats),
                tree_model("Tree_F", 112, 58, mats),
            ]
        )

    return props


def dungeon_props(biome: str, size: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    props = [
        rock_model("RockEntranceA", -30, -50, mats),
        rock_model("RockEntranceB", 30, -50, mats),
        quest_board("WarningBoard", 0, -25),
        npc_marker("NPC_DungeonGuide", 0, -10),
        crate_model("SupplyCrate_A", -12, -16),
        crate_model("SupplyCrate_B", 12, -16),
    ]
    return props


def survival_props(biome: str, size: str) -> List[Dict[str, Any]]:
    mats = biome_materials(biome)
    props = [
        model(
            "CampTent_A",
            [
                part("TentBase", (-12, 2, 8), (10, 4, 8), "Fabric", (170, 140, 90)),
                part("TentPole", (-12, 5, 8), (1, 6, 1), "Wood", (95, 70, 50)),
            ],
        ),
        model(
            "CampTent_B",
            [
                part("TentBase", (12, 2, 8), (10, 4, 8), "Fabric", (140, 160, 90)),
                part("TentPole", (12, 5, 8), (1, 6, 1), "Wood", (95, 70, 50)),
            ],
        ),
        crate_model("CampCrate_A", -6, -6),
        crate_model("CampCrate_B", 6, -4),
        npc_marker("NPC_Survivor", 0, 14),
        rock_model("Rock_Camp_A", -36, 26, mats),
        tree_model("Tree_Camp_A", 42, 26, mats),
        tree_model("Tree_Camp_B", -48, -18, mats),
    ]
    return props


def choose_props(template: str, biome: str, size: str) -> List[Dict[str, Any]]:
    template = (template or "custom").lower()
    if "dungeon" in template:
        return dungeon_props(biome, size)
    if "survival" in template:
        return survival_props(biome, size)
    return village_props(biome, size)


def search_creator_store_assets(keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
    params = {"keyword": keyword, "limit": limit, "includeOnlyVerifiedCreators": "false"}
    try:
        response = requests.get(ROBLOX_SEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    results: List[Dict[str, Any]] = []
    for item in payload.get("data", []):
        asset_id = item.get("asset", {}).get("id") or item.get("id")
        if not asset_id:
            continue
        results.append(
            {
                "assetId": int(asset_id),
                "position": vec(0, 4, 0),
                "query": keyword,
            }
        )
    return results


def asset_queries_for_prompt(prompt: str, biome: str, template: str) -> List[str]:
    text = f"{prompt} {biome} {template}".lower()
    queries: List[str] = []

    if "village" in text or template == "village":
        queries += ["wood house", "market stall", "lamp post"]
    if "forest" in text or biome in {"forest", "plains", "swamp"}:
        queries += ["tree", "bush"]
    if "cave" in text or "dungeon" in text or template == "dungeon":
        queries += ["rock", "ruin", "cave"]
    if biome == "snow":
        queries += ["snow tree", "winter cabin"]
    if biome == "desert":
        queries += ["cactus", "desert ruin"]

    if not queries:
        queries = ["tree", "rock"]

    return queries[:6]


def pick_assets(prompt: str, biome: str, template: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for query in asset_queries_for_prompt(prompt, biome, template):
        for item in search_creator_store_assets(query, 3):
            asset_id = item["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            found.append(item)
            if len(found) >= 8:
                return found
    return found


def script_bundle() -> List[Dict[str, str]]:
    return [
        {
            "className": "Script",
            "name": "AmbientCycle",
            "source": (
                "local Lighting = game:GetService('Lighting')\n"
                "while task.wait(8) do\n"
                "    Lighting.ClockTime = (Lighting.ClockTime + 0.15) % 24\n"
                "end\n"
            ),
        },
        {
            "className": "Script",
            "name": "NPCInteractionStarter",
            "source": "print('WorldForge NPC content created. Add your own dialogue UI or quest logic here.')\n",
        },
    ]


@app.post("/roblox/worldgen")
async def roblox_worldgen(body: GenerateRequest):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    template = (body.template or "custom").lower()
    biome = (body.biome or "plains").lower()
    size = (body.size or "medium").lower()
    caps = body.capabilities or {}

    props = choose_props(template, biome, size) if caps.get("props", True) else []
    assets = pick_assets(prompt, biome, template) if caps.get("props", True) else []

    plan: Dict[str, Any] = {
        "folders": ["Gameplay", "Spawns", "Decor", "GeneratedScripts"],
        "lighting": {
            "ClockTime": 15,
            "Brightness": 2,
            "FogStart": 100,
            "FogEnd": 700,
            "Ambient": rgb(100, 100, 110),
            "OutdoorAmbient": rgb(130, 130, 140),
        },
        "terrain": make_terrain(size, biome) if caps.get("terrain", True) else [],
        "primitiveProps": [
            part("SpawnPad", (0, 3, 0), (12, 1, 12), "Neon", (0, 170, 255), "Cylinder")
        ] + props,
        "storeAssets": assets,
        "scripts": script_bundle() if caps.get("scripts", True) else [],
        "selectionTargets": ["SpawnPad"],
    }

    return plan
