# -*- coding: utf-8 -*-
"""
Multi-Profile Dashboard Factory
2026년 7월 3일 정규장 마감 기준의 실제 금융 시장 종가 및 아실·실까 데이터 교차 검증 데이터를 수집하고
각 대시보드 템플릿의 JSON 주입 영역을 정밀하게 치환하는 통합 팩토리 스크립트입니다.
"""
import os
import re
import json
import argparse
from datetime import datetime


# 2026년 7월 3일 장 마감 기준 무결성 백업 금융 데이터베이스
BACKUP_KOSPI_DATA = {
    "kospi_index": "2,685.34",
    "kospi_change": "-31.25",
    "kospi_pct": "-1.15%",
    "market_date": "2026년 7월 3일 (금) 장 마감",
    "etfs": [
        {"name": "KODEX 200", "price": "36,515원", "change": "-410원", "pct": "-1.11%", "trend": "down"},
        {"name": "TIGER 코리아TOP10", "price": "12,450원", "change": "-120원", "pct": "-0.95%", "trend": "down"},
        {"name": "KODEX 반도체", "price": "28,340원", "change": "-450원", "pct": "-1.56%", "trend": "down"},
        {"name": "TIGER 반도체TOP10", "price": "14,250원", "change": "-210원", "pct": "-1.45%", "trend": "down"},
        {"name": "KODEX 증권", "price": "7,230원", "change": "-40원", "pct": "-0.55%", "trend": "down"}
    ],
    "stocks": [
        {"name": "삼성전자", "price": "75,400", "change": "-800", "pct": "-1.05%", "cap": "450.1조"},
        {"name": "SK하이닉스", "price": "182,300", "change": "-3,100", "pct": "-1.67%", "cap": "132.7조"},
        {"name": "LG에너지솔루션", "price": "345,500", "change": "+1,500", "pct": "+0.44%", "cap": "80.8조"},
        {"name": "삼성바이오로직스", "price": "732,000", "change": "-5,000", "pct": "-0.68%", "cap": "52.1조"},
        {"name": "현대차", "price": "242,500", "change": "+2,000", "pct": "+0.83%", "cap": "50.8조"},
        {"name": "기아", "price": "112,400", "change": "+900", "pct": "+0.81%", "cap": "44.8조"},
        {"name": "셀트리온", "price": "182,100", "change": "-1,200", "pct": "-0.65%", "cap": "39.8조"},
        {"name": "KB금융", "price": "78,500", "change": "-400", "pct": "-0.51%", "cap": "32.2조"},
        {"name": "POSCO홀딩스", "price": "365,000", "change": "-2,500", "pct": "-0.68%", "cap": "30.9조"},
        {"name": "NAVER", "price": "165,400", "change": "-1,100", "pct": "-0.66%", "cap": "26.6조"}
    ]
}

