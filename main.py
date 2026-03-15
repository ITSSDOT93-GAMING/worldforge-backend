import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://worldforge-backend-production.up.railway.app").rstrip("/")
ROBLOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"
ASSET_PACKS_PATH = Path(__file__).with_name("asset_packs.json")
ENABLE_LIVE_SEARCH = os.getenv("ENABLE_LIVE_SEARCH", "false").lower() == "true"

RATE_BUCKET: dict[str, list[float]] = {}
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1500)
    template: str = "adventure"
    size: str = "medium"
    biome: str = "forest"
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
    return {"ok": True, "service": "worldforge-backend", "version": "11.0.0"}


@app.get("/config")
async def get_config():
    return {"endpoint": f"{PUBLIC_BASE_URL}/roblox/worldgen"}


def rgb(r: int, g: int, b: int) -> Dict[str, int]:
    return {"r": int(r), "g": int(g), "b": int(b)}


def vec(x: float, y: float, z: float) -> Dict[str, float]:
    return {"x": float(x), "y": float(y), "z": float(z)}


def safe_material(name: str) -> str:
    allowed = {
        "Grass", "Ground", "Rock", "Slate", "Sand", "Snow", "Mud",
        "Basalt", "Wood", "WoodPlanks", "Cobblestone", "Concrete",
        "Glass", "Neon", "Fabric", "Brick", "Limestone", "LeafyGrass",
        "Water",
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
        "Material": safe_material(material),
        "Color": rgb(*color),
    }


def model(name: str, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"kind": "Model", "Name": name, "parts": parts}


def size_settings(size: str) -> Dict[str, Any]:
    size = size.lower()
    if size == "small":
        return {"span": 320, "zone_distance": 130, "house_count": 4, "tree_count": 10, "rock_count": 8}
    if size == "large":
        return {"span": 760, "zone_distance": 260, "house_count": 10, "tree_count": 32, "rock_count": 22}
    return {"span": 520, "zone_distance": 190, "house_count": 7, "tree_count": 20, "rock_count": 14}


def density_multiplier(density: str) -> float:
    density = density.lower()
    if density == "sparse":
        return 0.7
    if density == "dense":
        return 1.65
    return 1.0


def biome_style(biome: str) -> Dict[str, Any]:
    biome = biome.lower()
    if biome == "snow":
        return {
            "ground": "Snow",
            "secondary_ground": "Slate",
            "rock": "Slate",
            "tree_leaves": (220, 235, 220),
            "ambient": rgb(105, 110, 125),
            "outdoor": rgb(140, 145, 160),
            "clock": 13,
            "theme": "winter",
        }
    if biome == "desert":
        return {
            "ground": "Sand",
            "secondary_ground": "Sand",
            "rock": "Limestone",
            "tree_leaves": (130, 170, 90),
            "ambient": rgb(115, 105, 90),
            "outdoor": rgb(150, 140, 120),
            "clock": 15,
            "theme": "desert",
        }
    if biome == "mountain":
        return {
            "ground": "Rock",
            "secondary_ground": "Slate",
            "rock": "Slate",
            "tree_leaves": (80, 130, 80),
            "ambient": rgb(95, 95, 105),
            "outdoor": rgb(125, 125, 135),
            "clock": 14,
            "theme": "mountain",
        }
    if biome == "swamp":
        return {
            "ground": "Mud",
            "secondary_ground": "Grass",
            "rock": "Rock",
            "tree_leaves": (75, 110, 65),
            "ambient": rgb(85, 95, 80),
            "outdoor": rgb(110, 120, 95),
            "clock": 16,
            "theme": "swamp",
        }
    if biome == "plains":
        return {
            "ground": "Grass",
            "secondary_ground": "Ground",
            "rock": "Rock",
            "tree_leaves": (90, 170, 85),
            "ambient": rgb(100, 100, 105),
            "outdoor": rgb(130, 130, 140),
            "clock": 14,
            "theme": "plains",
        }
    return {
        "ground": "Grass",
        "secondary_ground": "Ground",
        "rock": "Rock",
        "tree_leaves": (85, 150, 80),
        "ambient": rgb(100, 100, 110),
        "outdoor": rgb(130, 130, 140),
        "clock": 15,
        "theme": "forest",
    }


