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
USE_MOCK_DATA = False

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

        # 1. Add a flag to track if the play matters to the matchup
        is_relevant = False

        for scorer in parsed_data["scorers"]:
            if scorer["name"] in ROSTERS["my_team"]:
                scorer["owner"] = "my_team"
                is_relevant = True
            elif scorer["name"] in ROSTERS["opponent"]:
                scorer["owner"] = "opponent"
                is_relevant = True
            else:
                scorer["owner"] = "neutral"

        # 2. Only push the data to the web UI if it triggered the flag!
        if is_relevant:
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
    matchup_data = await client.get_matchup_data(my_team_id=6)
    roster_data = await client.get_starting_lineups(my_team_id=6)

    ROSTERS["my_team"] = roster_data.get("my_team", {})
    ROSTERS["opponent"] = roster_data.get("opponent", {})

    # FIX: Dynamically sum the actual live player points to bypass ESPN's team score lag!
    my_real_total = sum([data.get("pts", 0.0) for name, data in ROSTERS["my_team"].items()])
    opp_real_total = sum([data.get("pts", 0.0) for name, data in ROSTERS["opponent"].items()])

    return {
        "team_names": {
            "my_team": matchup_data["my_team"]["name"],
            "opponent": matchup_data["opp_team"]["name"]
        },
        "my_team": [{"name": name, "pos": data["pos"], "pts": data["pts"]} for name, data in ROSTERS["my_team"].items()],
        "opponent": [{"name": name, "pos": data["pos"], "pts": data["pts"]} for name, data in ROSTERS["opponent"].items()],
        # Send your instant calculations instead of the delayed ESPN total
        "totals": {"my_total": my_real_total, "opp_total": opp_real_total}
    }

@app.websocket("/ws/live-field")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

#uvicorn main2:app --reload
#http://localhost:8000