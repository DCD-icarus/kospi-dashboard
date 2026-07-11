"""
Dashboard Factory (v2)
=======================
기존 스크립트는 BACKUP_*_DATA 하드코딩 값을 매번 그대로 재기록하는 구조였습니다.
이 버전은 실제 외부 데이터 소스에서 값을 가져오고, 실패 시에는 "가짜 숫자로
덮어쓰는" 대신 기존 파일 값을 그대로 보존하고 에러를 로그로 남깁니다.

데이터 소스
-----------
- KOSPI 지수 / 국내 대형주 / ETF / 국내 REITs 시세 : yfinance (Yahoo Finance, .KS 티커)
- REITs 공시 : DART Open API (실제 개별 공시 링크 생성)
- 미국 지수/금리/유가 / 미국 대형주 : yfinance
- 서울 아파트 실거래가 : 공공데이터포털 국토교통부 아파트매매 실거래 상세자료 API

필요한 GitHub Secrets
----------------------
- KAKAO_CLIENT_ID, KAKAO_REFRESH_TOKEN   (기존과 동일)
- DART_API_KEY                            (opendart.fss.or.kr 무료 발급)
- MOLIT_API_KEY                           (data.go.kr 아파트매매 실거래가 상세자료, 무료 자동승인)

발급 방법은 README_설치가이드.md 참고.
"""

import os
import re
import json
import logging
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dashboard_factory")

KST = timezone(timedelta(hours=9))
CODE_CACHE_FILE = "stock_code_cache.json"

# ---------------------------------------------------------------------------
# 종목코드 매핑
# ---------------------------------------------------------------------------
# 아래 10개 대형주 + 5개 ETF는 널리 알려진 종목이라 신뢰도가 높습니다.
# 반면 상장리츠 23개는 코드가 신규 상장/합병 등으로 바뀔 수 있어, 아래 값은
# "1차 추정치"로만 쓰고 실행 시 네이버 종목검색 API로 자동 재검증합니다.
# 검증 결과는 stock_code_cache.json 에 저장되어 다음 실행부터는 캐시를 씁니다.
KNOWN_CODES = {
    "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940", "현대차": "005380", "기아": "000270",
    "셀트리온": "068270", "KB금융": "105560", "POSCO홀딩스": "005490", "NAVER": "035420",
    "KODEX 200": "069500", "TIGER 코리아TOP10": "277630", "KODEX 반도체": "091160",
    "TIGER 반도체TOP10": "381170", "KODEX 증권": "102970",
}

REIT_ETF_NAMES = ["TIGER 리츠부동산인프라", "KODEX 한국부동산리츠"]
REIT_ASSET_NAMES = [
    "맥쿼리인프라펀드", "SK리츠", "롯데리츠", "제이알글로벌리츠", "신한알파리츠",
    "ESR켄달스퀘어리츠", "KB발해인프라펀드", "코람코라이프인프라리츠", "디앤디플랫폼리츠",
    "이리츠코크렙", "한화리츠", "KB스타리츠", "삼성FN리츠", "미래에셋글로벌리츠",
    "신한글로벌액티브리츠", "신한서부티엔디리츠", "마스턴프리미어리츠", "코람코더원리츠",
    "NH올원리츠", "미래에셋맵스리츠", "이지스밸류플러스리츠", "이지스레지던스리츠",
    "NH프라임리츠", "대신밸류리츠",
]

DART_WATCH_NAMES = ["맥쿼리인프라", "SK리츠", "신한알파리츠"]  # DART 검색 시 회사명 매칭용 (펀드/리츠 접미사 차이 대응)

US_TOP_TICKERS = ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "LLY", "V"]

US_MACRO_TICKERS = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "나스닥 종합"),
    ("^DJI", "다우존스 지수"),
    ("^TNX", "미국채 10년 금리"),
    ("^TYX", "미국채 30년 금리"),
    ("CL=F", "WTI 선물 유가"),
]

# 서울 관심 지역 법정동코드 (앞 5자리) - 필요시 추가/수정
LAWD_CODES = {
    "강남구": "11680", "서초구": "11650", "송파구": "11710",
    "강동구": "11740", "용산구": "11170", "성동구": "11200",
}