def load_asset_packs() -> Dict[str, Any]:
    if not ASSET_PACKS_PATH.exists():
        return {}
    try:
        with ASSET_PACKS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def path_block(x: float, z: float, width: float = 14, length: float = 40, material: str = "Ground") -> Dict[str, Any]:
    return {
        "kind": "FillBlock",
        "position": vec(x, 1, z),
        "size": vec(width, 2, length),
        "material": material,
    }


def terrain_for_world(size: str, biome: str, template: str) -> List[Dict[str, Any]]:
    s = size_settings(size)
    b = biome_style(biome)
    span = s["span"]
    zone = s["zone_distance"]
    terrain: List[Dict[str, Any]] = [
        {"kind": "FillBlock", "position": vec(0, -8, 0), "size": vec(span, 16, span), "material": b["ground"]},
        {"kind": "FillBall", "position": vec(-zone, 30, -zone * 0.5), "radius": 60, "material": b["rock"]},
        {"kind": "FillBall", "position": vec(zone * 0.95, 20, zone * 0.6), "radius": 44, "material": b["secondary_ground"]},
        {"kind": "FillBall", "position": vec(zone * 0.35, 18, -zone * 0.82), "radius": 34, "material": b["secondary_ground"]},
        {"kind": "ClearSphere", "position": vec(-zone, 26, -zone * 0.5), "radius": 28},
        path_block(0, 0, 18, 70, "Ground"),
        path_block(0, 70, 18, 120, "Ground"),
        {"kind": "FillBlock", "position": vec(0, 1, zone), "size": vec(18, 2, 160), "material": "Ground"},
        {"kind": "FillBlock", "position": vec(zone * 0.35, 1, zone * 0.45), "size": vec(110, 2, 18), "material": "Ground"},
        {"kind": "FillBlock", "position": vec(-zone * 0.35, 1, zone * 0.25), "size": vec(95, 2, 18), "material": "Ground"},
    ]
    if template.lower() in {"adventure", "survival"}:
        terrain.append({"kind": "FillBlock", "position": vec(zone * 0.35, -1, zone * 0.45), "size": vec(120, 6, 30), "material": "Water"})
    if biome.lower() in {"mountain", "snow"}:
        terrain.extend([
            {"kind": "FillBall", "position": vec(-zone * 0.8, 44, -zone * 0.7), "radius": 62, "material": b["rock"]},
            {"kind": "ClearSphere", "position": vec(-zone * 0.82, 36, -zone * 0.66), "radius": 30},
        ])
    return terrain


def market_stall(name: str, x: float, z: float, color: Tuple[int, int, int]) -> Dict[str, Any]:
    return model(name, [
        part("Top", (x, 6, z), (10, 1, 6), "Fabric", color),
        part("Pole1", (x - 4, 3, z - 2), (1, 6, 1), "Wood", (95, 70, 50)),
        part("Pole2", (x + 4, 3, z - 2), (1, 6, 1), "Wood", (95, 70, 50)),
        part("Pole3", (x - 4, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
        part("Pole4", (x + 4, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
        part("Counter", (x, 2, z), (10, 2, 6), "WoodPlanks", (145, 110, 75)),
    ])


def tree_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    leaves = style["tree_leaves"]
    return model(name, [
        part("Trunk", (x, 6, z), (2, 12, 2), "Wood", (110, 82, 55)),
        part("Leaves", (x, 14, z), (10, 8, 10), "Grass", leaves),
        part("LeavesTop", (x, 19, z), (7, 5, 7), "Grass", leaves),
    ])


def rock_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [part("Rock", (x, 3, z), (6, 6, 6), style["rock"], (120, 120, 125), "Ball")])


def lamp_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("Post", (x, 4, z), (1, 8, 1), "Wood", (95, 70, 50)),
        part("Light", (x, 9, z), (2, 2, 2), "Neon", (255, 220, 120)),
    ])


def crate_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [part("Crate", (x, 1.5, z), (3, 3, 3), "WoodPlanks", (140, 105, 70))])


