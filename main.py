import os
import random
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://worldforge-backend-production.up.railway.app")
ROBLOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"

# Simple in-memory rate limit
RATE_BUCKET: dict[str, list[float]] = {}
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1200)
    template: str = "custom"
    size: str = "medium"
    biome: str = "plains"
    capabilities: Dict[str, bool] = Field(default_factory=dict)


@app.get("/")
async def root():
    return {"ok": True, "service": "worldforge-backend", "version": "7.0.0"}


@app.get("/config")
async def get_config():
    return {
        "endpoint": f"{BASE_URL.rstrip('/')}/roblox/worldgen"
    }


def search_creator_store_assets(
    keyword: str,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """
    Search Roblox Creator Store / Toolbox models.
    This uses Roblox's toolbox-service search endpoint, which may evolve over time.
    Keep this server-side so you can adjust filters without changing the plugin.
    """
    params = {
        "keyword": keyword,
        "limit": limit,
        "includeOnlyVerifiedCreators": "false",
    }

    try:
        response = requests.get(ROBLOX_SEARCH_URL, params=params, timeout=12)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"[WorldForge] asset search failed for '{keyword}': {exc}")
        return []

    results: List[Dict[str, Any]] = []
    for item in payload.get("data", []):
        asset_id = item.get("asset", {}).get("id") or item.get("id")
        name = item.get("asset", {}).get("name") or item.get("name") or keyword
        creator = item.get("creator", {}).get("name", "")
        if not asset_id:
            continue

        results.append(
            {
                "assetId": int(asset_id),
                "name": name,
                "creator": creator,
                "keyword": keyword,
            }
        )

    return results


def pick_assets_for_prompt(prompt: str, biome: str) -> List[Dict[str, Any]]:
    text = f"{prompt} {biome}".lower()

    queries: List[str] = []

    if "village" in text or "town" in text:
        queries += ["fantasy village house", "wooden house", "market stall"]
    if "forest" in text or "tree" in text or biome in {"forest", "plains"}:
        queries += ["tree", "pine tree", "bush"]
    if "rock" in text or "cave" in text or biome in {"mountain", "volcano"}:
        queries += ["rock", "boulder", "cave entrance"]
    if "fantasy" in text:
        queries += ["fantasy prop", "fantasy lamp", "fantasy crate"]
    if "desert" in text or biome == "desert":
        queries += ["cactus", "desert rock", "sandstone ruin"]
    if "snow" in text or biome == "snow":
        queries += ["snow pine tree", "ice rock", "winter cabin"]

    if not queries:
        queries = ["tree", "rock", "wooden house"]

    found: List[Dict[str, Any]] = []
    seen: set[int] = set()

    for query in queries[:6]:
        matches = search_creator_store_assets(query, limit=5)
        for match in matches:
            asset_id = match["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            found.append(
                {
                    "assetId": asset_id,
                    "query": query,
                    # plugin can pivot these where needed
                    "position": {"x": 0, "y": 4, "z": 0},
                }
            )
            if len(found) >= 10:
                return found

    return found


def make_terrain(size: str, biome: str) -> List[Dict[str, Any]]:
    size_map = {
        "small": 192,
        "medium": 320,
        "large": 512,
    }
    span = size_map.get(size, 320)

    top_material = {
        "forest": "Grass",
        "plains": "Grass",
        "desert": "Sand",
        "snow": "Snow",
        "mountain": "Rock",
        "volcano": "Basalt",
    }.get(biome, "Grass")

    terrain: List[Dict[str, Any]] = [
        {
            "kind": "FillBlock",
            "position": {"x": 0, "y": -8, "z": 0},
            "size": {"x": span, "y": 16, "z": span},
            "material": top_material,
        },
        {
            "kind": "FillBall",
            "position": {"x": -55, "y": 28, "z": -30},
            "radius": 44,
            "material": "Rock" if biome != "desert" else "Sandstone",
        },
        {
            "kind": "FillBall",
            "position": {"x": 70, "y": 20, "z": 15},
            "radius": 34,
            "material": top_material,
        },
    ]

    if "cave" in biome or biome in {"mountain", "volcano"}:
        terrain.append(
            {
                "kind": "ClearSphere",
                "position": {"x": -45, "y": 22, "z": -25},
                "radius": 18,
            }
        )

    return terrain


def make_scripts(prompt: str) -> List[Dict[str, str]]:
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
            "source": (
                "print('WorldForge NPC content created. Add your own prompts or dialogue UI here.')\n"
            ),
        },
    ]


def make_npc_content(prompt: str) -> List[Dict[str, Any]]:
    npc_name = random.choice(["Elda", "Torren", "Mira", "Bram", "Liora"])
    quest_title = random.choice(
        [
            "Find the Missing Relic",
            "Gather Forest Supplies",
            "Explore the Cave Entrance",
            "Deliver a Village Message",
        ]
    )

    return [
        {
            "kind": "Part",
            "Name": f"{npc_name}_Marker",
            "Shape": "Cylinder",
            "Position": {"x": 14, "y": 3, "z": 10},
            "Size": {"x": 4, "y": 1, "z": 4},
            "Material": "Neon",
            "Color": {"r": 255, "g": 220, "b": 80},
        },
        {
            "kind": "Model",
            "Name": f"{npc_name}_QuestSign",
            "parts": [
                {
                    "kind": "Part",
                    "Name": "Post",
                    "Position": {"x": 18, "y": 4, "z": 10},
                    "Size": {"x": 1, "y": 6, "z": 1},
                    "Material": "Wood",
                    "Color": {"r": 120, "g": 85, "b": 60},
                },
                {
                    "kind": "Part",
                    "Name": "Board",
                    "Position": {"x": 18, "y": 7, "z": 10},
                    "Size": {"x": 5, "y": 3, "z": 1},
                    "Material": "WoodPlanks",
                    "Color": {"r": 150, "g": 115, "b": 75},
                },
            ],
        },
    ]


@app.post("/roblox/worldgen")
async def roblox_worldgen(body: GenerateRequest):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    biome = body.biome or "plains"
    size = body.size or "medium"

    store_assets = pick_assets_for_prompt(prompt, biome)

    plan: Dict[str, Any] = {
        "folders": ["Gameplay", "Spawns", "Decor", "GeneratedScripts"],
        "lighting": {
            "ClockTime": 15,
            "Brightness": 2,
            "FogStart": 100,
            "FogEnd": 700,
            "Ambient": {"r": 110, "g": 100, "b": 100},
            "OutdoorAmbient": {"r": 140, "g": 130, "b": 130},
        },
        "terrain": make_terrain(size, biome) if body.capabilities.get("terrain", True) else [],
        "primitiveProps": [
            {
                "kind": "Part",
                "Name": "SpawnPad",
                "Shape": "Cylinder",
                "Position": {"x": 0, "y": 3, "z": 0},
                "Size": {"x": 12, "y": 1, "z": 12},
                "Material": "Neon",
                "Color": {"r": 0, "g": 170, "b": 255},
            }
        ],
        "storeAssets": store_assets if body.capabilities.get("props", True) else [],
        "scripts": make_scripts(prompt) if body.capabilities.get("scripts", True) else [],
        "selectionTargets": ["SpawnPad"],
    }

    if body.capabilities.get("npcs", True):
        plan["primitiveProps"].extend(make_npc_content(prompt))

    return plan
