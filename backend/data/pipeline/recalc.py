"""
Reactive recalc — injury / depth fetch가 감지한 변경 선수에 대해서만
player_value를 즉시 재계산해서 DB에 반영하는 모듈.

배경
----
- 평소엔 매일 3시 ET에 _step_recalculate가 전체 1300명 player_value 재계산함
- 그러나 부상/뎁스가 낮에 변경되면 다음날 3시까지 bid가 옛 값으로 stale
- Reactive recalc는 30분 fetch cycle에서 진짜 바뀐 선수만 즉시 다시 계산해
  bid 정확도를 빠르게 복구함 (보통 사이클당 0~5명)

호출 흐름
--------
  injury.fetch_and_update / depth_charts.fetch_and_update
    → 변경된 player_id 추출
    → recalculate_players([1234, 5678, ...])
    → 각 선수: api 호출로 새 player_value 받아 DB UPDATE
"""
import logging
import os
from typing import List, Optional

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

# DB 연결 — daily_update.py / injury.py와 동일 패턴.
# 자체 engine을 만들어 의존성 단순화 (다른 모듈 import 안 함).
DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# api 서비스의 /player/value endpoint — Docker Compose 네트워크 내부 호출.
API_VALUE_URL    = os.getenv("API_VALUE_URL", "http://api:8000/player/value")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# 4개 player 테이블 메타. 선수 검색 + UPDATE 시 순회용.
_TABLES = (
    ("batters_al",  "batter"),
    ("batters_nl",  "batter"),
    ("pitchers_al", "pitcher"),
    ("pitchers_nl", "pitcher"),
)


def _find_player(player_id: int) -> Optional[dict]:
    """
    주어진 player_id를 4개 테이블에서 검색해 row + table 정보 반환.
    찾으면 dict에 'table', 'player_type' 추가해서 돌려줌.
    어느 테이블에도 없으면 None.
    """
    db = SessionLocal()
    try:
        for table, ptype in _TABLES:
            row = db.execute(
                text(f"SELECT * FROM {table} WHERE player_id = :pid LIMIT 1"),
                {"pid": player_id},
            ).fetchone()
            if row:
                d = dict(row._mapping)
                d["table"]       = table
                d["player_type"] = ptype
                return d
    finally:
        db.close()
    return None


def _call_player_value_api(player: dict) -> Optional[float]:
    """
    api 서비스의 /player/value endpoint로 POST → 새 player_value 반환.

    daily_update.py의 _call_player_value와 동일한 payload 빌드 — 중복이긴
    하지만 두 파일이 같은 API 계약을 따른다는 게 명확해서 의도적 중복.
    실패 시 None (caller가 skip 처리).
    """
    position    = (player["position"] or "").upper()
    player_type = player.get("player_type", "batter")

    if player_type == "pitcher":
        # IP / ERA가 없으면 의미 있는 계산 불가 — skip
        if player["ip"] is None or player["era"] is None:
            return None
        stats_payload = {
            "player_type":   "pitcher",
            "IP":            player["ip"]   or 0.0,
            "W":             player["w"]    or 0,
            "SV":            player["sv"]   or 0,
            "K":             player["so"]   or 0,
            "ERA":           player["era"]  or 0.0,
            "WHIP":          player["whip"] or 0.0,
            "age":           player["current_age"],
            "depth_order":   player["depth_order"],
            "injury_status": player["injury_status"],
        }
    else:
        # 타석 / 타율 없으면 skip
        if player["ab"] is None or player["avg"] is None:
            return None
        stats_payload = {
            "player_type":   "batter",
            "AB":            player["ab"]   or 0,
            "R":             player["r"]    or 0,
            "HR":            player["hr"]   or 0,
            "RBI":           player["rbi"]  or 0,
            "SB":            player["sb"]   or 0,
            "CS":            player["cs"]   or 0,
            "AVG":           player["avg"]  or 0.0,
            "age":           player["current_age"],
            "depth_order":   player["depth_order"],
            "injury_status": player["injury_status"],
        }

    payload = {
        "player_name": str(player["player_id"]),
        "position":    position,
        "stats":       stats_payload,
    }

    try:
        resp = requests.post(
            API_VALUE_URL,
            json=payload,
            headers={"X-API-Key": INTERNAL_API_KEY},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["player_value"]
    except Exception as e:
        logger.warning(f"[reactive_recalc] /player/value failed pid={player['player_id']}: {e}")
        return None


def recalculate_players(player_ids: List[int]) -> int:
    """
    주어진 player_ids 각각에 대해 player_value 재계산 + DB UPDATE.

    호출처: injury.fetch_and_update, depth_charts.fetch_and_update
    호출 시점: 변경된 player_id 추출 직후

    Returns: 성공적으로 update된 선수 수 (logging 및 모니터링용).

    실패 케이스 (조용히 skip):
      - 선수 ID가 어느 테이블에도 없음 (이상 데이터)
      - api /player/value 호출 실패 (network, 5xx 등)
      - 필수 스탯 누락으로 의미 있는 계산 불가
      → 다음 사이클이나 daily full recalc에서 잡힘
    """
    if not player_ids:
        return 0

    success = 0
    for pid in player_ids:
        # 1) 선수 row + 어느 테이블인지 찾기
        player = _find_player(pid)
        if not player:
            logger.warning(f"[reactive_recalc] player_id={pid} not found in any table")
            continue

        # 2) api 호출해서 새 player_value 받기
        new_value = _call_player_value_api(player)
        if new_value is None:
            continue  # 위에서 이미 logging됨

        # 3) DB UPDATE (선수가 속한 테이블에)
        db = SessionLocal()
        try:
            db.execute(
                text(
                    f"UPDATE {player['table']} "
                    f"SET player_value = :v WHERE player_id = :pid"
                ),
                {"v": new_value, "pid": pid},
            )
            db.commit()
            success += 1
        except Exception as e:
            db.rollback()
            logger.error(f"[reactive_recalc] UPDATE failed pid={pid}: {e}")
        finally:
            db.close()

    logger.info(
        f"[reactive_recalc] {success}/{len(player_ids)} player_value 갱신 완료"
    )
    return success