def chest_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("Base", (x, 1.5, z), (4, 3, 3), "WoodPlanks", (125, 90, 55)),
        part("Lid", (x, 3.5, z), (4, 1.5, 3), "Wood", (100, 70, 45)),
        part("Trim", (x, 2.2, z + 1.55), (1, 1, 0.2), "Neon", (255, 215, 60)),
    ])


def quest_board(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("PostA", (x - 1.5, 3, z), (1, 6, 1), "Wood", (95, 70, 50)),
        part("PostB", (x + 1.5, 3, z), (1, 6, 1), "Wood", (95, 70, 50)),
        part("Board", (x, 6, z), (8, 4, 1), "WoodPlanks", (160, 125, 85)),
    ])


def npc_marker(name: str, x: float, z: float, color: Tuple[int, int, int]) -> Dict[str, Any]:
    return part(name, (x, 2, z), (3, 1, 3), "Neon", color, "Cylinder")


def bridge_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("Deck", (x, 2.5, z), (26, 1, 10), "WoodPlanks", (150, 110, 75)),
        part("RailL", (x - 12, 4, z), (1, 3, 10), "Wood", (95, 70, 50)),
        part("RailR", (x + 12, 4, z), (1, 3, 10), "Wood", (95, 70, 50)),
    ])


def ruin_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(name, [
        part("WallA", (x - 6, 5, z), (2, 10, 14), "Cobblestone", (125, 125, 125)),
        part("WallB", (x + 6, 5, z), (2, 10, 14), "Cobblestone", (125, 125, 125)),
        part("Back", (x, 5, z - 6), (14, 10, 2), "Cobblestone", (125, 125, 125)),
        part("Pillar", (x, 7, z + 5), (2, 14, 2), "Cobblestone", (135, 135, 135)),
    ])


def cave_entrance_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    return model(name, [
        part("RockLeft", (x - 8, 7, z), (10, 14, 8), style["rock"], (110, 110, 115)),
        part("RockRight", (x + 8, 7, z), (10, 14, 8), style["rock"], (110, 110, 115)),
        part("RockTop", (x, 13, z), (18, 6, 8), style["rock"], (110, 110, 115)),
        part("TorchLeft", (x - 10, 4, z + 4), (1, 8, 1), "Wood", (95, 70, 50)),
        part("TorchRight", (x + 10, 4, z + 4), (1, 8, 1), "Wood", (95, 70, 50)),
        part("Marker", (x, 2, z + 2), (8, 1, 4), "Neon", (180, 120, 255)),
    ])


def camp_zone(zone: float) -> List[Dict[str, Any]]:
    return [
        model("SpawnTent_A", [
            part("TentBase", (-12, 2, zone), (10, 4, 8), "Fabric", (170, 140, 90)),
            part("TentPole", (-12, 5, zone), (1, 6, 1), "Wood", (95, 70, 50)),
        ]),
        model("SpawnTent_B", [
            part("TentBase", (12, 2, zone), (10, 4, 8), "Fabric", (140, 160, 90)),
            part("TentPole", (12, 5, zone), (1, 6, 1), "Wood", (95, 70, 50)),
        ]),
        crate_model("CampCrate_A", -6, zone - 10),
        crate_model("CampCrate_B", 6, zone - 8),
        npc_marker("NPC_Guide", 0, zone + 14, (120, 255, 120)),
        quest_board("CampBoard", 0, zone + 28),
    ]