TARGET_APT = {  # 관심단지 (핵심 모니터링용, core 테이블)
    "올림픽파크포레온": "강동구", "래미안원베일리": "서초구", "타워팰리스3차": "강남구",
    "아크로리버파크": "서초구", "잠실엘스": "송파구", "헬리오시티": "송파구",
}


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
def _load_cache():
    if os.path.exists(CODE_CACHE_FILE):
        try:
            with open(CODE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    try:
        with open(CODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"종목코드 캐시 저장 실패: {e}")


_code_cache = _load_cache()


def resolve_stock_code(name):
    """종목명 -> 코드. KNOWN_CODES 우선, 없으면 캐시, 없으면 네이버 검색 API로 조회.
    (구) ac.finance.naver.com 은 네이버가 '네이버페이 증권'으로 개편되며 폐기되어
    DNS 조회 자체가 실패했음 - 현재는 m.stock.naver.com/front-api/search/autoComplete
    를 사용. 이 역시 비공식(undocumented) 엔드포인트이므로 스키마가 또 바뀔 수 있어
    실패 시 None을 반환하고 상위 로직에서 해당 항목만 건너뜁니다."""
    if name in KNOWN_CODES:
        return KNOWN_CODES[name]
    if name in _code_cache:
        return _code_cache[name]
    try:
        resp = requests.get(
            "https://m.stock.naver.com/front-api/search/autoComplete",
            params={"query": name, "target": "stock,index,marketindicator,coin,ipo"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("result") or {}).get("items", [])
        norm_target = name.replace(" ", "")
        for it in items:
            code = it.get("code")
            item_name = it.get("name", "")
            if not code:
                continue
            norm_a = item_name.replace(" ", "")
            if norm_a == norm_target or norm_a in norm_target or norm_target in norm_a:
                _code_cache[name] = code
                _save_cache(_code_cache)
                return code
        if items:  # 정확히 일치하는 항목이 없으면 최상위 추천 결과를 차선책으로 사용
            code = items[0].get("code")
            if code:
                log.warning(f"'{name}' 정확히 일치하는 종목명 없음 - 최상위 결과 '{items[0].get('name')}'({code}) 사용")
                _code_cache[name] = code
                _save_cache(_code_cache)
                return code
    except Exception as e:
        log.warning(f"종목코드 자동조회 실패 ({name}): {e}")
    return None


def fmt_pct(x):
    return f"{'+' if x >= 0 else ''}{x:.2f}%"


def fmt_won_change(x):
    return f"{'+' if x >= 0 else ''}{x:,.0f}원"


def fmt_won(x):
    return f"{x:,.0f}원"


def fmt_cap_won(market_cap):
    if not market_cap:
        return "N/A"
    eok = market_cap / 1e8
    jo = eok / 10000
    return f"{jo:.1f}조" if jo >= 1 else f"{eok:,.0f}억"


def fmt_usd(x):
    return f"${x:,.2f}"


def fmt_usd_change(x):
    return f"{'+' if x >= 0 else ''}${x:,.2f}"


def fmt_cap_usd(market_cap):
    if not market_cap:
        return "N/A"
    tril = market_cap / 1e12
    bil = market_cap / 1e9
    return f"{tril:.2f}조달러" if tril >= 1 else f"{bil:,.0f}억달러"


def yf_last_two(ticker):
    """최근 2거래일 종가를 반환. 실패 시 None."""
    if yf is None:
        log.error("yfinance가 설치되어 있지 않습니다 (pip install yfinance).")
        return None
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="7d")
        hist = hist.dropna(subset=["Close"])
        if len(hist) < 2:
            log.warning(f"{ticker}: 최근 시세 데이터 부족")
            return None
        last, prev = hist.iloc[-1], hist.iloc[-2]
        market_cap = None
        try:
            market_cap = t.fast_info.get("market_cap")
        except Exception:
            pass
        return {
            "close": float(last["Close"]),
            "prev_close": float(prev["Close"]),
            "date": hist.index[-1].strftime("%Y-%m-%d"),
            "market_cap": market_cap,
        }
    except Exception as e:
        log.warning(f"{ticker} 시세 조회 실패: {e}")
        return None


def replace_marketdata_block(file_path, start_marker, end_marker, new_data_obj):
    """지정된 마커 사이의 const marketData = {...}; 블록을 교체.
    new_data_obj가 None이면(=이번 수집 실패) 파일을 건드리지 않고 그대로 둔다."""
    if new_data_obj is None:
        log.error(f"{file_path}: 신규 데이터 없음 -> 기존 파일 값 유지 (덮어쓰지 않음)")
        return False
    if not os.path.exists(file_path):
        log.error(f"{file_path}: 파일이 존재하지 않습니다.")
        return False
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = re.escape(start_marker) + r"\s*const marketData = \{.*?\};\s*" + re.escape(end_marker)
    payload = json.dumps(new_data_obj, ensure_ascii=False, indent=12)
    replacement = f"{start_marker}\n        const marketData = {payload};\n        {end_marker}"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    else:
        content = re.sub(
            r"const marketData = \{.*?\};",
            f"const marketData = {payload};",
            content, count=1, flags=re.DOTALL,
        )
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"{file_path}: 업데이트 완료")
    return True


