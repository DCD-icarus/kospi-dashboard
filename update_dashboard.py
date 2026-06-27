import urllib.request
import re
import os
import json
import requests
from datetime import datetime

def extract_element_text(html, element_id):
    """HTML 소스코드에서 특정 id를 가진 태그 내부의 텍스트를 안전하게 파싱합니다."""
    pattern = rf'id=["\']?{element_id}["\']?[^>]*?>([\s\S]*?)</'
    match = re.search(pattern, html)
    if match:
        text = re.sub(r'<[^>]+>', '', match.group(1))
        return text.strip()
    return None

def extract_investor_val(html, investor_name):
    """투자 주체별 순매수 테이블에서 지정한 주체(개인, 외국인, 기관)의 값을 파싱합니다."""
    pattern = rf'{investor_name}[\s\S]*?class=["\']?num["\']?[^>]*?>[\s\S]*?>\s*([-+]?[\d,]+)'
    match = re.search(pattern, html)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def fetch_market_data():
    """네이버 금융에서 실시간 코스피 종가, 등락률, 투자자별 수급 데이터를 파싱합니다."""
    print("[1/3] 네이버 금융 시세 데이터 수집 시작...")
    
    url_main = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    req = urllib.request.Request(url_main, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    
    try:
        html = urllib.request.urlopen(req).read().decode('cp949', errors='ignore')
    except Exception as e:
        print(f"[오류] 네이버 금융 메인 페이지 접속 실패: {e}")
        raise e

    now_val = extract_element_text(html, 'now_value')
    if not now_val:
        print("[경고] 코스피 지수 기본 파싱 실패. 대체 정규식을 시도합니다.")
        now_val = re.search(r'id="now_value">([^<]+)', html).group(1)

    change_text = extract_element_text(html, 'change_value_and_direction')
    num_match = re.search(r'([\d.,]+)', change_text) if change_text else None
    num_val = num_match.group(1) if num_match else "0.00"
    is_down = "하락" in change_text or "락" in change_text or "-" in change_text if change_text else False
    is_up = "상승" in change_text or "승" in change_text or "+" in change_text if change_text else False
    direction = "-" if is_down else ("+" if is_up else "")
    change_val = f"{direction}{num_val}"

    rate_text = extract_element_text(html, 'change_rate_and_direction')
    rate_match = re.search(r'([\d.,]+%)', rate_text) if rate_text else None
    rate_val = rate_match.group(1) if rate_match else "0.00%"
    is_down_rate = "하락" in rate_text or "락" in rate_text or "-" in rate_text if rate_text else False
    is_up_rate = "상승" in rate_text or "승" in rate_text or "+" in rate_text if rate_text else False
    direction_rate = "-" if is_down_rate else ("+" if is_up_rate else "")
    change_rate = f"{direction_rate}{rate_val}"

    print(f"-> 수집 성공 - 코스피: {now_val} ({change_rate})")

    print("[2/3] 투자자별 매수/매도 수급 데이터 수집 시작...")
    url_trend = "https://finance.naver.com/sise/sise_trans.naver"
    req_trend = urllib.request.Request(url_trend, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    
    try:
        html_trend = urllib.request.urlopen(req_trend).read().decode('cp949', errors='ignore')
    except Exception as e:
        print(f"[오류] 수급 동향 페이지 접속 실패: {e}")
        raise e

    personal = extract_investor_val(html_trend, '개인')
    foreign = extract_investor_val(html_trend, '외국인')
    institution = extract_investor_val(html_trend, '기관')

    print(f"-> 수급 성공 - 개인: {personal}억 / 외인: {foreign}억 / 기관: {institution}억")

    return {
        "date": datetime.today().strftime('%Y년 %m월 %d일'),
        "kospi_value": now_val,
        "kospi_change": change_val,
        "kospi_percent": change_rate,
        "personal": personal / 10000.0,      
        "foreign": foreign / 10000.0,
        "institution": institution / 10000.0
    }

def update_html_file(data):
    """배포용 index.html 파일 내용을 최신 금융 데이터로 자동 치환합니다."""
    file_path = "index.html"
    
    if not os.path.exists(file_path):
        print(f"[오류] {file_path} 파일이 존재하지 않습니다. 루트 폴더에 index.html을 먼저 올려두셔야 합니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # HTML 내 텍스트 치환
    html_content = re.sub(r'id="kospi-value">.*?<', f'id="kospi-value">{data["kospi_value"]}<', html_content)
    html_content = re.sub(r'id="kospi-change-val">.*?<', f'id="kospi-change-val">{data["kospi_change"]}<', html_content)
    html_content = re.sub(r'id="kospi-change-pct">.*?<', f'id="kospi-change-pct">{data["kospi_percent"]}<', html_content)
    html_content = re.sub(r'id="market-date">.*?<', f'id="market-date">{data["date"]} 장 마감<', html_content)
    
    # Chart.js 데이터 변수 치환
    json_data_regex = r'const netBuyingData = \{.*?\};'
    replacement_json = f"""const netBuyingData = {{
            personal: {data["personal"]:.4f},    
            foreign: {data["foreign"]:.4f},    
            institution: {data["institution"]:.4f}  
        }};"""
    html_content = re.sub(json_data_regex, replacement_json, html_content, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("-> index.html 대시보드 파일 최신 데이터 업데이트 성공!")

def get_kakao_access_token():
    """GitHub Secrets에 저장된 2달짜리 Refresh Token을 활용해 임시 6시간용 Access Token을 발급받습니다."""
    client_id = os.environ.get("KAKAO_CLIENT_ID")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    
    if not client_id or not refresh_token:
        print("[⚠️ 경고] KAKAO_CLIENT_ID 또는 KAKAO_REFRESH_TOKEN 환경변수가 누락되었습니다.")
        return None
        
    url = "https://kauth.kakao.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    response = requests.post(url, data=payload, headers=headers)
    if response.status_code == 200:
        response_data = response.json()
        access_token = response_data.get("access_token")
        
        # 주기적인 Refresh Token 자동 갱신 체크
        new_refresh_token = response_data.get("refresh_token")
        if new_refresh_token:
            print(f"⚠️ [알림] 새로운 REFRESH_TOKEN이 자동 발급되었습니다! 깃허브 Secrets의 KAKAO_REFRESH_TOKEN 값을 아래 값으로 업데이트해주세요:\n{new_refresh_token}")
            
        return access_token
    else:
        print(f"[오류] 카카오 토큰 자동 연장 실패: {response.text}")
        return None

def send_kakao_notification(access_token, data):
    """카카오톡 '나에게 보내기' API로 마감 시황 보고서를 전송합니다."""
    if not access_token:
        return
        
    dashboard_url = f"https://{os.environ.get('GITHUB_REPOSITORY_OWNER', 'username')}.github.io/kospi-dashboard/"
    
    template_object = {
        "object_type": "text",
        "text": (
            f"📈 [{data['date']}] 코스피 마감 보고서\n\n"
            f"■ 코스피: {data['kospi_value']} ({data['kospi_percent']})\n"
            f"■ 개인 수급: {data['personal']:.2f}조 원\n"
            f"■ 외국인 수급: {data['foreign']:.2f}조 원\n"
            f"■ 기관 수급: {data['institution']:.2f}조 원"
        ),
        "link": {
            "web_url": dashboard_url,
            "mobile_web_url": dashboard_url
        },
        "button_title": "실시간 대시보드 이동"
    }
    
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "template_object": json.dumps(template_object, ensure_ascii=False)
    }
    
    response = requests.post(url, data=payload, headers=headers)
    if response.status_code == 200:
        print("[3/3] 카카오톡 나에게 보내기 발송 성공!")
    else:
        print(f"[오류] 카카오톡 전송 실패: {response.text}")

if __name__ == "__main__":
    market_data = fetch_market_data()
    update_html_file(market_data)
    
    access_token = get_kakao_access_token()
    if access_token:
        send_kakao_notification(access_token, market_data)