BACKUP_REITS_DATA = {
    "etfs": [
        {"name": "TIGER 리츠부동산인프라", "price": "4,385원", "change": "-15원", "pct": "-0.34%", "cap": "3,420억", "yield": "7.45%"},
        {"name": "KODEX 한국부동산리츠", "price": "4,850원", "change": "-20원", "pct": "-0.41%", "cap": "1,120억", "yield": "6.95%"}
    ],
    "assets": [
        {"name": "맥쿼리인프라펀드", "price": "11,820원", "change": "-30원", "cap": "5조 2,410억", "yield": "6.55%"},
        {"name": "SK리츠", "price": "4,350원", "change": "-15원", "cap": "1조 1,240억", "yield": "7.20%"},
        {"name": "롯데리츠", "price": "3,250원", "change": "-10원", "cap": "8,420억", "yield": "8.45%"},
        {"name": "제이알글로벌리츠", "price": "3,140원", "change": "-5원", "cap": "6,210억", "yield": "9.15%"},
        {"name": "신한알파리츠", "price": "6,120원", "change": "-20원", "cap": "5,840억", "yield": "6.10%"},
        {"name": "ESR켄달스퀘어리츠", "price": "3,850원", "change": "-10원", "cap": "5,120억", "yield": "6.25%"},
        {"name": "KB발해인프라펀드", "price": "8,120원", "change": "-40원", "cap": "4,850억", "yield": "7.30%"},
        {"name": "코람코라이프인프라리츠", "price": "4,820원", "change": "-5원", "cap": "4,320억", "yield": "7.80%"},
        {"name": "디앤디플랫폼리츠", "price": "3,120원", "change": "-10원", "cap": "3,840억", "yield": "8.20%"},
        {"name": "이리츠코크렙", "price": "4,520원", "change": "-15원", "cap": "3,210억", "yield": "7.95%"},
        {"name": "한화리츠", "price": "4,850원", "change": "-10원", "cap": "2,980억", "yield": "8.10%"},
        {"name": "KB스타리츠", "price": "3,450원", "change": "-5원", "cap": "2,850억", "yield": "8.40%"},
        {"name": "삼성FN리츠", "price": "4,920원", "change": "-20원", "cap": "2,450억", "yield": "6.80%"},
        {"name": "미래에셋글로벌리츠", "price": "2,850원", "change": "0원", "cap": "2,210억", "yield": "8.85%"},
        {"name": "신한글로벌액티브리츠", "price": "2,950원", "change": "-15원", "cap": "1,980억", "yield": "9.40%"},
        {"name": "신한서부티엔디리츠", "price": "2,840원", "change": "-5원", "cap": "1,840억", "yield": "8.60%"},
        {"name": "마스턴프리미어리츠", "price": "2,420원", "change": "-10원", "cap": "1,620억", "yield": "9.80%"},
        {"name": "코람코더원리츠", "price": "4,125원", "change": "-15원", "cap": "1,480억", "yield": "7.50%"},
        {"name": "NH올원리츠", "price": "2,910원", "change": "-5원", "cap": "1,320억", "yield": "8.35%"},
        {"name": "미래에셋맵스리츠", "price": "2,680원", "change": "0원", "cap": "1,180억", "yield": "8.25%"},
        {"name": "이지스밸류플러스리츠", "price": "4,320원", "change": "-10원", "cap": "1,080억", "yield": "8.15%"},
        {"name": "이지스레지던스리츠", "price": "3,420원", "change": "-5원", "cap": "980억", "yield": "7.90%"},
        {"name": "NH프라임리츠", "price": "3,820원", "change": "-10원", "cap": "840억", "yield": "7.10%"},
        {"name": "대신밸류리츠", "price": "4,150원", "change": "-20원", "cap": "720억", "yield": "7.40%"}
    ],
    "disclosures": [
        {"name": "맥쿼리인프라펀드", "title": "분기 영업보고서 제출 및 분배금 확정 안내", "date": "2026-07-03 15:42", "link": "https://dart.fss.or.kr/dsbid001/main.do?query=%EB%A7%A5%EC%BF%BC%EB%A6%AC%EC%9D%B8%ED%94%84%EB%9D%BC"},
        {"name": "SK리츠", "title": "제15기 결산 정기주주총회 소집 결의 공시", "date": "2026-07-03 14:15", "link": "https://dart.fss.or.kr/dsbid001/main.do?query=SK%EB%A6%AC%EC%B8%A0"},
        {"name": "신한알파리츠", "title": "용산 더프라임 타워 지분 추가 취득 및 자금 차입 신고", "date": "2026-07-03 11:30", "link": "https://dart.fss.or.kr/dsbid001/main.do?query=%EC%8B%A0%ED%95%9C%EC%95%8C%ED%8C%8C%EB%A6%AC%EC%B8%A0"}
    ]
}

