import httpx

class FantasyAPIClient:
    def __init__(self, league_id: str, swid: str, espn_s2: str):
        self.league_id = league_id
        self.cookies = {"SWID": swid, "espn_s2": espn_s2}

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        self.fantasy_base_url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues"
        self.nfl_base_url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

    async def get_matchup_data(self, my_team_id: int):
        async with httpx.AsyncClient(cookies=self.cookies, headers=self.headers, follow_redirects=True) as client:
            try:
                # 1. Try the live scoring endpoint first
                params = {"view": ["mMatchup", "mTeam"], "scoringPeriodId": 1}
                resp = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=params)

                data = {}
                # 2. If it's preseason (202), pivot to the static schedule view!
                if resp.status_code == 202:
                    print("✅ Live endpoint inactive (202). Fetching static Week 1 schedule...")
                    static_params = {"view": ["mMatchupScore", "mTeam"], "matchupPeriodId": 1}
                    resp_static = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=static_params)
                    if resp_static.status_code == 200:
                        data = resp_static.json()
                elif resp.status_code == 200:
                    data = resp.json()
                else:
                    return self._get_fallback_matchup()

                if not data:
                    return self._get_fallback_matchup()

                # 3. Glue location and nickname together for accurate Team Names
                team_names = {}
                for team in data.get("teams", []):
                    name = team.get("name")
                    if not name:
                        location = team.get("location", "")
                        nickname = team.get("nickname", "")
                        name = f"{location} {nickname}".strip()
                    team_names[team["id"]] = name or f"Team {team['id']}"

                # 4. Find the matchup
                for matchup in data.get("schedule", []):
                    if matchup.get("matchupPeriodId", 1) != 1:
                        continue

                    home_id = matchup.get("home", {}).get("teamId")
                    away_id = matchup.get("away", {}).get("teamId")

                    if home_id == my_team_id or away_id == my_team_id:
                        my_info = matchup["home"] if home_id == my_team_id else matchup["away"]
                        opp_info = matchup["away"] if home_id == my_team_id else matchup["home"]
                        opp_id = opp_info.get("teamId")

                        return {
                            "my_team": {
                                "name": team_names.get(my_team_id, "MY TEAM"),
                                "score": my_info.get("totalPoints", 0.0)
                            },
                            "opp_team": {
                                "name": team_names.get(opp_id, "OPPONENT") if opp_id else "BYE",
                                "score": opp_info.get("totalPoints", 0.0)
                            }
                        }

                return self._get_fallback_matchup()
            except Exception as e:
                print(f"🚨 Connection Error in get_matchup_data: {e}")
                return self._get_fallback_matchup()

    def _get_fallback_matchup(self):
        return {
            "my_team": {"name": "MY TEAM", "score": 0.0},
            "opp_team": {"name": "OPPONENT", "score": 0.0}
        }

    async def get_starting_lineups(self, my_team_id: int, scoring_period: int = 1):
        async with httpx.AsyncClient(cookies=self.cookies, headers=self.headers, follow_redirects=True) as client:
            try:
                # 1. Try the live roster endpoint first
                params = {"view": ["mMatchup", "mRoster"], "scoringPeriodId": scoring_period}
                resp = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=params)

                data = {}
                # 2. Catch the 202 and pivot to the static roster view!
                if resp.status_code == 202:
                    print("✅ Live rosters inactive (202). Fetching static Week 1 rosters...")
                    static_params = {"view": ["mRoster", "mMatchupScore"], "scoringPeriodId": scoring_period}
                    resp_static = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=static_params)

                    # --- NEW DIAGNOSTICS: Catch the exact rejection reason ---
                    print(f"🚨 STATIC ENDPOINT STATUS: {resp_static.status_code}")
                    if resp_static.status_code != 200:
                        print(f"🚨 ESPN REJECTED IT! Reason: {resp_static.reason_phrase}")
                    # ---------------------------------------------------------

                    if resp_static.status_code == 200:
                        data = resp_static.json()
                        print(f"🚨 RAW STATIC DATA PREVIEW: {str(data)[:200]}")

                elif resp.status_code == 200:
                    data = resp.json()

                else:
                    return {"my_team": {}, "opponent": {}}

                if not data: return {"my_team": {}, "opponent": {}}

                rosters = {"my_team": {}, "opponent": {}}

                if "teams" in data:
                    opp_team_id = None
                    for matchup in data.get("schedule", []):
                        if matchup.get("matchupPeriodId", 1) != scoring_period:
                            continue

                        home_id = matchup.get("home", {}).get("teamId")
                        away_id = matchup.get("away", {}).get("teamId")

                        if home_id == my_team_id:
                            opp_team_id = away_id
                            break
                        elif away_id == my_team_id:
                            opp_team_id = home_id
                            break

                    for team in data["teams"]:
                        t_id = team.get("id")
                        if t_id == my_team_id:
                            rosters["my_team"] = self._extract_starters(team)
                        elif t_id == opp_team_id:
                            rosters["opponent"] = self._extract_starters(team)

                return rosters

            except Exception as e:
                print(f"🚨 Connection Error in get_starting_lineups: {e}")
                return {"my_team": {}, "opponent": {}}

    def _extract_starters(self, team_data: dict):
        starters = {}
        pos_map = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 23: "FLEX"}

        roster_node = team_data.get("rosterForCurrentScoringPeriod")
        entries = roster_node.get("entries", []) if roster_node else []

        if not entries:
            roster_node = team_data.get("roster", {})
            entries = roster_node.get("entries") or []

        for entry in entries:
            slot_id = entry.get("lineupSlotId")

            if slot_id not in [20, 21]:
                player_pool_entry = entry.get("playerPoolEntry", {})
                player_node = player_pool_entry.get("player", {})
                full_name = player_node.get("fullName", "")

                # FIX 1: Extract ESPN's official live point total for the player
                points = player_pool_entry.get("appliedStatTotal", 0.0)

                if full_name:
                    parts = full_name.split(" ")
                    if len(parts) >= 2 and slot_id != 16:
                        nfl_name = f"{parts[0][0]}.{parts[1]}".upper()
                    else:
                        nfl_name = f"{parts[-1]} DEF".upper()

                    # FIX 2: Store both the position AND the current points in a dictionary
                    starters[nfl_name] = {"pos": pos_map.get(slot_id, "FLEX"), "pts": points}

        return starters

    # =======================================================#
    # LIVE NFL PLAY POLL (PUBLIC DATA)
    # =======================================================#
    async def fetch_live_plays(self):
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                resp = await client.get(self.nfl_base_url)
                if resp.status_code != 200:
                    return []

                data = resp.json()
                live_plays = []

                for event in data.get("events", []):
                    competitions = event.get("competitions", [])
                    if not competitions:
                        continue

                    situation = competitions[0].get("situation", {})
                    last_play = situation.get("lastPlay", {})

                    play_text = last_play.get("text")
                    play_id = last_play.get("id")

                    if play_text and play_id:
                        los = situation.get("downDistanceText")

                        possession_id = situation.get("team", {}).get("id")
                        defending_team = "UNKNOWN"
                        for competitor in competitions[0].get("competitors", []):
                            if competitor.get("id") != possession_id:
                                defending_team = competitor.get("team", {}).get("abbreviation")

                        live_plays.append({
                            "id": play_id,
                            "text": play_text,
                            "los": 25,
                            "defending_team": defending_team
                        })

                return live_plays

            except Exception as e:
                print(f"Error fetching live NFL plays: {e}")
                return []