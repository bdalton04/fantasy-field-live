import json
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from typing import List
from dotenv import load_dotenv

load_dotenv()

from core.parser import PlayParser
from services.api_client import FantasyAPIClient

parser = PlayParser()

# Change to False for the regular season!
USE_MOCK_DATA = True

# --- GLOBAL STATE ---
ROSTERS = {"my_team": {}, "opponent": {}}


def load_rosters():
    try:
        if os.path.exists("data/roster_configuration.json"):
            with open("data/roster_configuration.json", "r") as file:
                data = json.load(file)
                ROSTERS["my_team"] = data.get("my_team", {})
                ROSTERS["opponent"] = data.get("opponent", {})
    except Exception as e:
        print(f"Error loading rosters: {e}")


# --- API CLIENT INSTANCE ---
client = FantasyAPIClient(
    league_id=os.getenv("LEAGUE_ID"),
    swid=os.getenv("ESPN_SWID"),
    espn_s2=os.getenv("ESPN_S2_COOKIE")
)


# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except RuntimeError:
                pass


manager = ConnectionManager()


# --- DATA PIPELINES ---
async def process_and_broadcast_play(text: str, play_id: str, is_home: bool = True, los: int = 25,
                                     defending_team: str = None):
    parsed_data = parser.parse_play(text, los=los, defending_team=defending_team)
    if parsed_data:
        parsed_data["fantasy_team"] = "home" if is_home else "away"
        parsed_data["line_of_scrimmage"] = los
        parsed_data["raw_text"] = text
        for scorer in parsed_data["scorers"]:
            if scorer["name"] in ROSTERS["my_team"]:
                scorer["owner"] = "my_team"
            elif scorer["name"] in ROSTERS["opponent"]:
                scorer["owner"] = "opponent"
            else:
                scorer["owner"] = "neutral"
        await manager.broadcast(parsed_data)


async def broadcast_live_game():
    processed_play_ids = set()

    if USE_MOCK_DATA:
        with open("data/mock_games.json", "r") as file:
            mock_plays = json.load(file)
        while True:
            for idx, play in enumerate(mock_plays):
                await process_and_broadcast_play(play["text"], str(idx), (play["fantasy_team"] == "home"),
                                                 play.get("los", 25), play.get("defending_team"))
                await asyncio.sleep(5)
    else:
        while True:
            try:
                live_plays = await client.fetch_live_plays()
                for play in live_plays:
                    if play["id"] not in processed_play_ids:
                        processed_play_ids.add(play["id"])
                        await process_and_broadcast_play(play["text"], play["id"], True, play["los"],
                                                         play["defending_team"])
            except Exception as e:
                print(f"Error: {e}")
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_rosters()
    task = asyncio.create_task(broadcast_live_game())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def serve_frontend(): return FileResponse("index.html")


@app.get("/roster-state")
async def get_roster_state():
    matchup_data = await client.get_matchup_data(my_team_id=1)  # REPLACE THIS WITH MY TEAM ID

    my_score = matchup_data["my_team"]["score"]
    opp_score = matchup_data["opp_team"]["score"]

    return {
        "team_names": {
            "my_team": matchup_data["my_team"]["name"],
            "opponent": matchup_data["opp_team"]["name"]
        },
        "my_team": [{"name": p, "pos": pos, "pts": 0.0} for p, pos in ROSTERS["my_team"].items()],
        "opponent": [{"name": p, "pos": pos, "pts": 0.0} for p, pos in ROSTERS["opponent"].items()],
        "totals": {"my_total": my_score, "opp_total": opp_score}
    }


@app.websocket("/ws/live-field")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)