from __future__ import annotations
import json, os, random, time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
ASSET_CATALOG = json.loads((APP_DIR/'asset_catalog.json').read_text(encoding='utf-8')) if (APP_DIR/'asset_catalog.json').exists() else {'categories':{}}

app = FastAPI(title='WorldForge AI Backend', version='6.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
@app.get("/config")
async def get_config():
    return {
        "endpoint": "https://worldforge-backend-production.up.railway.app/roblox/worldgen"
    }

RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '60'))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv('RATE_LIMIT_MAX_REQUESTS', '10'))
PROMPT_MAX_LENGTH = int(os.getenv('PROMPT_MAX_LENGTH', '1500'))
_request_log: dict[str, deque[float]] = defaultdict(deque)

class OptionsModel(BaseModel):
    terrain: bool = True
    props: bool = True
    scripts: bool = True
    npcs: bool = True
    lighting: bool = True

class RequestModel(BaseModel):
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    template: str = 'custom'
    world_size: str = 'medium'
    options: OptionsModel = Field(default_factory=OptionsModel)
    studio: dict[str, Any] = Field(default_factory=dict)

def client_ip(request: Request) -> str:
    f = request.headers.get('x-forwarded-for')
    if f: return f.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'

def enforce_rate_limit(ip: str) -> None:
    now = time.time(); q = _request_log[ip]
    while q and now - q[0] > RATE_LIMIT_WINDOW_SECONDS: q.popleft()
    if len(q) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail=f'Rate limit exceeded. Limit: {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS} seconds.')
    q.append(now)

def clamp_size(world_size: str) -> int:
    return {'small':128, 'medium':256, 'large':512}.get(world_size, 256)

def choose_assets(template: str, prompt: str, max_items: int = 4):
    cats = ASSET_CATALOG.get('categories', {})
    lowered = f'{template} {prompt}'.lower()
    priority = []
    if any(x in lowered for x in ['fantasy','village','forest','medieval']): priority += ['fantasy','nature','buildings']
    if any(x in lowered for x in ['sci-fi','space','future','lab']): priority += ['scifi','props']
    if any(x in lowered for x in ['horror','dark','grave','spooky']): priority += ['horror','nature']
    if any(x in lowered for x in ['obby','platform','parkour']): priority += ['obby','props']
    if not priority: priority += [template,'props','nature','buildings']
    picks, seen = [], set()
    for cat in priority:
        for item in cats.get(cat, []):
            aid = item.get('assetId')
            if aid and aid not in seen:
                seen.add(aid); picks.append(item)
                if len(picks) >= max_items: return picks
    return picks[:max_items]

def base_lighting(template: str):
    d = {
      'fantasy': {'ClockTime':16,'Brightness':2.2,'FogStart':80,'FogEnd':650,'Ambient':{'r':90,'g':100,'b':120},'OutdoorAmbient':{'r':120,'g':130,'b':150}},
      'sci-fi': {'ClockTime':20,'Brightness':2.0,'FogStart':40,'FogEnd':300,'Ambient':{'r':70,'g':90,'b':130},'OutdoorAmbient':{'r':90,'g':120,'b':180}},
      'horror': {'ClockTime':1,'Brightness':1.0,'FogStart':20,'FogEnd':180,'Ambient':{'r':50,'g':55,'b':65},'OutdoorAmbient':{'r':70,'g':75,'b':85}},
      'town': {'ClockTime':14,'Brightness':2.4,'FogStart':150,'FogEnd':800,'Ambient':{'r':110,'g':110,'b':110},'OutdoorAmbient':{'r':140,'g':140,'b':140}},
      'survival': {'ClockTime':13,'Brightness':2.1,'FogStart':100,'FogEnd':700,'Ambient':{'r':100,'g':110,'b':100},'OutdoorAmbient':{'r':130,'g':140,'b':130}},
    }
    return d.get(template, {'ClockTime':15,'Brightness':2.0,'FogStart':100,'FogEnd':600,'Ambient':{'r':100,'g':100,'b':110},'OutdoorAmbient':{'r':130,'g':130,'b':140}})

