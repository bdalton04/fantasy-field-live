import re


class PlayParser:
    def __init__(self):
        pass

    def _clean_name(self, name_str: str) -> str:
        return name_str.replace(" ", "").upper()

    def parse_play(self, text: str, los: int, defending_team: str = None) -> dict:
        text_lower = text.lower()

        play_type = "run"
        yards_gained = 0
        scorers = []

        # NFL Event Flags
        is_touchdown = "touchdown" in text_lower
        is_fumble = "fumble" in text_lower
        is_interception = "intercepted" in text_lower
        is_sack = "sacked" in text_lower or "sack" in text_lower
        is_field_goal = "field goal" in text_lower
        is_pat = "extra point" in text_lower or "pat" in text_lower
        is_safety = "safety" in text_lower
        is_two_point = "two-point" in text_lower or "2-pt" in text_lower or "conversion" in text_lower
        is_dst_td = is_touchdown and (
                    "returned" in text_lower or "fumble recovery" in text_lower or "intercepted" in text_lower)

        x_coord = 26.6
        if " left" in text_lower:
            x_coord = 10
        elif " right" in text_lower:
            x_coord = 43

        name_pattern = r'([a-z]\.\s?[a-z\.\-\']+)'

        # --- FANTASY SCORING LOGIC ---

        if is_safety and defending_team:
            play_type = "safety"
            scorers.append({"name": f"{defending_team} DEF", "points": 2.0, "role": "defense"})
            y_coord = 0

        elif is_dst_td and defending_team:
            play_type = "dst_td"
            scorers.append({"name": f"{defending_team} DEF", "points": 6.0, "role": "defense"})
            y_coord = 100

        # 1. FIELD GOALS
        elif is_field_goal:
            play_type = "field_goal"
            kicker_match = re.search(name_pattern + r'\s+(\d+)\s+yard field goal', text_lower)
            if kicker_match:
                kicker_name = self._clean_name(kicker_match.group(1))
                yards = int(kicker_match.group(2))
                fg_points = 5.0 if yards >= 50 else (4.0 if yards >= 40 else 3.0)
                scorers.append({"name": kicker_name, "points": fg_points, "role": "kicker"})
            y_coord = 100

        # 2. EXTRA POINTS (PATs)
        elif is_pat:
            play_type = "pat"
            kicker_match = re.search(name_pattern + r'\s+extra point', text_lower)
            if kicker_match:
                kicker_name = self._clean_name(kicker_match.group(1))
                scorers.append({"name": kicker_name, "points": 1.0, "role": "kicker"})
            y_coord = 100

        # 3. PASSING PLAYS (Including 2-pt conversions)
        elif " pass " in text_lower or " passes " in text_lower:
            play_type = "pass"
            yards_match = re.search(r'for (-?\d+) yard', text_lower)
            yards_gained = int(yards_match.group(1)) if yards_match else 0

            passer_match = re.search(name_pattern + r'\s+pass', text_lower)
            receiver_match = re.search(r'to\s+' + name_pattern, text_lower)

            if passer_match:
                passer_name = self._clean_name(passer_match.group(1))
                qb_pts = 2.0 if is_two_point else (yards_gained / 25.0)
                if is_touchdown and not is_two_point: qb_pts += 4.0
                if is_interception: qb_pts -= 2.0
                scorers.append({"name": passer_name, "points": round(qb_pts, 2), "role": "passer"})

            if receiver_match and not is_interception:
                receiver_name = self._clean_name(receiver_match.group(1))
                wr_pts = 2.0 if is_two_point else (1.0 + (yards_gained * 0.1))
                if is_touchdown and not is_two_point: wr_pts += 6.0
                scorers.append({"name": receiver_name, "points": round(wr_pts, 2), "role": "receiver"})

            y_coord = los + yards_gained

        # 4. SACKS
        elif is_sack and defending_team:
            play_type = "sack"
            scorers.append({"name": f"{defending_team} DEF", "points": 1.0, "role": "defense"})
            y_coord = los

        # 5. RUSHING PLAYS (Including 2-pt conversions)
        else:
            play_type = "run"
            yards_match = re.search(r'for (-?\d+) yard', text_lower)
            yards_gained = int(yards_match.group(1)) if yards_match else 0

            runner_match = re.search(r'(?:\(\d+:\d+\)\s*)?' + name_pattern, text_lower)
            if runner_match:
                runner_name = self._clean_name(runner_match.group(1))
                rb_pts = 2.0 if is_two_point else (yards_gained * 0.1)
                if is_touchdown and not is_two_point: rb_pts += 6.0
                scorers.append({"name": runner_name, "points": round(rb_pts, 2), "role": "runner"})

            y_coord = los + yards_gained

        return {
            "play_type": play_type,
            "yards_gained": yards_gained,
            "is_touchdown": is_touchdown,
            "scorers": scorers,
            "coordinates": {"x": x_coord, "y": max(0, min(100, y_coord))}
        }