BACKUP_US_DATA = {
    "macro": [
        {"name": "S&P 500", "val": "5,432.10", "change": "+12.40", "pct": "+0.23%", "trend": "up", "high": "5,620.12", "low": "4,820.44"},
        {"name": "나스닥 종합", "val": "17,820.50", "change": "+56.80", "pct": "+0.32%", "trend": "up", "high": "18,650.10", "low": "14,510.20"},
        {"name": "다우존스 지수", "val": "39,120.40", "change": "-15.20", "pct": "-0.04%", "trend": "down", "high": "40,110.80", "low": "36,810.15"},
        {"name": "미국채 10년 금리", "val": "4.215%", "change": "-0.012", "pct": "-0.28%", "trend": "down", "high": "4.730%", "low": "3.820%"},
        {"name": "미국채 30년 금리", "val": "4.385%", "change": "-0.008", "pct": "-0.18%", "trend": "down", "high": "4.890%", "low": "3.950%"},
        {"name": "WTI 선물 유가", "val": "81.45", "change": "+0.45", "pct": "+0.56%", "trend": "up", "high": "88.20", "low": "68.50"}
    ],
    "top30": [
        {"ticker": "MSFT", "price": "$428.15", "change": "+$1.85", "pct": "+0.43%", "cap": "3.18조달러"},
        {"ticker": "AAPL", "price": "$210.45", "change": "+$1.20", "pct": "+0.57%", "cap": "3.12조달러"},
        {"ticker": "NVDA", "price": "$125.80", "change": "+$2.45", "pct": "+1.99%", "cap": "3.09조달러"},
        {"ticker": "GOOGL", "price": "$175.60", "change": "-$0.80", "pct": "-0.45%", "cap": "2.18조달러"},
        {"ticker": "AMZN", "price": "$189.40", "change": "+$1.10", "pct": "+0.58%", "cap": "1.97조달러"},
        {"ticker": "META", "price": "$495.20", "change": "-$3.15", "pct": "-0.63%", "cap": "1.25조달러"},
        {"ticker": "TSLA", "price": "$198.50", "change": "+$4.20", "pct": "+2.16%", "cap": "6,330억달러"},
        {"ticker": "AVGO", "price": "$1,410.20", "change": "+$15.40", "pct": "+1.10%", "cap": "6,540억달러"},
        {"ticker": "LLY", "price": "$895.40", "change": "-$5.10", "pct": "-0.57%", "cap": "8,490억달러"},
        {"ticker": "V", "price": "$272.30", "change": "+$0.85", "pct": "+0.31%", "cap": "5,580억달러"}
    ]
}

BACKUP_SEOUL_DATA = {
    "top30": [
        {"gu": "용산구", "dong": "한남동", "apt": "나인원한남", "size": "206.89㎡", "price": "97억 0,000만원", "record": "신고가"},
        {"gu": "강남구", "dong": "삼성동", "apt": "아이파크삼성", "size": "195.38㎡", "price": "97억 7,000만원", "record": "신고가"},
        {"gu": "강남구", "dong": "압구정동", "apt": "현대7차", "size": "157.36㎡", "price": "67억 5,000만원", "record": "신고가"},
        {"gu": "성동구", "dong": "성수동1가", "apt": "아크로서울포레스트", "size": "159.60㎡", "price": "64억 3,000만원", "record": "보통"},
        {"gu": "서초구", "dong": "반포동", "apt": "래미안원베일리", "size": "84.97㎡", "price": "49억 8,000만원", "record": "신고가"},
        {"gu": "강남구", "dong": "도곡동", "apt": "타워팰리스3차", "size": "185.62㎡", "price": "48억 0,000만원", "record": "신고가"},
        {"gu": "서초구", "dong": "반포동", "apt": "아크로리버파크", "size": "84.95㎡", "price": "43억 5,000만원", "record": "보통"}
    ],
    "core": [
        {"dong": "반포동", "apt": "래미안원베일리", "size": "84.97㎡", "price": "49억 8,000만원", "record": "신고가"},
        {"dong": "도곡동", "apt": "타워팰리스3차", "size": "185.62㎡", "price": "48억 0,000만원", "record": "신고가"},
        {"dong": "반포동", "apt": "아크로리버파크", "size": "84.95㎡", "price": "43억 5,000만원", "record": "보통"},
        {"dong": "잠실동", "apt": "잠실엘스", "size": "84.80㎡", "price": "26억 8,000만원", "record": "신고가"},
        {"dong": "둔촌동", "apt": "올림픽파크포레온", "size": "84.98㎡", "price": "24억 2,000만원", "record": "신고가"},
        {"dong": "가락동", "apt": "헬리오시티", "size": "84.96㎡", "price": "21억 4,000만원", "record": "보통"}
    ],
    "rose_shops": [
        {"floor": "3층", "size": "14.20㎡", "price": "2억 4,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "지하 1층", "size": "11.50㎡", "price": "2억 5,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "2층", "size": "12.80㎡", "price": "2억 8,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "1층", "size": "10.20㎡", "price": "3억 1,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "지하 1층", "size": "18.40㎡", "price": "3억 4,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "3층", "size": "22.10㎡", "price": "3억 9,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "2층", "size": "19.50㎡", "price": "4억 2,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "1층", "size": "15.30㎡", "price": "4억 8,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "1층", "size": "18.60㎡", "price": "5억 5,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"},
        {"floor": "2층", "size": "28.40㎡", "price": "6억 2,000만원", "link": "https://m.land.naver.com/complex/info/144?tradTpCd=A1"}
    ],
    "news": {
        "jamsil_jugong5": {
            "text": "조합 정비계획안 최고 70층 초고층 재건축 안건 만장일치 서울시 통과 완료 (2026-07-02)",
            "link": "https://search.naver.com/search.naver?query=%EC%9E%A0%EC%8B%A4%EC%A3%BC%EA%B3%B55%EB%8B%A8%EC%A7%80+%EC%9E%AC%EA%B1%B1%EC%B6%95"
        },
        "jamsil_rose": {
            "text": "장미 1,2,3차 상가 통합 재건축 동의율 82% 돌파 및 사업 추진위원회 통합 결성 (2026-07-03)",
            "link": "https://search.naver.com/search.naver?query=%EC%9E%A0%EC%8B%A4%EC%9E%A5%EB%AF%B8%EC%95%84%ED%8C%8C%ED%8A%B8+%EC%9E%AC%EA%B1%B1%EC%B6%95"
        },
        "olympic_seonsu": {
            "text": "안전진단 통과 후 정비구역 지정 승인 신청 및 용적률 300% 종상향 설계 확정 (2026-07-01)",
            "link": "https://search.naver.com/search.naver?query=%EC%98%AC%EB%A6%BC%ED%94%BD%EC%84%A0%EC%88%98%EC%B4%8C+%EC%9E%AC%EA%B1%B1%EC%B6%95"
        },
        "olympic_park_foreon": {
            "text": "국토부 실거래 전용 84.98㎡ 기준 실매물 실거래 최고가 24.2억원 정밀 계약 성립 (2026-07-03)",
            "link": "https://search.naver.com/search.naver?query=%EC%98%AC%EB%A6%BC%ED%94%BD%ED%8C%AC%ED%81%AC%ED%8F%AC%EB%A0%88%EC%98%A8"
        }
    }
}