def terrain_plan(template: str, world_size: str, prompt: str):
    size = clamp_size(world_size)
    ops = [{'kind':'FillBlock','position':{'x':0,'y':-8,'z':0},'size':{'x':size,'y':16,'z':size},'material':'Grass' if template not in {'sci-fi','obby'} else 'Concrete'}]
    if template in {'fantasy','survival','horror','town','custom'}:
        ops += [{'kind':'FillBall','position':{'x':55,'y':18,'z':-50},'radius':40,'material':'Rock'}, {'kind':'FillBall','position':{'x':-70,'y':16,'z':60},'radius':36,'material':'Grass'}]
    if 'cave' in prompt.lower() or template in {'dungeon','horror'}:
        ops += [{'kind':'FillBall','position':{'x':90,'y':26,'z':-30},'radius':34,'material':'Rock'}, {'kind':'ClearSphere','position':{'x':95,'y':24,'z':-30},'radius':16}]
    if 'water' in prompt.lower() or template in {'survival','fantasy'}:
        ops += [{'kind':'FillBlock','position':{'x':-90,'y':-2,'z':-90},'size':{'x':80,'y':6,'z':80},'material':'Water'}]
    if template == 'obby':
        ops = [{'kind':'FillBlock','position':{'x':0,'y':-10,'z':0},'size':{'x':size,'y':20,'z':size},'material':'Concrete'}]
    return ops

def primitive_spawn_area():
    return [{'kind':'Part','Name':'SpawnPad','Shape':'Cylinder','Position':{'x':0,'y':3,'z':0},'Size':{'x':12,'y':1,'z':12},'Material':'Neon','Color':{'r':0,'g':170,'b':255}}]

def npc_props(template: str):
    if template == 'obby': return []
    return [{'kind':'Model','Name':'QuestGiverNPC','parts':[{'kind':'Part','Name':'HumanoidRootPart','Position':{'x':18,'y':4,'z':12},'Size':{'x':2,'y':2,'z':1},'Material':'SmoothPlastic','Color':{'r':255,'g':204,'b':153}}, {'kind':'Part','Name':'Head','Position':{'x':18,'y':6.5,'z':12},'Size':{'x':2,'y':1,'z':1},'Material':'SmoothPlastic','Color':{'r':255,'g':224,'b':189}}]}]

def build_plan(body: RequestModel):
    template = body.template.lower(); prompt = body.prompt.strip(); options = body.options
    chosen_assets = choose_assets(template, prompt, 4) if options.props else []
    positions = [{'x':25,'y':4,'z':10},{'x':-30,'y':4,'z':40},{'x':60,'y':4,'z':-25},{'x':-55,'y':4,'z':-40}]
    store = [{'assetId':item['assetId'], 'position':positions[i % len(positions)], 'name':item.get('name','Asset')} for i,item in enumerate(chosen_assets)]
    scripts = []
    if options.scripts:
        scripts.append({'className':'ModuleScript','name':'QuestConfig','source':f'''return {{
    Quests = {{
        {{ Name = "Meet the Guide", Description = "Talk to the NPC to begin your {template} adventure.", Reward = 50 }},
        {{ Name = "Explore the Map", Description = "Reach a landmark area and look around.", Reward = 100 }},
    }}
}}'''})
        scripts.append({'className':'Script','name':'EnvironmentController','source':f'''while task.wait(15) do
    if game.Lighting.ClockTime >= 24 then game.Lighting.ClockTime = 0 else game.Lighting.ClockTime += 0.1 end
end
print("WorldForge environment script active for template: {template}")'''})
        if options.npcs:
            scripts.append({'className':'Script','name':'NPCInteractionStarter','source':'print("WorldForge NPC content created. Add your own prompts or dialogue UI here.")'})
    return {
      'folders':['Gameplay','Spawns','Decor'],
      'lighting': base_lighting(template) if options.lighting else {},
      'terrain': terrain_plan(template, body.world_size, prompt) if options.terrain else [],
      'primitiveProps': primitive_spawn_area() if options.props else [],
      'storeAssets': store,
      'scripts': scripts,
      'npcs': npc_props(template) if options.npcs else [],
      'selectionTargets':['GeneratedScripts','PrimitiveProps','NPCs'],
      'meta': {'template':template, 'world_size':body.world_size, 'note':'Public-client starter backend. Review generated content before publishing.'}
    }

@app.get('/')
def root():
    return {'ok':True, 'service':'worldforge-backend', 'version':'6.0.0'}

@app.get('/health')
def health():
    return {'ok':True, 'rate_limit_window_seconds':RATE_LIMIT_WINDOW_SECONDS, 'rate_limit_max_requests':RATE_LIMIT_MAX_REQUESTS, 'catalog_categories':sorted(list(ASSET_CATALOG.get('categories',{}).keys()))}

@app.get('/config')
def config():
    base = os.getenv('PUBLIC_BACKEND_URL', '').strip()
    return {'endpoint': base.rstrip('/') + '/roblox/worldgen' if base else ''}

@app.post('/roblox/worldgen')
async def roblox_worldgen(body: RequestModel, request: Request):
    ip = client_ip(request); enforce_rate_limit(ip)
    prompt = body.prompt.strip()
    if not prompt: raise HTTPException(status_code=400, detail='Prompt is required.')
    return build_plan(body)