def village_support_props(zone: float) -> List[Dict[str, Any]]:
    return [
        market_stall("MarketRed", -18, zone + 28, (180, 70, 70)),
        market_stall("MarketBlue", 18, zone + 28, (70, 110, 180)),
        quest_board("QuestBoard_Main", 0, zone + 44),
        npc_marker("NPC_QuestGiver", 0, zone + 18, (255, 220, 80)),
        npc_marker("NPC_Merchant", -18, zone + 20, (80, 220, 255)),
        npc_marker("NPC_Guard", 22, zone + 20, (255, 120, 120)),
        lamp_model("VillageLamp_A", -20, zone - 6),
        lamp_model("VillageLamp_B", 20, zone - 6),
        lamp_model("VillageLamp_C", -20, zone + 62),
        lamp_model("VillageLamp_D", 20, zone + 62),
        crate_model("VillageCrate_A", -10, zone + 36),
        crate_model("VillageCrate_B", 10, zone + 36),
        chest_model("VillageRewardChest", 0, zone + 72),
    ]


def filler_trees(style: Dict[str, Any], count: int, radius: float, name_prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(count):
        angle = (math.pi * 2) * (i / max(count, 1))
        x = math.cos(angle) * radius + random.randint(-18, 18)
        z = math.sin(angle) * radius + random.randint(-18, 18)
        if abs(x) < 55 and abs(z) < 55:
            z += 90
        out.append(tree_model(f"{name_prefix}_{i}", x, z, style))
    return out


def filler_rocks(style: Dict[str, Any], count: int, radius: float, name_prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(count):
        x = random.randint(int(-radius), int(radius))
        z = random.randint(int(-radius), int(radius))
        if abs(x) < 55 and abs(z) < 55:
            z += 90
        out.append(rock_model(f"{name_prefix}_{i}", x, z, style))
    return out


def house_positions_for_zone(zone: float, count: int) -> List[Tuple[float, float, float]]:
    positions = [
        (-50, 4, zone), (-24, 4, zone + 18), (0, 4, zone), (26, 4, zone + 16), (52, 4, zone),
        (-38, 4, zone + 46), (-8, 4, zone + 56), (22, 4, zone + 48), (52, 4, zone + 58),
        (-70, 4, zone + 76), (74, 4, zone + 80),
    ]
    return positions[:count]


def curated_assets_for(theme: str, category: str) -> List[int]:
    packs = load_asset_packs()
    theme_pack = packs.get(theme, {})
    shared_pack = packs.get("shared", {})
    values = theme_pack.get(category, []) or shared_pack.get(category, []) or []
    return [int(v) for v in values if isinstance(v, int) or (isinstance(v, str) and v.isdigit())]


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
        results.append({"assetId": int(asset_id)})
    return results


def searched_house_ids(theme: str, count: int) -> List[int]:
    if not ENABLE_LIVE_SEARCH:
        return []
    queries = [f"{theme} house", f"{theme} building", f"{theme} cottage", f"{theme} village house"]
    seen: set[int] = set()
    out: List[int] = []
    for query in queries:
        for item in search_creator_store_assets(query, 6):
            asset_id = item["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            out.append(asset_id)
            if len(out) >= count:
                return out
    return out


def place_asset_ids(asset_ids: List[int], positions: List[Tuple[float, float, float]], category: str) -> List[Dict[str, Any]]:
    placed: List[Dict[str, Any]] = []
    for i, pos in enumerate(positions):
        if i >= len(asset_ids):
            break
        placed.append({
            "assetId": asset_ids[i],
            "position": vec(*pos),
            "category": category,
        })
    return placed


def support_asset_queries(prompt: str, biome: str, template: str) -> List[str]:
    text = f"{prompt} {biome} {template}".lower()
    queries: List[str] = []
    if "bridge" in text:
        queries.append("bridge")
    if "ruin" in text:
        queries.append("ruin")
    if biome in {"forest", "plains", "swamp"}:
        queries.append("tree")
    if template == "dungeon" or "cave" in text:
        queries.append("cave")
    return queries[:4]


def live_support_assets(prompt: str, biome: str, template: str, density: str) -> List[Dict[str, Any]]:
    if not ENABLE_LIVE_SEARCH:
        return []
    max_assets = 3 if density == "sparse" else 6 if density == "normal" else 8
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for query in support_asset_queries(prompt, biome, template):
        for item in search_creator_store_assets(query, 3):
            asset_id = item["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            out.append({"assetId": asset_id, "position": vec(0, 4, 0), "category": "support"})
            if len(out) >= max_assets:
                return out
    return out


def adventure_layout(style: Dict[str, Any], size: str, density: str) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)
    props: List[Dict[str, Any]] = []
    props.extend(camp_zone(0))
    props.extend(village_support_props(zone))
    props.extend([
        bridge_model("Bridge_Main", zone * 0.35, zone * 0.45),
        cave_entrance_model("CaveEntrance", -zone, -zone * 0.5, style),
        ruin_model("AncientRuins", zone * 0.72, zone * 0.58),
        chest_model("RewardChest", zone * 0.78, zone * 0.66),
        npc_marker("NPC_Explorer", zone * 0.65, zone * 0.54, (180, 140, 255)),
    ])
    props.extend(filler_trees(style, int(s["tree_count"] * mult), s["span"] * 0.42, "Tree"))
    props.extend(filler_rocks(style, int(s["rock_count"] * mult), s["span"] * 0.38, "Rock"))
    return props, house_positions_for_zone(zone, s["house_count"])


def survival_layout(style: Dict[str, Any], size: str, density: str) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)
    props: List[Dict[str, Any]] = []
    props.extend(camp_zone(0))
    props.extend([
        crate_model("SupplyCrate_1", -20, 22), crate_model("SupplyCrate_2", 20, 22),
        chest_model("StarterChest", 0, 38), npc_marker("NPC_Survivor", 0, 18, (255, 220, 80)),
        bridge_model("RiverBridge", zone * 0.35, zone * 0.45), cave_entrance_model("ForageCave", -zone, -zone * 0.5, style),
    ])
    props.extend(village_support_props(zone))
    props.extend(filler_trees(style, int(s["tree_count"] * 1.2 * mult), s["span"] * 0.45, "Tree"))
    props.extend(filler_rocks(style, int(s["rock_count"] * 1.25 * mult), s["span"] * 0.4, "Rock"))
    return props, house_positions_for_zone(zone, max(3, s["house_count"] - 1))


def village_layout(style: Dict[str, Any], size: str, density: str) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]]]:
    s = size_settings(size)
    mult = density_multiplier(density)
    zone = 40
    props = village_support_props(zone)
    props.extend([
        market_stall("MarketGold", -32, 74, (180, 150, 60)),
        market_stall("MarketGreen", 32, 74, (80, 160, 90)),
        chest_model("TownRewardChest", 0, 100),
    ])
    props.extend(filler_trees(style, int(s["tree_count"] * mult), s["span"] * 0.4, "Tree"))
    props.extend(filler_rocks(style, int(s["rock_count"] * mult), s["span"] * 0.35, "Rock"))
    return props, house_positions_for_zone(zone, s["house_count"])


