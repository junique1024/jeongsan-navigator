"""AISStream에서 국내 주요 항만 해역의 AIS 신호를 일정 시간 수신해 data/ais_state.json을 갱신한다.

원칙: 수집에 성공했을 때만 파일을 덮어쓴다. 오류가 나거나 수신 메시지가 없으면
기존 파일을 그대로 두므로, 웹페이지에는 마지막으로 성공한 데이터와 시각이 유지된다.
"""
import asyncio
import datetime as dt
import json
import os
import sys
import time

import websockets

API_KEY = os.environ.get("AISSTREAM_API_KEY", "")
LISTEN_SECONDS = int(os.environ.get("LISTEN_SECONDS", "180"))
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ais_state.json")
MAX_EVENTS = 30
KEEP_DAYS = 5

# 항만 해역 (위도, 경도) 남서쪽과 북동쪽 꼭짓점
PORTS = {
    # 해외 항만 (공개 AIS 수신망의 수신이 원활한 해역)
    "로테르담항": [[51.85, 3.60], [52.05, 4.35]],
    "싱가포르항": [[1.10, 103.60], [1.40, 104.15]],
    "호르무즈 해협 인근": [[25.00, 55.50], [26.80, 57.50]],
    # 국내 항만 (현재 공개 수신망에서는 신호가 거의 잡히지 않음, 기획서상 PORT-MIS로 연계 예정)
    "부산항": [[34.95, 128.70], [35.15, 129.15]],
    "광양항": [[34.80, 127.60], [34.98, 127.85]],
    "포항항": [[35.95, 129.33], [36.10, 129.50]],
    "울산항": [[35.40, 129.30], [35.55, 129.45]],
    "대한해협 접근 수로": [[34.40, 128.30], [35.40, 129.80]],
}
# 키 정상 여부 확인용 (수신량이 많은 해역, 저장하지 않음)
DIAG_BOX = [[1.10, 103.60], [1.35, 104.10]]  # 싱가포르 해협

NAV_STATUS = {
    0: "항해 중", 1: "묘박(정박지 대기)", 2: "조종 불능", 3: "조종 제한",
    4: "흘수 제약", 5: "계류(접안)", 6: "좌초", 7: "어로 중", 8: "범주 중",
}


def port_of(lat, lon):
    for name, ((lat1, lon1), (lat2, lon2)) in PORTS.items():
        if lat1 <= lat <= lat2 and lon1 <= lon <= lon2:
            return name
    return "기타 해역"


def parse_time(s):
    # 예: "2026-10-15 01:23:45.123456789 +0000 UTC"
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


async def collect(boxes=None, seconds=None):
    boxes = boxes or list(PORTS.values())
    seconds = seconds or LISTEN_SECONDS
    msgs = []
    async with websockets.connect("wss://stream.aisstream.io/v0/stream", open_timeout=20) as ws:
        await ws.send(json.dumps({
            "APIKey": API_KEY,
            "BoundingBoxes": boxes,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }))
        end = time.time() + seconds
        while True:
            remain = end - time.time()
            if remain <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remain)
            except asyncio.TimeoutError:
                break
            try:
                m = json.loads(raw)
            except Exception:
                continue
            if "error" in m:
                raise RuntimeError(f"AISStream 오류: {m['error']}")
            msgs.append(m)
    return msgs


def update_state(state, msgs):
    vessels = state.setdefault("vessels", {})
    n_pos = 0
    for m in msgs:
        meta = m.get("MetaData", {})
        mmsi = str(meta.get("MMSI", ""))
        if not mmsi:
            continue
        v = vessels.setdefault(mmsi, {"mmsi": mmsi, "events": []})
        name = (meta.get("ShipName") or "").strip()
        if name:
            v["name"] = name
        mtype = m.get("MessageType")
        body = m.get("Message", {}).get(mtype, {})
        if mtype == "ShipStaticData":
            v["ship_type"] = body.get("Type")
            dest = (body.get("Destination") or "").strip()
            if dest:
                v["destination"] = dest
            if body.get("ImoNumber"):
                v["imo"] = body.get("ImoNumber")
            continue
        if mtype != "PositionReport":
            continue
        n_pos += 1
        lat, lon = meta.get("latitude"), meta.get("longitude")
        t = parse_time(meta.get("time_utc", ""))
        status = body.get("NavigationalStatus")
        prev = v.get("status")
        if prev is not None and status is not None and status != prev:
            v["events"].append({
                "time_utc": t,
                "from": NAV_STATUS.get(prev, f"코드 {prev}"),
                "to": NAV_STATUS.get(status, f"코드 {status}"),
                "to_code": status,
                "port": port_of(lat, lon) if lat is not None else None,
            })
            v["events"] = v["events"][-MAX_EVENTS:]
        if status is not None:
            v["status"] = status
            v["status_text"] = NAV_STATUS.get(status, f"코드 {status}")
        v.update({"lat": lat, "lon": lon, "sog": body.get("Sog"), "last_seen_utc": t,
                  "port": port_of(lat, lon) if lat is not None else v.get("port")})
    # 오래 안 보인 선박 정리
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    for k in list(vessels):
        ls = vessels[k].get("last_seen_utc")
        if ls and dt.datetime.fromisoformat(ls) < cutoff:
            del vessels[k]
    return n_pos


def main():
    if not API_KEY:
        print("AISSTREAM_API_KEY가 없어 수집을 건너뜁니다. 기존 데이터를 유지합니다.")
        return 0
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {"vessels": {}}
    try:
        msgs = asyncio.run(collect())
    except Exception as e:
        print(f"수집 실패, 기존 데이터를 유지합니다: {type(e).__name__}: {e}")
        return 0
    types = {}
    for m in msgs:
        types[m.get("MessageType")] = types.get(m.get("MessageType"), 0) + 1
    print(f"[진단] 대상 해역 {LISTEN_SECONDS}초 수신: 전체 {len(msgs)}건, 유형별 {types}")
    n_pos = update_state(state, msgs)
    if n_pos == 0:
        print("수신한 위치 신호가 없어 기존 데이터를 유지합니다.")
        try:
            d = asyncio.run(collect([DIAG_BOX], 20))
            print(f"[진단] 싱가포르 해협 20초 수신: {len(d)}건 "
                  + ("→ API 키는 정상, 국내 해역 수신이 부족한 상태" if d else "→ 키 또는 서비스 연결 문제 가능성"))
        except Exception as e:
            print(f"[진단] 싱가포르 해협 확인 실패: {e} → 키 또는 서비스 연결 문제 가능성")
        return 0
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    state["updated_utc"] = now
    state["source"] = "AISStream (aisstream.io)"
    state["last_run"] = {"time_utc": now, "messages": len(msgs), "position_reports": n_pos,
                         "listen_seconds": LISTEN_SECONDS}
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)
    by_port = {}
    for v in state["vessels"].values():
        by_port[v.get("port")] = by_port.get(v.get("port"), 0) + 1
    print(f"갱신 완료: 메시지 {len(msgs)}건, 위치 신호 {n_pos}건, 선박 {len(state['vessels'])}척, 해역별 {by_port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
