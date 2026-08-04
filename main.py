import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List

from core.parser import PlayParser

# --- Modernized Lifespan Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This code runs right when the server starts up
    background_task = asyncio.create_task(broadcast_simulated_game())

    yield  # The server stays alive and runs here while clients connect

    # This code runs when you shut down the server
    background_task.cancel()

app = FastAPI(lifespan=lifespan)
parser = PlayParser()

# --- FANTASY ROSTERS ---
# You own CeeDee, Barkley, Aubrey, and Parsons
MY_ROSTER = ["C.LAMB", "S.BARKLEY", "B.AUBREY", "M.PARSONS"]

# Opponent owns AJ Brown, Jalen Hurts, and Derrick Henry
OPPONENT_ROSTER = ["A.BROWN", "J.HURTS", "D.HENRY"]
# Note: Dak Prescott is NOT on either roster! He is a neutral free agent.

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"New viewer connected! Total viewers: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print("Viewer disconnected.")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

# --- The "Mock Sunday" Background Loop ---
async def broadcast_simulated_game():
    await asyncio.sleep(2)

    with open("data/mock_games.json", "r") as file:
        plays = json.load(file)

    while True:
        for play in plays:
            parsed_data = parser.parse_play(play["text"], play["los"])
            if parsed_data:
                # Add the team ownership and exact Line of Scrimmage
                parsed_data["fantasy_team"] = play["fantasy_team"]
                parsed_data["line_of_scrimmage"] = play["los"]

                # Send the original play text to the frontend so we can display it in the sidebar!
                parsed_data["raw_text"] = play["text"]

                # ROSTER LOGIC: Tag each player with their owner
                for scorer in parsed_data["scorers"]:
                    if scorer["name"] in MY_ROSTER:
                        scorer["owner"] = "my_team"
                    elif scorer["name"] in OPPONENT_ROSTER:
                        scorer["owner"] = "opponent"
                    else:
                        scorer["owner"] = "neutral"

                print(f"Broadcasting [{play['fantasy_team'].upper()}]: Play Executed")

                # THIS IS THE CRITICAL LINE: It actually sends the data to the frontend!
                await manager.broadcast(parsed_data)

            # Wait 8 seconds so the user has time to read the play summary!
            await asyncio.sleep(8)

# --- WebSocket Endpoint ---
@app.websocket("/ws/live-field")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        #uvicorn main:app --reload