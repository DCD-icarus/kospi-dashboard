"""
Dashboard Factory (v3)
=======================
v2 -> v3 변경점:
- REITs 종목코드 조회가 죽은 엔드포인트(ac.finance.naver.com)를 쓰고 있어 전부
  실패했던 문제 수정 (m.stock.naver.com/front-api/search/autoComplete 로 교체)
- 시가배당률을 항상 "N/A"로만 채우던 문제 수정 -> 최근 1년 지급 배당 합산으로 실제 계산
- 시가총액이 비어 있던 종목을 위한 market_cap fallback 체인 추가
- DART 공시가 시장 전체 피드에서 이름매칭만 하다 보니 페이지 밖으로 밀려 누락되던
  문제 수정 -> 관심 종목별로 DART corp_code를 찾아 개별 조회, 표시 개수 제한도 완화
- 실존 인물(워런 버핏 등)에게 가상의 발언을 붙인 "코멘트" 섹션을 전부 제거하고,
  네이버 뉴스 검색 오픈API(공식) 기반 실제 뉴스 피드로 교체
- KOSPI 대시보드의 국내식/해외식 색상 토글 제거 (국내식 고정)

데이터 소스
-----------
- KOSPI 지수 / 국내 대형주 / ETF / 국내 REITs 시세 : yfinance (Yahoo Finance, .KS 티커)
- REITs 공시 : DART Open API (종목별 corp_code 조회, 실제 개별 공시 링크 생성)
- 미국 지수/금리/유가 / 미국 대형주 : yfinance
- 서울 아파트 실거래가 : 공공데이터포털 국토교통부 아파트매매 실거래 상세자료 API
- 시황 관련 뉴스 : 네이버 뉴스 검색 오픈API (공식, openapi.naver.com)

필요한 GitHub Secrets
----------------------
- KAKAO_CLIENT_ID, KAKAO_REFRESH_TOKEN   (기존과 동일)
- DART_API_KEY                            (opendart.fss.or.kr 무료 발급)
- MOLIT_API_KEY                           (data.go.kr 아파트매매 실거래가 상세자료, 무료 자동승인)
- NAVER_CLIENT_ID, NAVER_CLIENT_SECRET    (developers.naver.com, 뉴스 검색 오픈API 무료 발급)

발급 방법은 README_설치가이드.md 참고.
"""

import os
import re
import json
import time
import random
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
_WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def kst_date_label(suffix="기준"):
    """실행 시점(KST) 날짜를 'YYYY년 M월 D일 (요일) {suffix}' 형태로 반환.
    이전 버전은 이 문자열이 화면에 하드코딩되어 있어 실제로는 절대 갱신되지
    않았던 게 '날짜가 항상 옛날로 보이는' 버그의 원인이었습니다."""
    now = datetime.now(KST)
    wd = _WEEKDAYS_KO[now.weekday()]
    return f"{now.year}년 {now.month}월 {now.day}일 ({wd}) {suffix}"


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


def _resolve_market_cap(t, price):
    """market_cap 조회 fallback 체인: fast_info -> info['marketCap'] -> price*발행주식수.
    yfinance의 fast_info는 국내(.KS) 종목에서 종종 비어 있어 3단계로 시도합니다."""
    try:
        mc = t.fast_info.get("market_cap")
        if mc:
            return mc
    except Exception:
        pass
    try:
        info = t.info  # 네트워크 호출 1회 추가 (fast_info 실패시에만 사용)
        mc = info.get("marketCap")
        if mc:
            return mc
        shares = info.get("sharesOutstanding")
        if shares and price:
            return shares * price
    except Exception:
        pass
    return None


