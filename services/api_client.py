import httpx


class FantasyAPIClient:
    def __init__(self, league_id: str, swid: str, espn_s2: str):
        self.league_id = league_id
        # Cookies are required for private leagues
        self.cookies = {"SWID": swid, "espn_s2": espn_s2}

        # 🎭 The Disguise: Tell ESPN we are a normal Google Chrome web browser, not a Python bot
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        # ESPN API Endpoints
        self.fantasy_base_url = "https://fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues"
        self.nfl_base_url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

    async def get_matchup_data(self, my_team_id: int):
        """
        Fetches the matchup containing my_team_id and returns team names and current total scores.
        """
        # follow_redirects=True is CRITICAL to bypass ESPN's internal 302 server redirects
        # We also pass our disguise headers here!
        async with httpx.AsyncClient(cookies=self.cookies, headers=self.headers, follow_redirects=True) as client:
            try:
                # mMatchup gives us schedule and scores, mTeam gives us the actual Team Names
                params = {"view": ["mMatchup", "mTeam"], "scoringPeriodId": 1}
                resp = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=params)

                # Preseason Debugger: Catch bad cookies or invalid league IDs
                if resp.status_code not in [200, 202]:
                    print(f"🚨 ESPN API REJECTED REQUEST. Status Code: {resp.status_code}")
                    print(f"🚨 Response Reason: {resp.reason_phrase}")
                    return self._get_fallback_matchup()

                if resp.status_code == 202:
                    print("✅ VIP ACCESS GRANTED! ESPN says '202 Accepted' (Preseason Mode)")

                data = resp.json()

                # 1. Build a dictionary of Team IDs to Team Names
                team_names = {team["id"]: team.get("name", f"Team {team['id']}") for team in data.get("teams", [])}

                # 2. Find your specific matchup in the schedule
                for matchup in data.get("schedule", []):
                    home_id = matchup.get("home", {}).get("teamId")
                    away_id = matchup.get("away", {}).get("teamId")

                    if home_id == my_team_id or away_id == my_team_id:
                        # Determine which one is you and which one is the opponent
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

                print(f"⚠️ Warning: Could not find a matchup for Team ID {my_team_id} in this scoring period.")
                return self._get_fallback_matchup()

            except Exception as e:
                print(f"🚨 Connection Error in get_matchup_data: {e}")
                return self._get_fallback_matchup()

    def _get_fallback_matchup(self):
        """Returns safe default values if the ESPN connection fails."""
        return {
            "my_team": {"name": "MY TEAM", "score": 0.0},
            "opp_team": {"name": "OPPONENT", "score": 0.0}
        }

    # =====================================================================
    # 🏈 THE HOLY GRAIL: AUTO-ROSTER LOGIC (FULLY IMPLEMENTED)
    # =====================================================================
    async def get_starting_lineups(self, my_team_id: int, scoring_period: int = 1):
        """
        Scrapes the live starting lineup for you and your opponent, formats their names
        to match the NFL play-by-play logs (e.g., 'J.BURROW'), and returns them.
        """
        async with httpx.AsyncClient(cookies=self.cookies, headers=self.headers, follow_redirects=True) as client:
            # mRoster is the specific view required to see individual players
            params = {"view": ["mMatchup", "mRoster"], "scoringPeriodId": scoring_period}
            resp = await client.get(f"{self.fantasy_base_url}/{self.league_id}", params=params)

            if resp.status_code != 200:
                print("🚨 Failed to fetch live rosters from ESPN.")
                return {"my_team": {}, "opponent": {}}

            data = resp.json()
            rosters = {"my_team": {}, "opponent": {}}

            for matchup in data.get("schedule", []):
                home_id = matchup.get("home", {}).get("teamId")
                away_id = matchup.get("away", {}).get("teamId")

                if home_id == my_team_id or away_id == my_team_id:
                    # Parse My Team
                    my_roster_data = matchup["home"] if home_id == my_team_id else matchup["away"]
                    rosters["my_team"] = self._extract_starters(my_roster_data)

                    # Parse Opponent (If they have an opponent this week)
                    opp_roster_data = matchup["away"] if home_id == my_team_id else matchup["home"]
                    if opp_roster_data:
                        rosters["opponent"] = self._extract_starters(opp_roster_data)

                    break

            return rosters

    def _extract_starters(self, team_data: dict):
        """Helper function to filter out bench players and format names."""
        starters = {}
        # Position mapping from ESPN's internal IDs to standard labels
        pos_map = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST", 23: "FLEX"}

        entries = team_data.get("rosterForCurrentScoringPeriod", {}).get("entries", [])
        for entry in entries:
            slot_id = entry.get("lineupSlotId")

            # ESPN Lineup Slots: 20 is Bench, 21 is IR. We only want active starters!
            if slot_id not in [20, 21]:
                player_pool_entry = entry.get("playerPoolEntry", {}).get("player", {})
                full_name = player_pool_entry.get("fullName", "")

                if full_name:
                    # Convert "Joe Burrow" into "J.BURROW" to match NFL Play-by-Play
                    parts = full_name.split(" ")
                    if len(parts) >= 2 and slot_id != 16:  # Normal players
                        nfl_name = f"{parts[0][0]}.{parts[1]}".upper()
                    else:  # D/ST formatting (e.g. "Ravens D/ST")
                        nfl_name = f"{parts[-1]} DEF".upper()

                    starters[nfl_name] = pos_map.get(slot_id, "FLEX")

        return starters

    # =====================================================================
    # 📡 THE LIVE NFL PLAY POLL (PUBLIC DATA)
    # =====================================================================
    async def fetch_live_plays(self):
        """
        Polls the public ESPN NFL scoreboard for live play-by-play text across all active games.
        """
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                resp = await client.get(self.nfl_base_url)
                if resp.status_code != 200:
                    return []

                data = resp.json()
                live_plays = []

                # Loop through every active NFL game on the scoreboard
                for event in data.get("events", []):
                    competitions = event.get("competitions", [])
                    if not competitions:
                        continue

                    situation = competitions[0].get("situation", {})
                    last_play = situation.get("lastPlay", {})

                    play_text = last_play.get("text")
                    play_id = last_play.get("id")

                    if play_text and play_id:
                        # Find line of scrimmage (0-100 scale)
                        los = situation.get("downDistanceText")

                        # Defending team is needed for sacks/turnovers
                        possession_id = situation.get("team", {}).get("id")
                        defending_team = "UNKNOWN"
                        for competitor in competitions[0].get("competitors", []):
                            if competitor.get("id") != possession_id:
                                defending_team = competitor.get("team", {}).get("abbreviation")

                        live_plays.append({
                            "id": play_id,
                            "text": play_text,
                            "los": 25,  # Defaulting to 25 if we can't parse the exact number
                            "defending_team": defending_team
                        })

                return live_plays

            except Exception as e:
                print(f"Error fetching live NFL plays: {e}")
                return []