# ---------------------------------------------------------------------------
# KOSPI
# ---------------------------------------------------------------------------
def build_kospi_data():
    idx = yf_last_two("^KS11")
    if idx is None:
        return None
    change = idx["close"] - idx["prev_close"]
    pct = (change / idx["prev_close"] * 100) if idx["prev_close"] else 0

    etfs = []
    for name in ["KODEX 200", "TIGER 코리아TOP10", "KODEX 반도체", "TIGER 반도체TOP10", "KODEX 증권"]:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS") if code else None
        if d is None:
            log.warning(f"ETF 시세 누락(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        etfs.append({
            "name": name, "price": fmt_won(d["close"]), "change": fmt_won_change(c),
            "pct": fmt_pct(p), "trend": "down" if c < 0 else "up",
        })

    stocks = []
    for name in ["삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성바이오로직스", "현대차",
                 "기아", "셀트리온", "KB금융", "POSCO홀딩스", "NAVER"]:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS") if code else None
        if d is None:
            log.warning(f"종목 시세 누락(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        stocks.append({
            "name": name, "code": code, "price": f"{d['close']:,.0f}",
            "change": fmt_won_change(c), "pct": fmt_pct(p), "cap": fmt_cap_won(d["market_cap"]),
            "link": f"https://finance.naver.com/item/main.naver?code={code}",
        })

    if not stocks:
        log.error("KOSPI 종목 데이터를 하나도 가져오지 못했습니다.")
        return None

    return {
        "kospi_index": f"{idx['close']:,.2f}",
        "kospi_change": fmt_won_change(change).replace("원", ""),
        "kospi_pct": fmt_pct(pct),
        "market_date": datetime.strptime(idx["date"], "%Y-%m-%d").strftime("%Y년 %-m월 %-d일") + " 장 마감",
        "etfs": etfs,
        "stocks": stocks,
    }


def run_kospi_mode():
    data = build_kospi_data()
    ok = replace_marketdata_block(
        "index.html", "// --- KOSPI_DATA_START ---", "// --- KOSPI_DATA_END ---", data
    )
    return data if ok else None


# ---------------------------------------------------------------------------
# REITs
# ---------------------------------------------------------------------------
def build_reits_data(dart_api_key):
    etfs = []
    for name in REIT_ETF_NAMES:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS") if code else None
        if d is None:
            log.warning(f"REITs ETF 시세 누락(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        etfs.append({
            "name": name, "price": fmt_won(d["close"]), "change": fmt_won_change(c),
            "pct": fmt_pct(p), "cap": fmt_cap_won(d["market_cap"]), "yield": "N/A",
        })

    assets = []
    for name in REIT_ASSET_NAMES:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS") if code else None
        if d is None:
            log.warning(f"REITs 종목코드/시세 확인 필요(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        assets.append({
            "name": name, "code": code, "price": fmt_won(d["close"]), "change": fmt_won_change(c),
            "cap": fmt_cap_won(d["market_cap"]), "yield": "N/A",
            "link": f"https://finance.naver.com/item/main.naver?code={code}",
        })

    if not assets:
        log.error("REITs 종목 데이터를 하나도 가져오지 못했습니다.")
        return None

    disclosures = fetch_dart_disclosures(dart_api_key) if dart_api_key else []
    if not disclosures:
        log.warning("DART 공시 데이터 없음 (DART_API_KEY 미설정 또는 조회 실패) - disclosures 비움")

    return {"etfs": etfs, "assets": assets, "disclosures": disclosures}


