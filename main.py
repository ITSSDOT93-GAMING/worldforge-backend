import os
import time
import math
import random
from typing import Any, Dict, List, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

PUBLIC_BASE_URL = "https://worldforge-backend-production.up.railway.app"

ROBLOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/search"

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
    return {"ok": True, "service": "worldforge-backend", "version": "9.0.0"}


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
    return {
        "kind": "Model",
        "Name": name,
        "parts": parts,
    }


def size_settings(size: str) -> Dict[str, Any]:
    size = size.lower()
    if size == "small":
        return {
            "span": 260,
            "zone_distance": 120,
            "extra_houses": 1,
            "extra_trees": 8,
            "extra_rocks": 6,
        }
    if size == "large":
        return {
            "span": 620,
            "zone_distance": 240,
            "extra_houses": 5,
            "extra_trees": 26,
            "extra_rocks": 18,
        }
    return {
        "span": 420,
        "zone_distance": 170,
        "extra_houses": 3,
        "extra_trees": 16,
        "extra_rocks": 10,
    }


def density_multiplier(density: str) -> float:
    density = density.lower()
    if density == "sparse":
        return 0.65
    if density == "dense":
        return 1.75
    return 1.0


def biome_style(biome: str) -> Dict[str, Any]:
    biome = biome.lower()

    if biome == "snow":
        return {
            "ground": "Snow",
            "secondary_ground": "Slate",
            "rock": "Slate",
            "wood": "WoodPlanks",
            "roof": "Brick",
            "water_color": rgb(180, 220, 255),
            "tree_leaves": (220, 235, 220),
            "ambient": rgb(105, 110, 125),
            "outdoor": rgb(140, 145, 160),
            "clock": 13,
        }
    if biome == "desert":
        return {
            "ground": "Sand",
            "secondary_ground": "Sand",
            "rock": "Limestone",
            "wood": "WoodPlanks",
            "roof": "Brick",
            "water_color": rgb(120, 180, 220),
            "tree_leaves": (130, 170, 90),
            "ambient": rgb(115, 105, 90),
            "outdoor": rgb(150, 140, 120),
            "clock": 15,
        }
    if biome == "mountain":
        return {
            "ground": "Rock",
            "secondary_ground": "Slate",
            "rock": "Slate",
            "wood": "WoodPlanks",
            "roof": "Brick",
            "water_color": rgb(130, 170, 210),
            "tree_leaves": (80, 130, 80),
            "ambient": rgb(95, 95, 105),
            "outdoor": rgb(125, 125, 135),
            "clock": 14,
        }
    if biome == "swamp":
        return {
            "ground": "Mud",
            "secondary_ground": "Grass",
            "rock": "Rock",
            "wood": "WoodPlanks",
            "roof": "Brick",
            "water_color": rgb(80, 110, 70),
            "tree_leaves": (75, 110, 65),
            "ambient": rgb(85, 95, 80),
            "outdoor": rgb(110, 120, 95),
            "clock": 16,
        }
    if biome == "plains":
        return {
            "ground": "Grass",
            "secondary_ground": "Ground",
            "rock": "Rock",
            "wood": "WoodPlanks",
            "roof": "Brick",
            "water_color": rgb(110, 170, 230),
            "tree_leaves": (90, 170, 85),
            "ambient": rgb(100, 100, 105),
            "outdoor": rgb(130, 130, 140),
            "clock": 14,
        }
    return {
        "ground": "Grass",
        "secondary_ground": "Ground",
        "rock": "Rock",
        "wood": "WoodPlanks",
        "roof": "Brick",
        "water_color": rgb(110, 170, 230),
        "tree_leaves": (85, 150, 80),
        "ambient": rgb(100, 100, 110),
        "outdoor": rgb(130, 130, 140),
        "clock": 15,
    }


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
        {
            "kind": "FillBlock",
            "position": vec(0, -8, 0),
            "size": vec(span, 16, span),
            "material": b["ground"],
        },
        {
            "kind": "FillBall",
            "position": vec(-zone, 28, -zone * 0.5),
            "radius": 52,
            "material": b["rock"],
        },
        {
            "kind": "FillBall",
            "position": vec(zone * 0.9, 20, zone * 0.6),
            "radius": 44,
            "material": b["secondary_ground"],
        },
        {
            "kind": "FillBall",
            "position": vec(zone * 0.3, 18, -zone * 0.8),
            "radius": 30,
            "material": b["secondary_ground"],
        },
    ]

    # Main roads / paths
    terrain.extend(
        [
            path_block(0, 0, 18, 70, "Ground"),
            path_block(0, 70, 18, 120, "Ground"),
            {
                "kind": "FillBlock",
                "position": vec(0, 1, zone),
                "size": vec(18, 2, 120),
                "material": "Ground",
            },
            {
                "kind": "FillBlock",
                "position": vec(zone * 0.35, 1, zone * 0.45),
                "size": vec(90, 2, 16),
                "material": "Ground",
            },
            {
                "kind": "FillBlock",
                "position": vec(-zone * 0.35, 1, zone * 0.25),
                "size": vec(90, 2, 16),
                "material": "Ground",
            },
        ]
    )

    # Water crossing for adventure/survival
    if template.lower() in {"adventure", "survival"}:
        terrain.append(
            {
                "kind": "FillBlock",
                "position": vec(zone * 0.35, -1, zone * 0.45),
                "size": vec(110, 6, 28),
                "material": "Water",
            }
        )

    # Cave opening area
    terrain.append(
        {
            "kind": "ClearSphere",
            "position": vec(-zone, 24, -zone * 0.5),
            "radius": 18,
        }
    )

    if biome.lower() in {"mountain", "snow"}:
        terrain.extend(
            [
                {
                    "kind": "FillBall",
                    "position": vec(-zone * 0.8, 44, -zone * 0.7),
                    "radius": 58,
                    "material": b["rock"],
                },
                {
                    "kind": "ClearSphere",
                    "position": vec(-zone * 0.82, 36, -zone * 0.66),
                    "radius": 22,
                },
            ]
        )

    return terrain