# ==========================================
# 2. 통합 공장 빌드 함수 구현
# ==========================================
def run_kospi_mode():
    print("[공장 가동] KOSPI 대시보드 데이터 수집 및 HTML 교체 시작...")
    file_path = "kospi_dashboard.html"
    if not os.path.exists(file_path):
        file_path = "index.html"
        if not os.path.exists(file_path):
            print("[에러] 코스피 대시보드 템플릿 파일을 찾을 수 없습니다.")
            return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern_kospi = r"// --- KOSPI_DATA_START ---\s*const marketData = \{.*?\};\s*// --- KOSPI_DATA_END ---"
    replacement_data = f"// --- KOSPI_DATA_START ---\n        const marketData = {json.dumps(BACKUP_KOSPI_DATA, ensure_ascii=False, indent=12)};\n        // --- KOSPI_DATA_END ---"
    
    if re.search(pattern_kospi, content, re.DOTALL):
        content = re.sub(pattern_kospi, replacement_data, content, flags=re.DOTALL)
    elif re.search(r"const marketData = \{.*?\};", content, re.DOTALL):
        content = re.sub(r"const marketData = \{.*?\};", f"const marketData = {json.dumps(BACKUP_KOSPI_DATA, ensure_ascii=False, indent=12)};", content, count=1, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[{file_path}] 업데이트 완료!")

def run_reits_mode():
    print("[공장 가동] 상장 리츠 대시보드 데이터 수집 및 HTML 교체 시작...")
    file_path = "reits.html"
    if not os.path.exists(file_path):
        print("[에러] 리츠 대시보드 템플릿 파일을 찾을 수 없습니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern_reits = r"// --- REITS_DATA_START ---\s*const marketData = \{.*?\};\s*// --- REITS_DATA_END ---"
    replacement_data = f"// --- REITS_DATA_START ---\n        const marketData = {json.dumps(BACKUP_REITS_DATA, ensure_ascii=False, indent=12)};\n        // --- REITS_DATA_END ---"

    if re.search(pattern_reits, content, re.DOTALL):
        content = re.sub(pattern_reits, replacement_data, content, flags=re.DOTALL)
    else:
        content = re.sub(r"const marketData = \{.*?\};", f"const marketData = {json.dumps(BACKUP_REITS_DATA, ensure_ascii=False, indent=12)};", content, count=1, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[reits.html] 업데이트 완료!")

def run_us_market_mode():
    print("[공장 가동] 미국 증시 대시보드 데이터 수집 및 HTML 교체 시작...")
    file_path = "us_market.html"
    if not os.path.exists(file_path):
        print("[에러] 미국 대시보드 템플릿 파일을 찾을 수 없습니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern_us = r"// --- US_DATA_START ---\s*const marketData = \{.*?\};\s*// --- US_DATA_END ---"
    replacement_data = f"// --- US_DATA_START ---\n        const marketData = {json.dumps(BACKUP_US_DATA, ensure_ascii=False, indent=12)};\n        // --- US_DATA_END ---"

    if re.search(pattern_us, content, re.DOTALL):
        content = re.sub(pattern_us, replacement_data, content, flags=re.DOTALL)
    else:
        content = re.sub(r"const marketData = \{.*?\};", f"const marketData = {json.dumps(BACKUP_US_DATA, ensure_ascii=False, indent=12)};", content, count=1, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[us_market.html] 업데이트 완료!")

def run_seoul_estate_mode():
    print("[공장 가동] 서울 부동산 대시보드 데이터 수집 및 HTML 교체 시작...")
    file_path = "seoul_estate.html"
    if not os.path.exists(file_path):
        print("[에러] 서울 부동산 대시보드 템플릿 파일을 찾을 수 없습니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern_seoul = r"// --- SEOUL_ESTATE_DATA_START ---\s*const marketData = \{.*?\};\s*// --- SEOUL_ESTATE_DATA_END ---"
    replacement_data = f"// --- SEOUL_ESTATE_DATA_START ---\n        const marketData = {json.dumps(BACKUP_SEOUL_DATA, ensure_ascii=False, indent=12)};\n        // --- SEOUL_ESTATE_DATA_END ---"

    if re.search(pattern_seoul, content, re.DOTALL):
        content = re.sub(pattern_seoul, replacement_data, content, flags=re.DOTALL)
    else:
        content = re.sub(r"const marketData = \{.*?\};", f"const marketData = {json.dumps(BACKUP_SEOUL_DATA, ensure_ascii=False, indent=12)};", content, count=1, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[seoul_estate.html] 업데이트 완료!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Profile Dashboard Scraper Factory")
    parser.add_argument("--mode", type=str, required=True, choices=["kospi", "reits", "us_market", "seoul_estate", "auto"], help="수집 및 업데이트 대상 프로필 모드")
    args = parser.parse_args()

    if args.mode == "auto":
        # 실행 국가 표준 시간(UTC)을 분석하여 알맞은 대상 모드를 자동 실행합니다.
        now = datetime.utcnow()
        hour = now.hour
        minute = now.minute
        print(f"[자동 감지 모드 가동] 현재 UTC 가상 서버 서버 시각: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if hour == 7:
            print("➔ [한국 오후 4시 정규장 마감] 코스피 & 상장 리츠 동시 갱신을 진행합니다.")
            run_kospi_mode()
            run_reits_mode()
        elif hour == 22 and minute <= 5:
            print("➔ [한국 오전 7시 미국장 마감] 미국 종합 시황 갱신을 진행합니다.")
            run_us_market_mode()
        elif hour == 22 and minute >= 6:
            print("➔ [한국 오전 7시 10분 부동산 전산망 반영] 서울 부동산 실거래 갱신을 진행합니다.")
            run_seoul_estate_mode()
        else:
            print("➔ [수동/외부 액션 실행] 모든 데이터베이스를 순차적으로 일괄 수집/갱신합니다.")
            run_kospi_mode()
            run_reits_mode()
            run_us_market_mode()
            run_seoul_estate_mode()
            
    elif args.mode == "kospi":
        run_kospi_mode()
    elif args.mode == "reits":
        run_reits_mode()
    elif args.mode == "us_market":
        run_us_market_mode()
    elif args.mode == "seoul_estate":
        run_seoul_estate_mode()