def fetch_dart_disclosures(api_key, days_back=5, limit=6):
    """DART Open API 로 최근 리츠 관련 공시를 조회해 실제 rcept_no 기반 링크를 생성."""
    end_de = datetime.now(KST).strftime("%Y%m%d")
    bgn_de = (datetime.now(KST) - timedelta(days=days_back)).strftime("%Y%m%d")
    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": api_key, "bgn_de": bgn_de, "end_de": end_de,
                "page_no": 1, "page_count": 100, "corp_cls": "Y",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "000":
            log.warning(f"DART API 응답 이상: {data.get('status')} {data.get('message')}")
            return []
        results = []
        watch_norm = [n.replace(" ", "") for n in REIT_ASSET_NAMES + REIT_ETF_NAMES + DART_WATCH_NAMES]
        for item in data.get("list", []):
            corp_name = item.get("corp_name", "")
            if any(w in corp_name.replace(" ", "") or corp_name.replace(" ", "") in w for w in watch_norm):
                rcp_no = item.get("rcept_no")
                results.append({
                    "name": corp_name,
                    "title": item.get("report_nm", ""),
                    "date": item.get("rcept_dt", ""),
                    "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}",
                })
        return results[:limit]
    except Exception as e:
        log.warning(f"DART 공시 조회 실패: {e}")
        return []


def run_reits_mode(dart_api_key):
    data = build_reits_data(dart_api_key)
    ok = replace_marketdata_block(
        "reits.html", "// --- REITS_DATA_START ---", "// --- REITS_DATA_END ---", data
    )
    return data if ok else None


# ---------------------------------------------------------------------------
# US Market
# ---------------------------------------------------------------------------
def build_us_market_data():
    macro = []
    for ticker, name in US_MACRO_TICKERS:
        d = yf_last_two(ticker)
        if d is None:
            log.warning(f"미국 지표 조회 실패(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        is_rate = "금리" in name
        val = f"{d['close']:.3f}%" if is_rate else f"{d['close']:,.2f}"
        chg = f"{'+' if c>=0 else ''}{c:.3f}" if is_rate else f"{'+' if c>=0 else ''}{c:,.2f}"
        macro.append({
            "name": name, "val": val, "change": chg, "pct": fmt_pct(p),
            "trend": "down" if c < 0 else "up",
        })

    top30 = []
    for ticker in US_TOP_TICKERS:
        d = yf_last_two(ticker)
        if d is None:
            log.warning(f"미국 종목 조회 실패(건너뜀): {ticker}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        top30.append({
            "ticker": ticker, "price": fmt_usd(d["close"]), "change": fmt_usd_change(c),
            "pct": fmt_pct(p), "cap": fmt_cap_usd(d["market_cap"]),
            "link": f"https://finance.yahoo.com/quote/{ticker}",
        })

    if not macro and not top30:
        return None
    return {"macro": macro, "top30": top30}


def run_us_market_mode():
    data = build_us_market_data()
    ok = replace_marketdata_block(
        "us_market.html", "// --- US_DATA_START ---", "// --- US_DATA_END ---", data
    )
    return data if ok else None