def dungeon_layout(style: Dict[str, Any], size: str, density: str) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)
    props: List[Dict[str, Any]] = [
        camp_zone(0)[0], camp_zone(0)[1],
        npc_marker("NPC_DungeonGuide", 0, 16, (255, 180, 80)),
        quest_board("DungeonBoard", 0, 32),
        cave_entrance_model("DungeonEntrance", -zone * 0.7, -40, style),
        ruin_model("OuterRuins_A", 30, zone * 0.4),
        ruin_model("OuterRuins_B", -30, zone * 0.55),
        chest_model("DungeonRewardChest", 0, zone * 0.65),
        crate_model("DungeonSupply_A", -16, 10), crate_model("DungeonSupply_B", 16, 12),
    ]
    props.extend(filler_trees(style, int(s["tree_count"] * 0.7 * mult), s["span"] * 0.4, "Tree"))
    props.extend(filler_rocks(style, int(s["rock_count"] * 1.5 * mult), s["span"] * 0.4, "Rock"))
    return props, house_positions_for_zone(70, max(2, s["house_count"] - 3))


def choose_layout(template: str, size: str, biome: str, density: str) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]]]:
    style = biome_style(biome)
    template = template.lower()
    if template == "survival":
        return survival_layout(style, size, density)
    if template == "village":
        return village_layout(style, size, density)
    if template == "dungeon":
        return dungeon_layout(style, size, density)
    return adventure_layout(style, size, density)


