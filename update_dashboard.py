import urllib.request
import re
import os
import json
import requests
from datetime import datetime

def fetch_market_data():
    """네이버 금융에서 실시간 코스피 종가, 등락률, 투자자별 수급 데이터를 파싱합니다."""
    # 1. KOSPI 종합 정보 파싱
    url_main = "[https://finance.naver.com/sise/sise_index.naver?code=KOSPI](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)"
    req = urllib.request.Request(url_main, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('cp949', errors='ignore')
    
    now_val = re.search(r'id="now_value">([^<]+)', html).group(1)
    change_val = re.search(r'id="change_value_and_direction">.*?([-+]?\d+\.\d+|[-+]?\d+)', html, re.DOTALL).group(1)
    change_rate = re.search(r'id="change_rate_and_direction">.*?([-+]?\d+\.\d+%)', html, re.DOTALL).group(1)
    
    # 2. 투자자별 순매수 동향 파싱 (금액 단위: 억 원)
    url_trend = "[https://finance.naver.com/sise/sise_trans.naver](https://finance.naver.com/sise/sise_trans.naver)"
    req_trend = urllib.request.Request(url_trend, headers={'User-Agent': 'Mozilla/5.0'})
    html_trend = urllib.request.urlopen(req_trend).read().decode('cp949', errors='ignore')
    
    personal = int(re.search(r'개인.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    foreign = int(re.search(r'외국인.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    institution = int(re.search(r'기관.*?class=".*?">([-+]?[\d,]+)', html_trend, re.DOTALL).group(1).replace(',', ''))
    
    return {
        "date": datetime.today().strftime('%Y년 %m월 %d일'),
        "kospi_value": now_val,
        "kospi_change": change_val,
        "kospi_percent": change_rate,
        "personal": personal / 10000.0,      # 조 단위로 변환
        "foreign": foreign / 10000.0,
        "institution": institution / 10000.0
    }

def update_html_file(data):
    """배포용 index.html 파일 내용을 최신 금융 데이터로 자동 치환합니다."""
    file_path = "index.html"
    if not os.path.exists(file_path):
        print(f"[Error] {file_path} 파일이 존재하지 않습니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 데이터 주입용 치환 처리
    html_content = re.sub(r'id="kospi-value">.*?<', f'id="kospi-value">{data["kospi_value"]}<', html_content)
    
    json_data_regex = r'const netBuyingData = \{.*?\};'
    replacement_json = f"""const netBuyingData = {{
            personal: {data["personal"]:.4f},    
            foreign: {data["foreign"]:.4f},    
            institution: {data["institution"]:.4f}  
        }};"""
    html_content = re.sub(json_data_regex, replacement_json, html_content, flags=re.DOTALL)
    
    html_content = re.sub(r'id="market-date">.*?<', f'id="market-date">{data["date"]} 장 마감<', html_content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Dashboard HTML 파일 성공적으로 업데이트 완료!")

def get_kakao_access_token():
    """GitHub Secrets에 저장된 2달짜리 Refresh Token을 활용해 임시 6시간용 Access Token을 받아옵니다."""
    client_id = os.environ.get("KAKAO_CLIENT_ID")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    
    if not client_id or not refresh_token:
        print("[오류] KAKAO_CLIENT_ID 또는 KAKAO_REFRESH_TOKEN 환경변수가 누락되었습니다.")
        return None
        
    url = "[https://kauth.kakao.com/oauth/token](https://kauth.kakao.com/oauth/token)"
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
        
        # 만약 카카오 정책에 따라 Refresh Token이 갱신되었다면 로그에 출력하여 업데이트를 유도합니다.
        new_refresh_token = response_data.get("refresh_token")
        if new_refresh_token:
            print(f"⚠️ [중요] 새로운 REFRESH_TOKEN이 발급되었습니다! 아래 토큰을 복사하여 GitHub Secrets를 꼭 업데이트해 주세요:\n{new_refresh_token}")
            
        return access_token
    else:
        print(f"[오류] 카카오 토큰 갱신 실패: {response.text}")
        return None

def send_kakao_notification(access_token, data):
    """카카오톡 '나에게 보내기' API를 호출하여 메시지를 전송합니다."""
    if not access_token:
        return
        
    dashboard_url = f"https://{os.environ.get('GITHUB_REPOSITORY_OWNER', 'username')}.github.io/kospi-dashboard/"
    
    # 카카오톡 템플릿 양식 정의
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
    
    url = "[https://kapi.kakao.com/v2/api/talk/memo/default/send](https://kapi.kakao.com/v2/api/talk/memo/default/send)"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "template_object": json.dumps(template_object, ensure_ascii=False)
    }
    
    response = requests.post(url, data=payload, headers=headers)
    if response.status_code == 200:
        print("카카오톡 나에게 보내기 전송 성공!")
    else:
        print(f"카카오톡 전송 실패: {response.text}")

if __name__ == "__main__":
    market_data = fetch_market_data()
    update_html_file(market_data)
    
    # 카카오 토큰 자동 갱신 후 발송 실행
    access_token = get_kakao_access_token()
    if access_token:
        send_kakao_notification(access_token, market_data)