# ---------------------------------------------------------------------------
# Seoul Real Estate (실거래가)
# ---------------------------------------------------------------------------
def fetch_molit_trades(lawd_cd, deal_ymd, api_key, num_rows=100):
    url = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    params = {
        "serviceKey": api_key, "LAWD_CD": lawd_cd, "DEAL_YMD": deal_ymd,
        "numOfRows": num_rows, "pageNo": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        header_msg = root.findtext(".//resultMsg", default="")
        if header_msg and header_msg not in ("OK", "NORMAL SERVICE", ""):
            log.warning(f"실거래가 API 메시지 (LAWD_CD={lawd_cd}): {header_msg}")
        items = root.findall(".//item")
        out = []
        for it in items:
            def g(tag):
                el = it.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            amount_raw = g("dealAmount")
            if not amount_raw:
                continue
            out.append({
                "apt": g("aptNm"), "dong": g("umdNm"), "area": g("excluUseAr"),
                "amount_manwon": int(amount_raw.replace(",", "")),
                "floor": g("floor"), "year": g("dealYear"), "month": g("dealMonth"), "day": g("dealDay"),
            })
        return out
    except Exception as e:
        log.warning(f"실거래가 조회 실패 (LAWD_CD={lawd_cd}): {e}")
        return []


def _fmt_eok(manwon):
    eok, remain = divmod(manwon, 10000)
    if eok > 0:
        return f"{eok}억 {remain:,}만원" if remain else f"{eok}억원"
    return f"{remain:,}만원"


def _naver_land_search_link(apt_name):
    from urllib.parse import quote
    return f"https://m.land.naver.com/search/result/{quote(apt_name)}"


def build_seoul_estate_data(molit_api_key):
    if not molit_api_key:
        log.error("MOLIT_API_KEY 미설정 - 서울 실거래가 조회 불가")
        return None

    now = datetime.now(KST)
    deal_ymd = now.strftime("%Y%m")
    prev_ymd = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")

    all_trades = []
    for gu, code in LAWD_CODES.items():
        trades = fetch_molit_trades(code, deal_ymd, molit_api_key)
        if not trades:
            trades = fetch_molit_trades(code, prev_ymd, molit_api_key)  # 이번달 신고 건이 없으면 전월분
        for t in trades:
            t["gu"] = gu
        all_trades.extend(trades)

    if not all_trades:
        log.error("서울 실거래가 데이터를 하나도 가져오지 못했습니다.")
        return None

    all_trades.sort(key=lambda x: x["amount_manwon"], reverse=True)
    top30 = []
    for t in all_trades[:30]:
        top30.append({
            "gu": t["gu"], "dong": t["dong"], "apt": t["apt"],
            "size": f"{float(t['area']):.2f}㎡", "price": _fmt_eok(t["amount_manwon"]),
            "record": "신고가" if False else "보통",  # 신고가 판정은 과거 데이터 누적이 필요해 후속 과제로 표시
            "link": _naver_land_search_link(t["apt"]),
        })

    core = []
    for t in all_trades:
        if t["apt"] in TARGET_APT:
            core.append({
                "dong": t["dong"], "apt": t["apt"], "size": f"{float(t['area']):.2f}㎡",
                "price": _fmt_eok(t["amount_manwon"]), "record": "보통",
                "link": _naver_land_search_link(t["apt"]),
            })
    # 관심단지별 최고가 1건만 남기기
    seen = set()
    core_dedup = []
    for c in sorted(core, key=lambda x: x["apt"]):
        if c["apt"] not in seen:
            core_dedup.append(c)
            seen.add(c["apt"])

    return {
        "top30": top30,
        "core": core_dedup,
        # 장미상가(구분상가)는 별도의 상업용 부동산 실거래 API/수동 데이터가 필요해
        # 이번 자동화 범위에서 제외했습니다. 아래는 기존 값 유지용 placeholder이며,
        # 실제로는 run_seoul_estate_mode()에서 기존 파일 값을 보존합니다.
        "rose_shops": None,
        "news": None,
    }


def run_seoul_estate_mode(molit_api_key):
    new_data = build_seoul_estate_data(molit_api_key)
    if new_data is None:
        replace_marketdata_block("seoul_estate.html", "// --- SEOUL_ESTATE_DATA_START ---",
                                  "// --- SEOUL_ESTATE_DATA_END ---", None)
        return None

    # rose_shops / news는 자동 수집 대상이 아니므로 기존 파일에서 그대로 가져와 보존
    file_path = "seoul_estate.html"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            old_content = f.read()
        m = re.search(r"const marketData = (\{.*?\});", old_content, re.DOTALL)
        if m:
            try:
                old_data = json.loads(m.group(1))
                new_data["rose_shops"] = old_data.get("rose_shops", [])
                new_data["news"] = old_data.get("news", {})
            except Exception as e:
                log.warning(f"기존 seoul_estate.html 파싱 실패 (rose_shops/news 보존 불가): {e}")
                new_data["rose_shops"] = []
                new_data["news"] = {}
    else:
        new_data["rose_shops"] = []
        new_data["news"] = {}

    ok = replace_marketdata_block(
        file_path, "// --- SEOUL_ESTATE_DATA_START ---", "// --- SEOUL_ESTATE_DATA_END ---", new_data
    )
    return new_data if ok else None


# ---------------------------------------------------------------------------
# Kakao 알림
# ---------------------------------------------------------------------------
def get_kakao_access_token():
    client_id = os.environ.get("KAKAO_CLIENT_ID")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not client_id or not refresh_token:
        log.error("KAKAO_CLIENT_ID / KAKAO_REFRESH_TOKEN 미설정 - 알림 생략")
        return None
    try:
        resp = requests.post(
            "https://kauth.kakao.com/oauth/token",
            data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        body = resp.json()
        if resp.status_code != 200:
            log.error(f"카카오 토큰 갱신 실패 ({resp.status_code}): {body}")
            return None
        # 카카오가 리프레시 토큰을 재발급하는 경우가 있어 안내 로그를 남김 (Actions secret은 자동 갱신되지 않음)
        if "refresh_token" in body:
            log.warning("카카오가 새 refresh_token을 발급했습니다. GitHub Secret KAKAO_REFRESH_TOKEN을 "
                        f"다음 값으로 업데이트해야 합니다: {body['refresh_token'][:10]}... (전체 값은 Actions 로그에서 마스킹됨)")
        return body.get("access_token")
    except Exception as e:
        log.error(f"카카오 토큰 갱신 중 예외: {e}")
        return None


def send_kakao_notification(token, mode, data):
    if not token:
        log.warning(f"[{mode}] 카카오 토큰 없음 - 알림 전송 생략")
        return
    if not data:
        log.warning(f"[{mode}] 전송할 데이터 없음 - 알림 전송 생략")
        return
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "username").lower()
    base_url = f"https://{owner}.github.io/kospi-dashboard/"
    try:
        if mode == "kospi":
            title = "KOSPI 마감 시황 보고"
            summary = f"KOSPI: {data['kospi_index']} ({data['kospi_change']} / {data['kospi_pct']})"
            if data.get("stocks"):
                summary += f"\n1위 {data['stocks'][0]['name']}: {data['stocks'][0]['price']}원"
            target_url = base_url + "index.html"
        elif mode == "reits":
            title = "상장 리츠 및 인프라 시황 보고"
            summary = "리츠 시세 업데이트 완료"
            if data.get("assets"):
                summary = f"{data['assets'][0]['name']}: {data['assets'][0]['price']}"
            target_url = base_url + "reits.html"
        elif mode == "us_market":
            title = "미국 뉴욕 증시 마감 보고"
            summary = "미국 시황 업데이트 완료"
            if data.get("macro"):
                summary = f"S&P 500: {data['macro'][0]['val']} ({data['macro'][0]['pct']})"
            target_url = base_url + "us_market.html"
        elif mode == "seoul_estate":
            title = "서울 부동산 실거래가 분석 보고"
            summary = "서울 아파트 실거래가 업데이트 완료"
            if data.get("core"):
                summary = f"{data['core'][0]['apt']}: {data['core'][0]['price']}"
            target_url = base_url + "seoul_estate.html"
        else:
            return
        template_object = {
            "object_type": "text",
            "text": f"⚙️ {title}\n\n{summary}\n\n바로가기: {target_url}",
            "link": {"web_url": target_url, "mobile_web_url": target_url},
            "buttons": [{"title": "리포트 보기", "link": {"web_url": target_url, "mobile_web_url": target_url}}],
        }
        resp = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data={"template_object": json.dumps(template_object, ensure_ascii=False)},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if resp.status_code != 200:
            log.error(f"[{mode}] 카카오 알림 전송 실패 ({resp.status_code}): {resp.text}")
        else:
            log.info(f"[{mode}] 카카오 알림 전송 완료")
    except Exception as e:
        log.error(f"[{mode}] 카카오 알림 전송 중 예외: {e}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", type=str, required=True,
        choices=["kospi", "reits", "kospi_reits", "us_market", "seoul_estate", "all"],
        help="실행 모드. 시간 기반 자동추론(auto)은 제거됨 - 워크플로가 명시적으로 전달합니다.",
    )
    args = parser.parse_args()
    mode_to_run = args.mode

    dart_key = os.environ.get("DART_API_KEY")
    molit_key = os.environ.get("MOLIT_API_KEY")

    kakao_token = get_kakao_access_token()

    if mode_to_run in ("kospi", "kospi_reits", "all"):
        d = run_kospi_mode()
        send_kakao_notification(kakao_token, "kospi", d)

    if mode_to_run in ("reits", "kospi_reits", "all"):
        d = run_reits_mode(dart_key)
        send_kakao_notification(kakao_token, "reits", d)

    if mode_to_run in ("us_market", "all"):
        d = run_us_market_mode()
        send_kakao_notification(kakao_token, "us_market", d)

    if mode_to_run in ("seoul_estate", "all"):
        d = run_seoul_estate_mode(molit_key)
        send_kakao_notification(kakao_token, "seoul_estate", d)

    log.info("실행 완료")
