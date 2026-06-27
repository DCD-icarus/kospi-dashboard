import urllib.request
import re
import os
import requests
from datetime import datetime

def fetch_market_data():
    """네이버 금융에서 실시간 코스피 종가, 등락률, 투자자별 수급 데이터를 파싱합니다."""
    # 1. KOSPI 메인 정보 파싱
    url_main = "[https://finance.naver.com/sise/sise_index.naver?code=KOSPI](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)"
    req = urllib.request.Request(url_main, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('cp949', errors='ignore')
    
    # 정규표현식으로 종가, 상승폭, 등락률 추출
    now_val = re.search(r'id="now_value">([^<]+)', html).group(1)
    change_val = re.search(r'id="change_value_and_direction">.*?([-+]?\d+\.\d+|[-+]?\d+)', html, re.DOTALL).group(1)
    change_rate = re.search(r'id="change_rate_and_direction">.*?([-+]?\d+\.\d+%)', html, re.DOTALL).group(1)
    
    # 2. 투자자별 순매수 동향 파싱 (금액 단위: 억 원)
    url_trend = "[https://finance.naver.com/sise/sise_trans.naver](https://finance.naver.com/sise/sise_trans.naver)"
    req_trend = urllib.request.Request(url_trend, headers={'User-Agent': 'Mozilla/5.0'})
    html_trend = urllib.request.urlopen(req_trend).read().decode('cp949', errors='ignore')
    
    # 개인, 외국인, 기관 순매수 금액 매칭 (단위: 억 원)
    personal = int(re.search(r'개인.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    foreign = int(re.search(r'외국인.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    institution = int(re.search(r'기관.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    
    return {
        "date": datetime.today().strftime('%Y년 %m월 %d일'),
        "kospi_value": now_val,
        "kospi_change": change_val,
        "kospi_percent": change_rate,
        "personal": personal / 10000.0,      # 조 단위로 전환
        "foreign": foreign / 10000.0,
        "institution": institution / 10000.0
    }

def update_html_file(data):
    """배포용 index.html 파일 내용을 최신 금융 데이터로 자동 치환합니다."""
    file_path = "index.html"
    if not os.path.exists(file_path):
        print(f"[Error] {file_path} 파일이 존재하지 않습니다. 루트 폴더에 배치했는지 확인하세요.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 데이터 주입용 치환 처리
    # 1. 코스피 지수 텍스트 영역 치환
    html_content = re.sub(
        r'id="kospi-value">.*?<', 
        f'id="kospi-value">{data["kospi_value"]}<', 
        html_content
    )
    
    # 2. 수급 차트용 스크립트 데이터 세팅 블록 자동 치환
    json_data_regex = r'const netBuyingData = \{.*?\};'
    replacement_json = f"""const netBuyingData = {{
            personal: {data["personal"]:.4f},    
            foreign: {data["foreign"]:.4f},    
            institution: {data["institution"]:.4f}  
        }};"""
    html_content = re.sub(json_data_regex, replacement_json, html_content, flags=re.DOTALL)
    
    # 3. 날짜 텍스트 영역 업데이트 (id="market-date")
    html_content = re.sub(
        r'id="market-date">.*?<', 
        f'id="market-date">{data["date"]} 장 마감<', 
        html_content
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Dashboard HTML 파일 성공적으로 업데이트 완료!")

def send_telegram_notification(data):
    """텔레그램 봇 API를 사용하여 사용자에게 정기 보고서 메시지를 전송합니다."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않아 알림 발송을 건너뜁니다.")
        return
        
    dashboard_url = f"https://{os.environ.get('GITHUB_REPOSITORY_OWNER', 'username')}.github.io/kospi-dashboard/"
    
    # 텔레그램에 전송할 마크업 텍스트 구성
    message = (
        f"📈 <b>[{data['date']}] 코스피 마감 보고서</b>\n\n"
        f"■ <b>코스피 종가</b>: <code>{data['kospi_value']}</code> ({data['kospi_percent']})\n"
        f"■ <b>개인 수급</b>: <code>{data['personal']:.2f}조 원</code>\n"
        f"■ <b>외국인 수급</b>: <code>{data['foreign']:.2f}조 원</code>\n"
        f"■ <b>기관 수급</b>: <code>{data['institution']:.2f}조 원</code>\n\n"
        f"🔗 <a href='{dashboard_url}'>실시간 인터랙티브 대시보드 보기</a>"
    )
    
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("텔레그램 알림 전송 성공!")
    else:
        print(f"텔레그램 전송 실패: {response.text}")

if __name__ == "__main__":
    market_data = fetch_market_data()
    update_html_file(market_data)
    send_telegram_notification(market_data)