def _detect_dividend_frequency(divs):
    """최근 지급 이력의 간격(일)을 분석해 연간 지급 횟수를 추정.
    분기(~90일)=4, 반기(~180일)=2, 연간(~365일)=1. 이력이 1건뿐이면 1로 가정.
    지급 주기가 살짝 밀리거나 당겨져도(영업일 조정 등) 어느 구간에 속하는지로
    판별하므로 캘린더 365일 창(window) 방식보다 배당 누락/중복 위험이 적습니다."""
    if len(divs) < 2:
        return 1
    # 최근 6건(최대) 사이의 간격만 사용 - 오래된 이력에 배당정책 변경분이 섞이는 것 방지
    recent_dates = divs.index[-7:]
    gaps_days = [(recent_dates[i] - recent_dates[i - 1]).days for i in range(1, len(recent_dates))]
    if not gaps_days:
        return 1
    gaps_days.sort()
    median_gap = gaps_days[len(gaps_days) // 2]
    if median_gap <= 45:
        return 12  # 월 배당
    elif median_gap <= 135:
        return 4   # 분기 배당
    elif median_gap <= 270:
        return 2   # 반기 배당
    else:
        return 1   # 연간 배당


def _resolve_trailing_dividend_yield(t, price):
    """지급 주기(분기/반기/연간)를 자동 판별해 '최근 N회 지급분' 합계를 현재가로
    나눈 시가배당률(%). 캘린더 365일 창 대신 지급 횟수 기준으로 세기 때문에,
    지급일 사이 간격 때문에 1회가 걸치거나 빠지는 문제가 없습니다."""
    try:
        divs = t.dividends
        if divs is None or len(divs) == 0 or not price:
            return None
        freq = _detect_dividend_frequency(divs)
        recent_n = divs.iloc[-freq:]
        total = float(recent_n.sum())
        if total <= 0:
            return None
        return total / price * 100
    except Exception:
        return None


def yf_snapshot(ticker, want_dividend=False):
    """최근 2거래일 종가 + 시가총액(+옵션: 배당수익률)을 반환. 실패 시 None."""
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
        price = float(last["Close"])
        result = {
            "close": price,
            "prev_close": float(prev["Close"]),
            "date": hist.index[-1].strftime("%Y-%m-%d"),
            "market_cap": _resolve_market_cap(t, price),
            "dividend_yield": None,
        }
        if want_dividend:
            result["dividend_yield"] = _resolve_trailing_dividend_yield(t, price)
        return result
    except Exception as e:
        log.warning(f"{ticker} 시세 조회 실패: {e}")
        return None


# 하위 호환용 별칭 (기존 코드 곳곳에서 yf_last_two 이름으로 호출)
yf_last_two = yf_snapshot


# ---------------------------------------------------------------------------
# 뉴스 (네이버 뉴스 검색 오픈API - 공식/문서화된 API)
# ---------------------------------------------------------------------------
def fetch_naver_news(query, client_id, client_secret, display=4):
    """네이버 뉴스 검색 오픈API (공식). 실제 기사 제목/링크/날짜를 반환.
    이전 버전의 '거장 코멘트'는 실존 인물에게 가상의 발언을 붙인 가짜 콘텐츠였어서
    전면 제거하고, 실제 검색 결과 기반 뉴스로 교체했습니다."""
    if not client_id or not client_secret:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": display, "sort": "date"},
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("items", []):
            title = re.sub(r"<.*?>", "", item.get("title", "")).replace("&quot;", '"').replace("&amp;", "&")
            link = item.get("originallink") or item.get("link")
            pub = item.get("pubDate", "")
            try:
                date_str = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = pub
            results.append({"title": title, "link": link, "date": date_str, "source": "네이버뉴스"})
        if results:
            log.info(f"네이버 뉴스 조회 성공 ('{query}'): {len(results)}건")
        else:
            log.warning(f"네이버 뉴스 조회 결과 0건 ('{query}') - 검색어와 일치하는 최신 기사가 없거나 API 응답이 비어있음")
        return results
    except Exception as e:
        log.warning(f"네이버 뉴스 조회 실패 ('{query}'): {e}")
        return []


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
def build_kospi_data(naver_id=None, naver_secret=None):
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

    news = fetch_naver_news("코스피 마감 시황", naver_id, naver_secret, display=4)

    return {
        "kospi_index": f"{idx['close']:,.2f}",
        "kospi_change": fmt_won_change(change).replace("원", ""),
        "kospi_pct": fmt_pct(pct),
        "market_date": datetime.strptime(idx["date"], "%Y-%m-%d").strftime("%Y년 %-m월 %-d일") + " 장 마감",
        "etfs": etfs,
        "stocks": stocks,
        "news": news,
    }


def run_kospi_mode(naver_id=None, naver_secret=None):
    data = build_kospi_data(naver_id, naver_secret)
    ok = replace_marketdata_block(
        "index.html", "// --- KOSPI_DATA_START ---", "// --- KOSPI_DATA_END ---", data
    )
    return data if ok else None


# ---------------------------------------------------------------------------
# REITs
# ---------------------------------------------------------------------------
def build_reits_data(dart_api_key, naver_id=None, naver_secret=None):
    etfs = []
    for name in REIT_ETF_NAMES:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS", want_dividend=True) if code else None
        if d is None:
            log.warning(f"REITs ETF 시세 누락(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        p = (c / d["prev_close"] * 100) if d["prev_close"] else 0
        yld = d.get("dividend_yield")
        etfs.append({
            "name": name, "price": fmt_won(d["close"]), "change": fmt_won_change(c),
            "pct": fmt_pct(p), "cap": fmt_cap_won(d["market_cap"]),
            "yield": f"{yld:.2f}%" if yld is not None else "N/A",
        })

    assets = []
    for name in REIT_ASSET_NAMES:
        code = resolve_stock_code(name)
        d = yf_last_two(f"{code}.KS", want_dividend=True) if code else None
        if d is None:
            log.warning(f"REITs 종목코드/시세 확인 필요(건너뜀): {name}")
            continue
        c = d["close"] - d["prev_close"]
        yld = d.get("dividend_yield")
        assets.append({
            "name": name, "code": code, "price": fmt_won(d["close"]), "change": fmt_won_change(c),
            "cap": fmt_cap_won(d["market_cap"]),
            "yield": f"{yld:.2f}%" if yld is not None else "N/A",
            "link": f"https://finance.naver.com/item/main.naver?code={code}",
        })

    if not assets:
        log.error("REITs 종목 데이터를 하나도 가져오지 못했습니다.")
        return None

    disclosures = fetch_dart_disclosures(dart_api_key, limit=30) if dart_api_key else []
    if not disclosures:
        log.warning("DART 공시 데이터 없음 (DART_API_KEY 미설정 또는 조회 실패) - disclosures 비움")

    news = fetch_naver_news("상장리츠", naver_id, naver_secret, display=4)

    return {"etfs": etfs, "assets": assets, "disclosures": disclosures, "news": news, "market_date": kst_date_label()}


DART_CORPCODE_CACHE_FILE = "dart_corpcode_cache.json"


def _load_dart_corpcode_map(api_key):
    """DART corpCode.xml(전체 상장사 고유번호 목록)을 1회 내려받아 이름->corp_code 매핑 생성.
    종목코드(6자리)와 DART 고유번호(8자리)는 다른 체계라 별도 매핑이 필요합니다."""
    if os.path.exists(DART_CORPCODE_CACHE_FILE):
        try:
            with open(DART_CORPCODE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        import io
        import zipfile
        resp = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": api_key}, timeout=20,
        )
        resp.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_bytes = zf.read("CORPCODE.xml")
        root = ET.fromstring(xml_bytes)
        mapping = {}
        for el in root.findall(".//list"):
            corp_name = (el.findtext("corp_name") or "").strip()
            corp_code = (el.findtext("corp_code") or "").strip()
            if corp_name and corp_code:
                mapping[corp_name.replace(" ", "")] = corp_code
        with open(DART_CORPCODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)
        return mapping
    except Exception as e:
        log.warning(f"DART corpCode 매핑 다운로드 실패: {e}")
        return {}


def _recent_business_day_start(n_days):
    """오늘로부터 최근 n영업일 전 날짜(KST)를 반환. 주말만 건너뛰고
    공휴일은 반영하지 않는 단순 계산입니다(한국 공휴일 캘린더 미적용)."""
    d = datetime.now(KST)
    counted = 0
    while counted < n_days:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # 0=월 ... 4=금
            counted += 1
    return d


def fetch_dart_disclosures(api_key, business_days_back=2, limit=30):
    """관심 리츠 종목별(ETF 제외)로 DART 고유번호(corp_code)를 찾아 최근 영업일
    기준으로 개별 조회. (이전 버전은 유가증권시장 전체 공시 피드에서 이름
    문자열매칭으로 걸러냈는데, 하루 공시량이 많으면 페이지 1(100건) 밖으로
    밀려 리츠 공시를 놓칠 수 있었습니다. 종목별로 직접 조회하면 놓치지 않습니다.)"""
    if not api_key:
        return []
    corpcode_map = _load_dart_corpcode_map(api_key)
    if not corpcode_map:
        return []
    end_de = datetime.now(KST).strftime("%Y%m%d")
    bgn_de = _recent_business_day_start(business_days_back).strftime("%Y%m%d")
    results = []
    for name in REIT_ASSET_NAMES:  # ETF(TIGER 리츠부동산인프라 등)는 공시 대상에서 제외
        norm = name.replace(" ", "")
        corp_code = corpcode_map.get(norm)
        if not corp_code:
            for k, v in corpcode_map.items():
                if norm in k or k in norm:
                    corp_code = v
                    break
        if not corp_code:
            log.warning(f"DART 고유번호 매칭 실패(공시 건너뜀): {name}")
            continue
        try:
            resp = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={
                    "crtfc_key": api_key, "corp_code": corp_code,
                    "bgn_de": bgn_de, "end_de": end_de, "page_no": 1, "page_count": 20,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "000":
                for item in data.get("list", []):
                    rcp_no = item.get("rcept_no")
                    results.append({
                        "name": item.get("corp_name", name),
                        "title": item.get("report_nm", ""),
                        "date": item.get("rcept_dt", ""),
                        "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}",
                    })
            elif data.get("status") != "013":  # 013 = 조회 결과 없음(정상적인 무공시)
                log.warning(f"DART 공시 조회 이상 ({name}): {data.get('status')} {data.get('message')}")
        except Exception as e:
            log.warning(f"DART 공시 조회 실패 ({name}): {e}")
    results.sort(key=lambda x: x["date"], reverse=True)
    return results[:limit]


def run_reits_mode(dart_api_key, naver_id=None, naver_secret=None):
    data = build_reits_data(dart_api_key, naver_id, naver_secret)
    ok = replace_marketdata_block(
        "reits.html", "// --- REITS_DATA_START ---", "// --- REITS_DATA_END ---", data
    )
    return data if ok else None


# ---------------------------------------------------------------------------
# US Market
# ---------------------------------------------------------------------------
def build_us_market_data(naver_id=None, naver_secret=None):
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

    news = fetch_naver_news("뉴욕증시 마감", naver_id, naver_secret, display=4)
    return {"macro": macro, "top30": top30, "news": news, "market_date": kst_date_label("NY 마감 기준")}


def run_us_market_mode(naver_id=None, naver_secret=None):
    data = build_us_market_data(naver_id, naver_secret)
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
        "market_date": kst_date_label(),
        "news": None,  # run_seoul_estate_mode()에서 채움
    }


# 관심단지 뉴스 registry: 구(gu)별 그룹핑 + 성격(category)별 색상 표기용 메타데이터.
# category: 재건축 / 재개발 / 신축(준공 10년 미만) / 구축대단지
COMPLEX_REGISTRY = [
    {"key": "jamsil_jugong5", "name": "잠실주공5단지", "gu": "송파구", "category": "재건축"},
    {"key": "jamsil_rose", "name": "잠실 장미아파트", "gu": "송파구", "category": "재건축"},
    {"key": "bangi_seonsuchon", "name": "방이 올림픽선수촌", "gu": "송파구", "category": "구축대단지"},
    {"key": "dunchon_foreon", "name": "둔촌 올림픽파크포레온", "gu": "강동구", "category": "신축"},
    {"key": "garak_helio", "name": "가락 헬리오시티", "gu": "송파구", "category": "신축"},
    {"key": "jamsil_els", "name": "잠실 엘스", "gu": "송파구", "category": "구축대단지"},
    {"key": "jamsil_riesens", "name": "잠실 리센츠", "gu": "송파구", "category": "구축대단지"},
    {"key": "sincheon_parkrio", "name": "신천 파크리오", "gu": "송파구", "category": "구축대단지"},
    {"key": "banpo_onebailey", "name": "반포 원베일리", "gu": "서초구", "category": "신축"},
    {"key": "banpo_124", "name": "반포 124주구(반디클)", "gu": "서초구", "category": "재건축"},
    {"key": "banpo_acro", "name": "반포 아크로리버파크", "gu": "서초구", "category": "구축대단지"},
    {"key": "banpo_xi", "name": "반포자이", "gu": "서초구", "category": "구축대단지"},
    {"key": "banpo_firstige", "name": "반포 래미안퍼스티지", "gu": "서초구", "category": "구축대단지"},
    {"key": "hannam3", "name": "한남3구역(디에이치한남)", "gu": "용산구", "category": "재개발"},
    {"key": "hannam5", "name": "한남5구역", "gu": "용산구", "category": "재개발"},
    {"key": "noryangjin1", "name": "노량진1구역", "gu": "동작구", "category": "재개발"},
    {"key": "noryangjin3", "name": "노량진3구역", "gu": "동작구", "category": "재개발"},
    {"key": "acro_seoulforest", "name": "아크로서울포레스트", "gu": "성동구", "category": "신축"},
    {"key": "seongsu1", "name": "성수전략정비구역 1지구", "gu": "성동구", "category": "재개발"},
    {"key": "hannam_the_hill", "name": "한남더힐", "gu": "용산구", "category": "구축대단지"},
    {"key": "nineone_hannam", "name": "나인원한남", "gu": "용산구", "category": "신축"},
    {"key": "dogok_towerpalace", "name": "도곡동 타워팰리스 1/2/3차", "gu": "강남구", "category": "구축대단지"},
    {"key": "gaepo_firstier", "name": "개포동 디에이치 퍼스티어 아이파크", "gu": "강남구", "category": "신축"},
    {"key": "daechi_eunma", "name": "대치 은마아파트", "gu": "강남구", "category": "재건축"},
    {"key": "yeouido_sibeom", "name": "여의도 시범아파트", "gu": "영등포구", "category": "재건축"},
    {"key": "mokdong7", "name": "목동 신시가지 7단지", "gu": "양천구", "category": "재건축"},
]


def build_seoul_news(naver_id, naver_secret):
    """관심단지 26곳 각각에 대해 실제 네이버 뉴스 검색 결과 1건씩 조회.
    (이전 버전은 4곳 고정 + 하드코딩된 가짜 뉴스 텍스트였습니다.)"""
    from urllib.parse import quote
    news_list = []
    for c in COMPLEX_REGISTRY:
        query = f"{c['name']} 재건축" if c["category"] in ("재건축", "재개발") else c["name"]
        results = fetch_naver_news(query, naver_id, naver_secret, display=1)
        if results:
            item = {**c, "text": results[0]["title"], "link": results[0]["link"]}
        else:
            item = {**c, "text": "관련 뉴스를 찾지 못했습니다.",
                    "link": f"https://search.naver.com/search.naver?query={quote(query)}"}
        news_list.append(item)
    return news_list


def run_seoul_estate_mode(molit_api_key, naver_id=None, naver_secret=None):
    new_data = build_seoul_estate_data(molit_api_key)
    if new_data is None:
        replace_marketdata_block("seoul_estate.html", "// --- SEOUL_ESTATE_DATA_START ---",
                                  "// --- SEOUL_ESTATE_DATA_END ---", None)
        return None

    new_data["news"] = build_seoul_news(naver_id, naver_secret)

    ok = replace_marketdata_block(
        "seoul_estate.html", "// --- SEOUL_ESTATE_DATA_START ---", "// --- SEOUL_ESTATE_DATA_END ---", new_data
    )
    return new_data if ok else None


# ---------------------------------------------------------------------------
# 잠실 장미상가 실거래가 (비공개 모니터링 전용 페이지)
# ---------------------------------------------------------------------------
def fetch_commercial_trades_songpa(molit_api_key, deal_ymd):
    """국토부 상업업무용 부동산 매매 실거래가 API (RTMSDataSvcNrgTrade).
    이 데이터셋은 아파트용과 별개 API라 정확한 응답 필드명을 아직 검증하지
    못했습니다 - 모든 필드를 그대로 dict로 담아 반환하고, 첫 매칭 건의 필드
    목록을 로그로 남겨 실제 스키마를 확인할 수 있게 했습니다."""
    if not molit_api_key:
        return []
    url = "http://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
    try:
        resp = requests.get(url, params={
            "serviceKey": molit_api_key, "LAWD_CD": LAWD_CODES["송파구"],
            "DEAL_YMD": deal_ymd, "numOfRows": 500, "pageNo": 1,
        }, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        header_msg = root.findtext(".//resultMsg", default="")
        if header_msg and header_msg not in ("OK", "NORMAL SERVICE", ""):
            log.warning(f"상업용 실거래가 API 메시지 ({deal_ymd}): {header_msg}")
        items = root.findall(".//item")
        return [{child.tag: (child.text.strip() if child.text else "") for child in it} for it in items]
    except Exception as e:
        log.warning(f"상업용 실거래가 조회 실패 ({deal_ymd}): {e}")
        return []


def _format_floor_label(raw):
    """MOLIT 데이터의 층 표기는 지하를 음수(-1 등)로 주는 경우가 많아 이를
    '지하n층' / '지상n층'으로 변환. 형식이 다르면 원본 값을 그대로 보여줌."""
    if raw is None or raw == "":
        return "-"
    try:
        f = int(raw)
    except (ValueError, TypeError):
        return str(raw)
    if f < 0:
        return f"지하{abs(f)}층"
    return f"지상{f}층"


def _to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _format_commercial_row(row):
    # 실제 응답 필드 확인 결과(2026-07-11 로그): 이 데이터셋에는 건물명 필드가
    # 아예 없습니다 (bldNm 등 존재하지 않음) - 그래서 항상 고정 라벨을 씁니다.
    name = "장미상가(재건축 장미1,2,3차)"
    amount_manwon = _to_float(row.get("dealAmount"))
    price = _fmt_eok(int(amount_manwon)) if amount_manwon else (row.get("dealAmount") or "N/A")

    floor_label = _format_floor_label(row.get("floor"))

    # 면적 필드 = buildingAr(건물면적). plottageAr(대지권면적)은 참고용으로만 남겨둠.
    area_sqm = _to_float(row.get("buildingAr"))
    area_label = f"{area_sqm:.2f}㎡" if area_sqm else "-"

    pyeong_price = None
    pyeong_label = "-"
    if amount_manwon and area_sqm and area_sqm > 0:
        pyeong = area_sqm / 3.3058
        pyeong_price = amount_manwon / pyeong  # 만원/평
        pyeong_label = f"{pyeong_price:,.0f}만원/평"

    y, mo, d = row.get("dealYear", ""), row.get("dealMonth", ""), row.get("dealDay", "")
    date_label = f"{y}-{mo.zfill(2) if mo else ''}-{d.zfill(2) if d else ''}" if y else ""
    deal_dt = None
    try:
        deal_dt = datetime(int(y), int(mo), int(d or "1"), tzinfo=KST)
    except (ValueError, TypeError):
        pass

    return {
        "name": name, "floor": floor_label, "area": area_label, "price": price,
        "pyeong_price": pyeong_label, "date": date_label,
        "_pyeong_price_raw": pyeong_price, "_deal_dt": deal_dt,  # 통계 계산용 (JSON에도 포함되지만 화면에서는 안 씀)
    }


ROSE_TARGET_DONG = "신천동"
ROSE_TARGET_JIBUN = {"7", "11"}  # 아실 확인: 재건축 장미1,2,3차 상가 - 서울시 송파구 신천동 7 / 11


def _normalize_jibun(v):
    """MOLIT 데이터는 지번을 '0007'처럼 0으로 채운 형태로 주는 경우가 많아,
    숫자로 변환 가능하면 앞자리 0을 제거하고 비교합니다."""
    if v is None:
        return None
    v = str(v).strip()
    try:
        return str(int(v))
    except (ValueError, TypeError):
        return v


def _row_matches_rose(row):
    """이름에 '장미'가 들어간 행 OR (법정동=신천동 AND 지번=7|11)인 행을 매칭.
    정확한 MOLIT 필드 태그명이 아직 검증 전이라, 키 이름에 'umd'(법정동)나
    'jibun'/'bonbun'(지번)이 들어간 필드를 유연하게 찾아서 비교하고,
    0으로 채워진 지번 표기('0007' 등)도 정규화해서 비교합니다."""
    values = [v for v in row.values() if isinstance(v, str)]
    if any("장미" in v for v in values):
        return True
    dong_val, jibun_val = None, None
    for k, v in row.items():
        kl = k.lower()
        if "umd" in kl or "dong" in kl:
            dong_val = v
        if "jibun" in kl or "bonbun" in kl:
            jibun_val = _normalize_jibun(v)
    if dong_val == ROSE_TARGET_DONG and jibun_val in ROSE_TARGET_JIBUN:
        return True
    return False


def _months_back(base_dt, n):
    """base_dt로부터 n개월 전의 1일(day=1)을 반환."""
    year, month = base_dt.year, base_dt.month - n
    while month <= 0:
        month += 12
        year -= 1
    return base_dt.replace(year=year, month=month, day=1)


def build_rose_real_trades(molit_api_key):
    """잠실(신천동) 소재 상업용 부동산 실거래 중 장미상가로 추정되는 행만 필터링.
    매칭 기준: ① 건물명 등에 '장미' 포함, ② 법정동=신천동 + 지번=7 또는 11
    (아실에서 확인한 '재건축 장미1,2,3차' 주소 기준). 최근 12개월 조회
    (1개월/3개월/6개월/1년 통계를 내려면 1년치 데이터가 필요합니다)."""
    if not molit_api_key:
        log.warning("MOLIT_API_KEY 없음 - 장미상가 실거래가 조회 생략")
        return []
    now = datetime.now(KST)
    matched, logged_schema = [], False
    for i in range(12):
        ymd = _months_back(now, i).strftime("%Y%m")
        rows = fetch_commercial_trades_songpa(molit_api_key, ymd)
        for row in rows:
            if not logged_schema and row:
                log.info(f"상업용 실거래가 응답 필드 예시({ymd}): {list(row.keys())}")
                logged_schema = True
            if _row_matches_rose(row):
                matched.append(_format_commercial_row(row))
    return matched


def build_rose_stats(matched_rows, now):
    """평단가(거래가/평) 기준 최근 1개월/3개월/6개월/1년 최고·최저·평균 통계."""
    windows = [("1개월", 30), ("3개월", 90), ("6개월", 180), ("1년", 365)]
    stats = []
    for label, days in windows:
        cutoff = now - timedelta(days=days)
        vals = [
            r["_pyeong_price_raw"] for r in matched_rows
            if r.get("_deal_dt") and r["_deal_dt"] >= cutoff and r.get("_pyeong_price_raw")
        ]
        if vals:
            stats.append({
                "label": label, "count": len(vals),
                "max": f"{max(vals):,.0f}만원/평", "min": f"{min(vals):,.0f}만원/평",
                "avg": f"{sum(vals) / len(vals):,.0f}만원/평",
            })
        else:
            stats.append({"label": label, "count": 0, "max": "-", "min": "-", "avg": "-"})
    return stats


# 신이사님이 네이버부동산에서 직접 확인해주신 장미상가 매물 11건의 articleId.
# 리스트/검색 API는 막혀 있어 자동 발견은 안 되고, 이 목록에 있는 매물의
# 상세정보만 매일 갱신합니다. 매물이 추가/삭제되면 이 리스트를 수동으로 갱신해야 합니다.
ROSE_ARTICLE_IDS = [
    "2637267879", "2635413456", "2632272074", "2632270827", "2633793700",
    "2636884585", "2637305176", "2632027465", "2632271578", "2632914018", "2635413792",
]


def fetch_naver_article_detail(article_id):
    """fin.land.naver.com 개별 매물 상세 조회 (비공식 API).
    브라우저로 직접 접속하면 Referer가 없어 {"detailCode":"Error"}가 뜨는 걸
    확인했습니다 - 매물 상세페이지 URL을 Referer로 넣어 우회를 시도합니다.
    처음엔 429 발생 시 지수 백오프로 재시도했는데, 대기시간을 8~34초까지
    늘려도 3번 다 실패하는 게 반복 확인되어(요청 빈도가 아니라 GitHub
    Actions IP 자체가 막혔을 가능성) 재시도를 없애고 1회만 시도합니다.
    이러면 실패해도 몇 초 안에 다음 항목으로 넘어가 전체 실행 시간이
    과도하게 길어지는 걸 막을 수 있습니다."""
    url = "https://fin.land.naver.com/front-api/v1/article/basicInfo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"https://fin.land.naver.com/articles/{article_id}",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(
            url, params={"articleId": article_id, "realEstateType": "D02", "tradeType": "A1"},
            headers=headers, timeout=8,
        )
        if resp.status_code == 429:
            log.warning(f"매물 {article_id} 429(Too Many Requests) - 재시도 없이 건너뜀")
            return None
        resp.raise_for_status()
        data = resp.json()
        if not data or data.get("detailCode") == "Error":
            log.warning(f"매물 {article_id} 조회 거부됨 (Referer 우회 실패 가능성)")
            return None
        return data
    except Exception as e:
        log.warning(f"매물 {article_id} 조회 실패: {e}")
        return None


def _format_naver_shop(article_id, data):
    """정확한 응답 필드명이 검증 전이라, 흔한 후보 키들을 순서대로 시도.
    전부 실패하면 최소한 링크는 살아있도록 '정보없음'으로 채웁니다."""
    name = data.get("articleName") or data.get("atclNm") or "장미상가"
    floor_raw = data.get("floorInfo") or data.get("flrInfo") or data.get("floor") or data.get("flrInfoNm")
    price_raw = (data.get("dealOrWarrantPrc") or data.get("price") or data.get("dealPrice")
                 or data.get("priceInfo"))
    area2 = data.get("area2") or data.get("spc2") or data.get("exclusiveArea")  # 전용면적 추정
    area1 = data.get("area1") or data.get("spc1") or data.get("supplyArea")     # 공급면적 추정
    size = f"{area2}㎡(전용)" if area2 else (f"{area1}㎡(공급)" if area1 else "정보없음")
    return {
        "name": name,
        "floor": str(floor_raw) if floor_raw else "정보없음",
        "size": size,
        "price": str(price_raw) if price_raw else "정보없음",
        "link": f"https://fin.land.naver.com/articles/{article_id}",
    }


def build_rose_shops():
    """확보된 articleId 11건의 매물 호가를 자동 조회. 요청 사이에 텀을 둬서
    이전에 발생했던 429(Too Many Requests) 차단을 피합니다. 실패한 건은
    건너뛰고, 전부 실패하면 None을 반환해 run_rose_watch_mode()에서 기존
    값을 보존합니다."""
    results = []
    logged_schema = False
    for i, aid in enumerate(ROSE_ARTICLE_IDS):
        if i > 0:
            time.sleep(random.uniform(1.5, 2.5))  # 요청 간 최소한의 예의상 텀 (재시도 없으니 길게 둘 필요 없음)
        data = fetch_naver_article_detail(aid)
        if data is None:
            continue
        if not logged_schema:
            log.info(f"네이버 매물 상세 응답 필드 예시(articleId={aid}): {list(data.keys())}")
            logged_schema = True
        results.append(_format_naver_shop(aid, data))
    if not results:
        log.warning(
            "네이버 매물 11건 전부 조회 실패 - 기존 shops 값 보존 "
            "(대기시간을 늘려도 계속 실패해서 요청 빈도 문제가 아니라 "
            "GitHub Actions IP 자체가 차단된 것으로 판단, 재시도는 제거함)"
        )
        return None
    if len(results) < len(ROSE_ARTICLE_IDS):
        log.warning(f"네이버 매물 일부만 조회 성공: {len(results)}/{len(ROSE_ARTICLE_IDS)}건")
    return results


def run_rose_watch_mode(molit_api_key=None):
    """장미상가 페이지: 실거래가(국토부 상업용 실거래 API, 자동) + 호가(네이버
    개별 매물 11건, articleId 기반 자동) 두 섹션을 함께 관리."""
    file_path = "rose_watch.html"
    if not os.path.exists(file_path):
        log.warning(f"{file_path} 없음 - 장미상가 페이지 업데이트 생략 (파일을 저장소에 올려주세요)")
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"const marketData = (\{.*?\});", content, re.DOTALL)
    old_data = {}
    if m:
        try:
            old_data = json.loads(m.group(1))
        except Exception as e:
            log.warning(f"{file_path} 기존 데이터 파싱 실패: {e}")

    real_trades = build_rose_real_trades(molit_api_key)
    real_trade_stats = build_rose_stats(real_trades, datetime.now(KST))
    # 통계 계산에만 쓰인 내부 필드는 JSON 직렬화 전에 제거 (datetime은 직렬화 불가)
    for r in real_trades:
        r.pop("_pyeong_price_raw", None)
        r.pop("_deal_dt", None)

    shops = build_rose_shops()
    if shops is None:
        shops = old_data.get("shops", [])  # 전부 실패 시 기존 값 보존

    new_data = {
        "market_date": kst_date_label(),
        "shops": shops,  # 호가(네이버 개별 매물 11건) - articleId 기반 자동 수집
        "real_trades": real_trades,  # 실거래가(국토부 상업용 부동산 API) - 자동 수집
        "real_trade_stats": real_trade_stats,  # 기간별(1/3/6/12개월) 평단가 최고·최저·평균
        "note": "실거래가·호가 모두 자동 갱신됩니다. 호가는 확보된 매물 11건 기준이며, 신규 매물은 articleId를 추가해야 반영됩니다.",
    }
    ok = replace_marketdata_block(
        file_path, "// --- ROSE_WATCH_DATA_START ---", "// --- ROSE_WATCH_DATA_END ---", new_data
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


def _dashboard_base_url():
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "username").lower()
    return f"https://{owner}.github.io/kospi-dashboard/"


def send_kakao_notification(token, mode, data):
    if not token:
        log.warning(f"[{mode}] 카카오 토큰 없음 - 알림 전송 생략")
        return
    if not data:
        log.warning(f"[{mode}] 전송할 데이터 없음 - 알림 전송 생략")
        return
    base_url = _dashboard_base_url()
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
        elif mode == "rose_watch":
            title = "잠실 장미상가 모니터링 (비공개)"
            n = len(data.get("real_trades", []))
            summary = f"이번 실행에서 실거래 {n}건 확인됨" if n else "이번 기간 신규 실거래 없음 (매물 호가는 페이지에서 확인)"
            target_url = base_url + "rose_watch.html"
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


def send_hub_notification(token):
    """통합 허브 페이지 링크를 매일 07:10 발송. 데이터 의존성이 없는 단순 링크 알림."""
    if not token:
        log.warning("[hub] 카카오 토큰 없음 - 알림 전송 생략")
        return
    target_url = _dashboard_base_url() + "hub.html"
    try:
        template_object = {
            "object_type": "text",
            "text": f"📊 DCD Icarus 통합 대시보드\n\n{kst_date_label('업데이트')}\nKOSPI · REITs · 미국증시 · 서울부동산을 한 곳에서 확인하세요.\n\n바로가기: {target_url}",
            "link": {"web_url": target_url, "mobile_web_url": target_url},
            "buttons": [{"title": "통합 대시보드 열기", "link": {"web_url": target_url, "mobile_web_url": target_url}}],
        }
        resp = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data={"template_object": json.dumps(template_object, ensure_ascii=False)},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if resp.status_code != 200:
            log.error(f"[hub] 카카오 알림 전송 실패 ({resp.status_code}): {resp.text}")
        else:
            log.info("[hub] 카카오 알림 전송 완료")
    except Exception as e:
        log.error(f"[hub] 카카오 알림 전송 중 예외: {e}")


# ---------------------------------------------------------------------------
# 상업용 부동산 뉴스 (SPI + 딜북뉴스) - 신규 아티클 알림 + 전용 페이지
# ---------------------------------------------------------------------------
# 로그인 없이 공개된 아티클 목록 페이지에서 "제목 + 링크"만 가져오고, 신규
# 아티클에 한해 개별 페이지의 og:title/description(검색엔진 미리보기용 공개
# 메타데이터)에서 깔끔한 제목과 짧은 요약만 추가로 가져옵니다. 본문 전체는
# 각 사이트 이용약관상 무단 복제·배포가 금지되어 있어 절대 수집하지 않습니다.
#
# 코어비트(corebeat.co.kr)는 확인 결과 콘텐츠가 자바스크립트로 렌더링되는
# 구조라 일반 HTTP 요청으로는 목록을 가져올 수 없어 이번 범위에서 제외했습니다.
# 정상적으로 제목이 보이는 목록 페이지 URL을 확인해주시면 추가하겠습니다.
CRE_CACHE_FILE = "cre_articles_cache.json"
CRE_PAGE_MAX_ITEMS = 30

CRE_NEWS_SOURCES = [
    {
        "key": "spi",
        "name": "SPI",
        "list_url": "https://seoulpi.io/article/all",
        "pattern": re.compile(r'<a[^>]+href="(/article/(\d{10,}))"[^>]*>(.*?)</a>', re.DOTALL),
        "base_url": "https://seoulpi.io",
        "exclude_ids": set(),
    },
    {
        "key": "dealbook",
        "name": "딜북뉴스",
        "list_url": "https://www.dealbook.co.kr/news/",
        "pattern": re.compile(r'<a[^>]+href="(https://www\.dealbook\.co\.kr/([a-z0-9\-]+)/)"[^>]*>(.*?)</a>', re.DOTALL),
        "base_url": "",
        # 단일 세그먼트라 정규식은 통과하지만 실제 아티클이 아닌 메뉴/유틸 링크
        "exclude_ids": {"news", "introduction", "signin", "membership", "aboutmembership",
                         "tos", "privacy", "shop", "author"},
    },
]


def _load_cre_cache():
    if os.path.exists(CRE_CACHE_FILE):
        try:
            with open(CRE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)  # {"소스:id": {title, summary, link, source, first_seen}}
        except Exception:
            return {}
    return {}


def _save_cre_cache(cache):
    try:
        with open(CRE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"CRE 뉴스 캐시 저장 실패: {e}")


def fetch_news_listing(source, limit=15):
    """소스 설정(source)에 따라 아티클 목록에서 id/제목(원문)/링크만 추출.
    사이트마다 URL 구조가 달라 source별로 정규식 패턴을 따로 씁니다."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(source["list_url"], headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.warning(f"{source['name']} 목록 조회 실패: {e}")
        return []

    articles = []
    for m in source["pattern"].finditer(html):
        path, sid, inner_html = m.group(1), m.group(2), m.group(3)
        if sid in source["exclude_ids"]:
            continue
        title_text = re.sub(r"<[^>]+>", " ", inner_html)
        title_text = re.sub(r"\s+", " ", title_text).strip()
        if not title_text:
            continue
        link = path if path.startswith("http") else source["base_url"] + path
        articles.append({
            "id": f"{source['key']}:{sid}", "raw_title": title_text,
            "link": link, "source": source["name"],
        })

    seen_ids, dedup = set(), []
    for a in articles:
        if a["id"] not in seen_ids:
            seen_ids.add(a["id"])
            dedup.append(a)
    if not dedup:
        log.warning(f"{source['name']} 아티클 파싱 결과 0건 - 페이지 구조가 바뀌었을 수 있음")
    return dedup[:limit]


def fetch_article_meta(link):
    """개별 아티클 페이지의 공개 메타데이터(og:title, og:description)만 추출.
    이건 각 사이트가 검색엔진·SNS 미리보기용으로 이미 공개해둔 정보라, 본문을
    긁는 것과 달리 저작권/약관 문제에서 자유롭습니다."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(link, headers=headers, timeout=10)
        resp.raise_for_status()
        html = resp.text
        title_m = (re.search(r'<meta property="og:title" content="([^"]*)"', html)
                   or re.search(r'<title>([^<]*)</title>', html))
        desc_m = (re.search(r'<meta property="og:description" content="([^"]*)"', html)
                  or re.search(r'<meta name="description" content="([^"]*)"', html))
        title = title_m.group(1).strip() if title_m else None
        summary = desc_m.group(1).strip() if desc_m else None
        return title, summary
    except Exception as e:
        log.warning(f"아티클 메타 조회 실패 ({link}): {e}")
        return None, None


def build_cre_news():
    """등록된 모든 소스에서 목록을 가져오고, 캐시에 없는(신규) 아티클만 상세
    메타를 추가로 조회해 캐시에 누적. 반환값은 화면 표시용 최신 N개 리스트."""
    cache = _load_cre_cache()
    new_ids = []

    for source in CRE_NEWS_SOURCES:
        listing = fetch_news_listing(source)
        for a in listing:
            if a["id"] in cache:
                continue
            title, summary = fetch_article_meta(a["link"])
            cache[a["id"]] = {
                "title": title or a["raw_title"][:80],
                "summary": summary or "",
                "link": a["link"],
                "source": a["source"],
                "first_seen": kst_date_label(""),
            }
            new_ids.append(a["id"])
            time.sleep(random.uniform(1.0, 2.0))  # 상대 서버 배려 차원의 텀

    # 캐시가 무한정 커지지 않도록 최근 N개만 유지 (첫 발견 순 정렬)
    ordered = sorted(cache.items(), key=lambda kv: kv[1].get("first_seen", ""), reverse=True)
    trimmed = dict(ordered[:CRE_PAGE_MAX_ITEMS])
    _save_cre_cache(trimmed)

    display_list = [{"id": k, **v} for k, v in ordered[:CRE_PAGE_MAX_ITEMS]]
    return display_list, new_ids


def run_cre_news_mode(kakao_token):
    file_path = "cre_news.html"
    if not os.path.exists(file_path):
        log.warning(f"{file_path} 없음 - 상업용 부동산 뉴스 페이지 업데이트 생략 (파일을 저장소에 올려주세요)")
        return

    display_list, new_ids = build_cre_news()
    new_data = {"market_date": kst_date_label(), "articles": display_list}
    replace_marketdata_block(file_path, "// --- CRE_NEWS_DATA_START ---", "// --- CRE_NEWS_DATA_END ---", new_data)

    if new_ids:
        log.info(f"CRE 뉴스 신규 아티클 {len(new_ids)}건 발견")
        new_items = [a for a in display_list if a["id"] in new_ids]
        send_cre_news_notification(kakao_token, new_items)
    else:
        log.info("CRE 뉴스 신규 아티클 없음")


def send_cre_news_notification(token, new_articles):
    if not token or not new_articles:
        return
    top = new_articles[:3]
    lines = [f"• [{a['source']}] {a['title'][:40]}" for a in top]
    extra = f" 외 {len(new_articles) - 3}건" if len(new_articles) > 3 else ""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "username").lower()
    target_url = f"https://{owner}.github.io/kospi-dashboard/cre_news.html"
    text = f"📰 상업용 부동산 뉴스 신규 {len(new_articles)}건{extra}\n\n" + "\n".join(lines)
    try:
        template_object = {
            "object_type": "text",
            "text": text[:190],
            "link": {"web_url": target_url, "mobile_web_url": target_url},
            "buttons": [{"title": "뉴스 페이지 보기", "link": {"web_url": target_url, "mobile_web_url": target_url}}],
        }
        resp = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data={"template_object": json.dumps(template_object, ensure_ascii=False)},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if resp.status_code != 200:
            log.error(f"[cre_news] 카카오 알림 전송 실패 ({resp.status_code}): {resp.text}")
        else:
            log.info(f"[cre_news] 카카오 알림 전송 완료 ({len(new_articles)}건)")
    except Exception as e:
        log.error(f"[cre_news] 카카오 알림 전송 중 예외: {e}")




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
    naver_id = os.environ.get("NAVER_CLIENT_ID")
    naver_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not naver_id or not naver_secret:
        log.warning("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 - 뉴스 섹션은 비워집니다.")

    kakao_token = get_kakao_access_token()

    if mode_to_run in ("kospi", "kospi_reits", "all"):
        d = run_kospi_mode(naver_id, naver_secret)
        send_kakao_notification(kakao_token, "kospi", d)

    if mode_to_run in ("reits", "kospi_reits", "all"):
        d = run_reits_mode(dart_key, naver_id, naver_secret)
        send_kakao_notification(kakao_token, "reits", d)

    if mode_to_run in ("us_market", "all"):
        d = run_us_market_mode(naver_id, naver_secret)
        send_kakao_notification(kakao_token, "us_market", d)

    if mode_to_run in ("seoul_estate", "all"):
        d = run_seoul_estate_mode(molit_key, naver_id, naver_secret)
        send_kakao_notification(kakao_token, "seoul_estate", d)

        # 매일 07:10 KST에 도는 이 트리거에 허브 알림 + CRE 뉴스 + 장미상가(비공개) 알림도 함께 발송.
        # rose_watch의 네이버 매물 호가 조회가 가장 불안정한(실패 가능성 높은) 단계라
        # 일부러 맨 뒤에 배치 - 앞의 알림들이 이 단계의 지연/실패에 영향받지 않도록 함
        send_hub_notification(kakao_token)
        run_cre_news_mode(kakao_token)
        rose_d = run_rose_watch_mode(molit_key)
        send_kakao_notification(kakao_token, "rose_watch", rose_d)

    log.info("실행 완료")