def house_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Base", (x, 2.5, z), (18, 5, 18), style["wood"], (150, 110, 75)),
            part("Roof", (x, 8.5, z), (20, 4, 20), style["roof"], (110, 55, 50)),
            part("Door", (x, 4, z + 9.1), (3, 6, 1), "Wood", (90, 65, 45)),
            part("WindowLeft", (x - 5, 6, z + 9.2), (3, 3, 1), "Glass", (120, 190, 255)),
            part("WindowRight", (x + 5, 6, z + 9.2), (3, 3, 1), "Glass", (120, 190, 255)),
        ],
    )


def market_stall(name: str, x: float, z: float, color: Tuple[int, int, int]) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Top", (x, 6, z), (10, 1, 6), "Fabric", color),
            part("Pole1", (x - 4, 3, z - 2), (1, 6, 1), "Wood", (95, 70, 50)),
            part("Pole2", (x + 4, 3, z - 2), (1, 6, 1), "Wood", (95, 70, 50)),
            part("Pole3", (x - 4, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
            part("Pole4", (x + 4, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
            part("Counter", (x, 2, z), (10, 2, 6), "WoodPlanks", (145, 110, 75)),
        ],
    )


def tree_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    leaves = style["tree_leaves"]
    return model(
        name,
        [
            part("Trunk", (x, 6, z), (2, 12, 2), "Wood", (110, 82, 55)),
            part("Leaves", (x, 14, z), (10, 8, 10), "Grass", leaves),
            part("LeavesTop", (x, 19, z), (7, 5, 7), "Grass", leaves),
        ],
    )


def rock_model(name: str, x: float, z: float, style: Dict[str, Any]) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Rock", (x, 3, z), (6, 6, 6), style["rock"], (120, 120, 125), "Ball"),
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
        [
            part("Crate", (x, 1.5, z), (3, 3, 3), "WoodPlanks", (140, 105, 70)),
        ],
    )


def chest_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [
            part("Base", (x, 1.5, z), (4, 3, 3), "WoodPlanks", (125, 90, 55)),
            part("Lid", (x, 3.5, z), (4, 1.5, 3), "Wood", (100, 70, 45)),
            part("Trim", (x, 2.2, z + 1.55), (1, 1, 0.2), "Neon", (255, 215, 60)),
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


def npc_marker(name: str, x: float, z: float, color: Tuple[int, int, int]) -> Dict[str, Any]:
    return part(name, (x, 2, z), (3, 1, 3), "Neon", color, "Cylinder")


def bridge_model(name: str, x: float, z: float) -> Dict[str, Any]:
    parts = [
        part("Deck", (x, 2.5, z), (26, 1, 10), "WoodPlanks", (150, 110, 75)),
        part("RailL", (x - 12, 4, z), (1, 3, 10), "Wood", (95, 70, 50)),
        part("RailR", (x + 12, 4, z), (1, 3, 10), "Wood", (95, 70, 50)),
    ]
    return model(name, parts)


def ruin_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [
            part("WallA", (x - 6, 5, z), (2, 10, 14), "Cobblestone", (125, 125, 125)),
            part("WallB", (x + 6, 5, z), (2, 10, 14), "Cobblestone", (125, 125, 125)),
            part("Back", (x, 5, z - 6), (14, 10, 2), "Cobblestone", (125, 125, 125)),
            part("Pillar", (x, 7, z + 5), (2, 14, 2), "Cobblestone", (135, 135, 135)),
        ],
    )


def cave_marker_model(name: str, x: float, z: float) -> Dict[str, Any]:
    return model(
        name,
        [
            part("EntranceMarker", (x, 4, z), (10, 8, 2), "Neon", (180, 120, 255)),
            part("TorchL", (x - 6, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
            part("TorchR", (x + 6, 3, z + 2), (1, 6, 1), "Wood", (95, 70, 50)),
        ],
    )


def filler_trees(style: Dict[str, Any], count: int, radius: float, name_prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(count):
        angle = (math.pi * 2) * (i / max(count, 1))
        wobble = random.randint(-18, 18)
        x = math.cos(angle) * radius + wobble
        z = math.sin(angle) * radius + random.randint(-18, 18)
        if abs(x) < 45 and abs(z) < 45:
            z += 70
        out.append(tree_model(f"{name_prefix}_{i}", x, z, style))
    return out


def filler_rocks(style: Dict[str, Any], count: int, radius: float, name_prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(count):
        x = random.randint(int(-radius), int(radius))
        z = random.randint(int(-radius), int(radius))
        if abs(x) < 50 and abs(z) < 50:
            z += 80
        out.append(rock_model(f"{name_prefix}_{i}", x, z, style))
    return out


def village_zone(style: Dict[str, Any], zone: float, house_count: int) -> List[Dict[str, Any]]:
    props: List[Dict[str, Any]] = []

    base_positions = [
        (-42, zone),
        (0, zone),
        (42, zone),
        (-84, zone + 30),
        (84, zone + 30),
        (-42, zone + 60),
        (42, zone + 60),
    ]

    for i in range(min(house_count, len(base_positions))):
        x, z = base_positions[i]
        props.append(house_model(f"House_{i+1}", x, z, style))

    props.extend(
        [
            market_stall("MarketRed", -20, zone + 18, (180, 70, 70)),
            market_stall("MarketBlue", 20, zone + 18, (70, 110, 180)),
            quest_board("QuestBoard_Main", 0, zone + 32),
            npc_marker("NPC_QuestGiver", 0, zone + 14, (255, 220, 80)),
            npc_marker("NPC_Merchant", -20, zone + 10, (80, 220, 255)),
            npc_marker("NPC_Guard", 22, zone + 10, (255, 120, 120)),
            lamp_model("VillageLamp_A", -16, zone - 10),
            lamp_model("VillageLamp_B", 16, zone - 10),
            lamp_model("VillageLamp_C", -16, zone + 46),
            lamp_model("VillageLamp_D", 16, zone + 46),
            crate_model("VillageCrate_A", -8, zone + 26),
            crate_model("VillageCrate_B", 10, zone + 24),
        ]
    )

    return props


def camp_zone(zone: float) -> List[Dict[str, Any]]:
    return [
        model(
            "SpawnTent_A",
            [
                part("TentBase", (-12, 2, zone), (10, 4, 8), "Fabric", (170, 140, 90)),
                part("TentPole", (-12, 5, zone), (1, 6, 1), "Wood", (95, 70, 50)),
            ],
        ),
        model(
            "SpawnTent_B",
            [
                part("TentBase", (12, 2, zone), (10, 4, 8), "Fabric", (140, 160, 90)),
                part("TentPole", (12, 5, zone), (1, 6, 1), "Wood", (95, 70, 50)),
            ],
        ),
        crate_model("CampCrate_A", -6, zone - 10),
        crate_model("CampCrate_B", 6, zone - 8),
        npc_marker("NPC_Guide", 0, zone + 14, (120, 255, 120)),
        quest_board("CampBoard", 0, zone + 28),
    ]


def adventure_layout(style: Dict[str, Any], size: str, density: str) -> List[Dict[str, Any]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)

    house_count = 3 + s["extra_houses"]
    tree_count = int(s["extra_trees"] * mult)
    rock_count = int(s["extra_rocks"] * mult)

    props: List[Dict[str, Any]] = []
    props.extend(camp_zone(0))
    props.extend(village_zone(style, zone, house_count))
    props.extend(
        [
            bridge_model("Bridge_Main", zone * 0.35, zone * 0.45),
            cave_marker_model("CaveEntrance", -zone, -zone * 0.5),
            ruin_model("AncientRuins", zone * 0.7, zone * 0.55),
            chest_model("RewardChest", zone * 0.72, zone * 0.62),
            npc_marker("NPC_Explorer", zone * 0.65, zone * 0.5, (180, 140, 255)),
        ]
    )
    props.extend(filler_trees(style, tree_count, s["span"] * 0.42, "Tree"))
    props.extend(filler_rocks(style, rock_count, s["span"] * 0.38, "Rock"))
    return props


def survival_layout(style: Dict[str, Any], size: str, density: str) -> List[Dict[str, Any]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)

    props: List[Dict[str, Any]] = []
    props.extend(camp_zone(0))
    props.extend(
        [
            crate_model("SupplyCrate_1", -20, 22),
            crate_model("SupplyCrate_2", 20, 22),
            chest_model("StarterChest", 0, 38),
            npc_marker("NPC_Survivor", 0, 18, (255, 220, 80)),
            bridge_model("RiverBridge", zone * 0.35, zone * 0.45),
            cave_marker_model("ForageCave", -zone, -zone * 0.5),
        ]
    )
    props.extend(village_zone(style, zone, 2 + s["extra_houses"]))
    props.extend(filler_trees(style, int(s["extra_trees"] * 1.2 * mult), s["span"] * 0.45, "Tree"))
    props.extend(filler_rocks(style, int(s["extra_rocks"] * 1.25 * mult), s["span"] * 0.4, "Rock"))
    return props


def village_layout(style: Dict[str, Any], size: str, density: str) -> List[Dict[str, Any]]:
    s = size_settings(size)
    mult = density_multiplier(density)
    house_count = 5 + s["extra_houses"]

    props = village_zone(style, 40, house_count)
    props.extend(
        [
            market_stall("MarketGold", -32, 74, (180, 150, 60)),
            market_stall("MarketGreen", 32, 74, (80, 160, 90)),
            chest_model("TownRewardChest", 0, 100),
        ]
    )
    props.extend(filler_trees(style, int(s["extra_trees"] * mult), s["span"] * 0.4, "Tree"))
    props.extend(filler_rocks(style, int(s["extra_rocks"] * mult), s["span"] * 0.35, "Rock"))
    return props


def dungeon_layout(style: Dict[str, Any], size: str, density: str) -> List[Dict[str, Any]]:
    s = size_settings(size)
    zone = s["zone_distance"]
    mult = density_multiplier(density)

    props: List[Dict[str, Any]] = [
        camp_zone(0)[0],
        camp_zone(0)[1],
        npc_marker("NPC_DungeonGuide", 0, 16, (255, 180, 80)),
        quest_board("DungeonBoard", 0, 32),
        cave_marker_model("DungeonEntrance", -zone * 0.7, -40),
        ruin_model("OuterRuins_A", 30, zone * 0.4),
        ruin_model("OuterRuins_B", -30, zone * 0.55),
        chest_model("DungeonRewardChest", 0, zone * 0.65),
        crate_model("DungeonSupply_A", -16, 10),
        crate_model("DungeonSupply_B", 16, 12),
    ]
    props.extend(filler_trees(style, int(s["extra_trees"] * 0.7 * mult), s["span"] * 0.4, "Tree"))
    props.extend(filler_rocks(style, int(s["extra_rocks"] * 1.5 * mult), s["span"] * 0.4, "Rock"))
    return props


def choose_props(template: str, size: str, biome: str, density: str) -> List[Dict[str, Any]]:
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
        {
            "className": "Script",
            "name": "AmbientCycle",
            "source": (
                "local Lighting = game:GetService('Lighting')\n"
                "while task.wait(8) do\n"
                "    Lighting.ClockTime = (Lighting.ClockTime + 0.08) % 24\n"
                "end\n"
            ),
        },
        {
            "className": "ModuleScript",
            "name": "WorldForgeQuestData",
            "source": (
                "return {\n"
                f"    MainQuest = {repr(quest_text)},\n"
                "    Rewards = { Gold = 100, XP = 25 },\n"
                "}\n"
            ),
        },
        {
            "className": "Script",
            "name": "WorldForgeInfo",
            "source": (
                "print('WorldForge generated this map. Add your own dialogue, UI, enemies, and quest logic on top of the generated layout.')\n"
            ),
        },
    ]


def asset_queries_for_prompt(prompt: str, biome: str, template: str) -> List[str]:
    text = f"{prompt} {biome} {template}".lower()
    queries: List[str] = []

    if "village" in text or template == "village":
        queries += ["wood house", "market stall", "lamp post"]
    if "forest" in text or biome in {"forest", "plains", "swamp"}:
        queries += ["tree", "bush"]
    if "cave" in text or "dungeon" in text or template == "dungeon":
        queries += ["rock", "ruin", "cave"]
    if "bridge" in text:
        queries += ["bridge"]
    if biome == "snow":
        queries += ["snow tree", "winter cabin"]
    if biome == "desert":
        queries += ["cactus", "desert ruin"]

    if not queries:
        queries = ["tree", "rock"]

    return queries[:6]


def search_creator_store_assets(keyword: str, limit: int = 3) -> List[Dict[str, Any]]:
    params = {
        "keyword": keyword,
        "limit": limit,
        "includeOnlyVerifiedCreators": "false",
    }
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


def pick_assets(prompt: str, biome: str, template: str, density: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen: set[int] = set()
    max_assets = 4 if density == "sparse" else 8 if density == "normal" else 12

    for query in asset_queries_for_prompt(prompt, biome, template):
        for item in search_creator_store_assets(query, 3):
            asset_id = item["assetId"]
            if asset_id in seen:
                continue
            seen.add(asset_id)
            found.append(item)
            if len(found) >= max_assets:
                return found

    return found


def selection_targets() -> List[str]:
    return [
        "SpawnPad",
        "NPC_QuestGiver",
        "QuestBoard_Main",
    ]


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

    plan: Dict[str, Any] = {
        "folders": [
            "Gameplay",
            "Spawns",
            "Decor",
            "NPCs",
            "QuestData",
            "GeneratedScripts",
        ],
        "lighting": {
            "ClockTime": style["clock"],
            "Brightness": 2,
            "FogStart": 90,
            "FogEnd": 850 if size == "large" else 650,
            "Ambient": style["ambient"],
            "OutdoorAmbient": style["outdoor"],
        },
        "terrain": terrain_for_world(size, biome, template) if caps.get("terrain", True) else [],
        "primitiveProps": [],
        "storeAssets": [],
        "scripts": script_bundle(template) if caps.get("scripts", True) else [],
        "selectionTargets": selection_targets(),
    }

    if caps.get("props", True):
        plan["primitiveProps"].append(
            part("SpawnPad", (0, 3, 0), (14, 1, 14), "Neon", (0, 170, 255), "Cylinder")
        )
        plan["primitiveProps"].extend(choose_props(template, size, biome, density))

    if caps.get("props", True):
        plan["storeAssets"] = pick_assets(prompt, biome, template, density)

    if not caps.get("npcs", True):
        plan["primitiveProps"] = [
            p for p in plan["primitiveProps"]
            if not str(p.get("Name", "")).startswith("NPC_")
        ]

    if not caps.get("lighting", True):
        plan["lighting"] = {}

    return plan