def script_bundle(template: str) -> List[Dict[str, str]]:
    quest_text = {
        "adventure": "Explore the ruins, then return to the village.",
        "survival": "Gather supplies from the area and return safely.",
        "village": "Help the townsfolk by checking the quest board.",
        "dungeon": "Prepare, then enter the dungeon when ready.",
    }.get(template.lower(), "Explore the world and talk to the NPCs.")
    return [
        {"className": "Script", "name": "AmbientCycle", "source": "local Lighting = game:GetService('Lighting')\nwhile task.wait(8) do\n    Lighting.ClockTime = (Lighting.ClockTime + 0.08) % 24\nend\n"},
        {"className": "ModuleScript", "name": "WorldForgeQuestData", "source": f"return {{\n    MainQuest = {repr(quest_text)},\n    Rewards = {{ Gold = 100, XP = 25 }},\n}}\n"},
        {"className": "Script", "name": "WorldForgeInfo", "source": "print('WorldForge generated this map. Add your own dialogue, UI, enemies, and quest logic on top of the generated layout.')\n"},
    ]


def selection_targets() -> List[str]:
    return ["SpawnPad", "NPC_QuestGiver", "QuestBoard_Main"]


@app.post("/roblox/worldgen")
async def roblox_worldgen(body: GenerateRequest):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    template = (body.template or "adventure").lower()
    size = (body.size or "medium").lower()
    biome = (body.biome or "forest").lower()
    density = (body.density or "normal").lower()
    caps = body.capabilities or {}
    style = biome_style(biome)

    primitive_props: List[Dict[str, Any]] = []
    store_assets: List[Dict[str, Any]] = []
    layout_props, house_positions = choose_layout(template, size, biome, density)

    if caps.get("props", True):
        primitive_props.append(part("SpawnPad", (0, 3, 0), (14, 1, 14), "Neon", (0, 170, 255), "Cylinder"))
        primitive_props.extend(layout_props)

        theme = style["theme"]
        curated_house_ids = curated_assets_for(theme, "houses")
        if len(curated_house_ids) < len(house_positions):
            curated_house_ids.extend(curated_assets_for("shared", "houses"))
        if len(curated_house_ids) < len(house_positions):
            curated_house_ids.extend(searched_house_ids(theme, len(house_positions) - len(curated_house_ids)))
        store_assets.extend(place_asset_ids(curated_house_ids, house_positions, "houses"))

        curated_landmarks = curated_assets_for(theme, "landmarks") + curated_assets_for("shared", "landmarks")
        landmark_positions = [(-size_settings(size)["zone_distance"], 4, -size_settings(size)["zone_distance"] * 0.5)]
        store_assets.extend(place_asset_ids(curated_landmarks, landmark_positions, "landmarks"))

        store_assets.extend(live_support_assets(prompt, biome, template, density))

    if not caps.get("npcs", True):
        primitive_props = [p for p in primitive_props if not str(p.get("Name", "")).startswith("NPC_")]

    plan: Dict[str, Any] = {
        "folders": ["Gameplay", "Spawns", "Decor", "NPCs", "QuestData", "GeneratedScripts"],
        "lighting": {
            "ClockTime": style["clock"],
            "Brightness": 2,
            "FogStart": 90,
            "FogEnd": 980 if size == "large" else 760,
            "Ambient": style["ambient"],
            "OutdoorAmbient": style["outdoor"],
        } if caps.get("lighting", True) else {},
        "terrain": terrain_for_world(size, biome, template) if caps.get("terrain", True) else [],
        "primitiveProps": primitive_props,
        "storeAssets": store_assets,
        "scripts": script_bundle(template) if caps.get("scripts", True) else [],
        "selectionTargets": selection_targets(),
    }
    return plan
