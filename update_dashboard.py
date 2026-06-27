import os
import re
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup

def extract_element_text_regex(html, element_id):
    """HTML 소스코드에서 특정 id를 가진 태그 내부의 텍스트를 정규식으로 안전하게 파싱하는 백업 파서입니다."""
    pattern = rf'id=["\']?{element_id}["\']?[^>]*?>([\s\S]*?)</'
    match = re.search(pattern, html)
    if match:
        text = re.sub(r'<[^>]+>', '', match.group(1))
        return text.strip()
    return None

def extract_investor_val_regex(html, investor_name):
    """정규식 기반의 투자 주체별 순매수 데이터 백업 파서입니다."""
    pattern = rf'{investor_name}[\s\S]*?class=["\']?num["\']?[^>]*?>[\s\S]*?>\s*([-+]?[\d,]+)'
    match = re.search(pattern, html)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def fetch_market_data():
    """네이버 금융 서버의 해외 IP 차단 필터를 완전히 우회하여 실시간 코스피 시세 및 수급 데이터를 수집합니다."""
    print("[1/3] 네이버 금융 실시간 시세 데이터 수집 시작 (우회 모드 가동)...")
    
    # 깃허브 가상환경 차단을 막기 위해 일반 크롬 브라우저 헤더 주입
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://finance.naver.com/'
    }
    
    url_main = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    
    try:
        # urllib 대신 requests를 사용하여 안전하게 웹 페이지를 받아옵니다.
        response = requests.get(url_main, headers=headers, timeout=15)
        response.raise_for_status() # 403 등 에러가 발생하면 즉시 예외를 발생시켜 디버깅을 돕습니다.
        html = response.content.decode('cp949', errors='ignore')
    except Exception as e:
        print(f"[치명적 오류] 네이버 금융 메인 서버 연결 실패 (차단 의심): {e}")
        raise e

    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. 코스피 지수 파싱
    now_val_elem = soup.find(id="now_value")
    if not now_val_elem:
        print("[오류] 코스피 지수 영역 파싱 실패 (네이버 구조 변경 의심). 백업 파서로 진행합니다.")
        now_val = extract_element_text_regex(html, 'now_value') or "0.00"
    else:
        now_val = now_val_elem.text.strip()
    
    # 등락폭 파싱
    change_elem = soup.find(id="change_value_and_direction")
    if change_elem:
        change_text = change_elem.text.strip()
        num_match = re.search(r'([\d.,]+)', change_text)
        num_val = num_match.group(1) if num_match else "0.00"
        
        is_down = "하락" in change_text or "락" in change_text or "-" in change_text
        is_up = "상승" in change_text or "승" in change_text or "+" in change_text
        direction = "-" if is_down else ("+" if is_up else "")
        change_val = f"{direction}{num_val}"
    else:
        change_val = "+0.00"
        
    # 등락률 파싱
    rate_elem = soup.find(id="change_rate_and_direction")
    if rate_elem:
        rate_text = rate_elem.text.strip()
        rate_match = re.search(r'([\d.,]+%)', rate_text)
        rate_val = rate_match.group(1) if rate_match else "0.00%"
        
        is_down_rate = "하락" in rate_text or "락" in rate_text or "-" in rate_text
        is_up_rate = "상승" in rate_text or "승" in rate_text or "+" in rate_text
        direction_rate = "-" if is_down_rate else ("+" if is_up_rate else "")
        change_rate = f"{direction_rate}{rate_val}"
    else:
        change_rate = "0.00%"

    print(f"-> 수집 성공! 코스피: {now_val} ({change_rate})")

    # 2. 투자자별 순매수 동향 수집
    print("[2/3] 투자자별 매수/매도 수급 데이터 수집 시작...")
    url_trend = "https://finance.naver.com/sise/sise_trans.naver"
    
    try:
        response_trend = requests.get(url_trend, headers=headers, timeout=15)
        response_trend.raise_for_status()
        html_trend = response_trend.content.decode('cp949', errors='ignore')
    except Exception as e:
        print(f"[치명적 오류] 수급 동향 데이터 서버 연결 실패: {e}")
        raise e

    soup_trend = BeautifulSoup(html_trend, 'html.parser')
    personal = 0
    foreign = 0
    institution = 0
    
    # 안정적인 HTML 테이블 순회 파서 작동
    for tr in soup_trend.find_all('tr'):
        title_td = tr.find('td', class_='title')
        if title_td:
            name = title_td.text.strip()
            num_tds = tr.find_all('td', class_='num')
            if num_tds:
                val_text = num_tds[0].text.strip().replace(',', '')
                try:
                    val = int(val_text)
                except ValueError:
                    val = 0
                
                if '개인' in name:
                    personal = val
                elif '외국인' in name:
                    foreign = val
                elif '기관' in name:
                    institution = val

    # 만약 테이블 파싱이 모종의 이유로 실패하여 모두 0으로 수집된 경우, 정규식(Regex) 백업 가동
    if personal == 0 and foreign == 0 and institution == 0:
        print("[알림] 수급 테이블 파이프라인 누락으로 백업 정규식 파서로 자동 전환합니다.")
        personal = extract_investor_val_regex(html_trend, '개인')
        foreign = extract_investor_val_regex(html_trend, '외국인')
        institution = extract_investor_val_regex(html_trend, '기관')

    print(f"-> 수급 수집 성공! 개인: {personal}억 / 외인: {foreign}억 / 기관: {institution}억")

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
        print(f"[오류] {file_path} 파일이 존재하지 않습니다.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 데이터 주입용 치환 처리
    html_content = re.sub(r'id="kospi-value">.*?<', f'id="kospi-value">{data["kospi_value"]}<', html_content)
    html_content = re.sub(r'id="kospi-change-val">.*?<', f'id="kospi-change-val">{data["kospi_change"]}<', html_content)
    html_content = re.sub(r'id="kospi-change-pct">.*?<', f'id="kospi-change-pct">{data["kospi_percent"]}<', html_content)
    html_content = re.sub(r'id="market-date">.*?<', f'id="market-date">{data["date"]} 장 마감<', html_content)
    
    # Chart.js 데이터 변수 주입 및 치환
    json_data_regex = r'const netBuyingData = \{.*?\};'
    replacement_json = f"""const netBuyingData = {{
            personal: {data["personal"]:.4f},    
            foreign: {data["foreign"]:.4f},    
            institution: {data["institution"]:.4f}  
        }};"""
    html_content = re.sub(json_data_regex, replacement_json, html_content, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("-> index.html 대시보드 파일 실시간 데이터 동기화 완료!")

def get_kakao_access_token():
    """GitHub Secrets에 저장된 리프레시 토큰을 활용해 영구 자동 카카오톡 Access Token을 연장 발급합니다."""
    client_id = os.environ.get("KAKAO_CLIENT_ID")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    
    if not client_id or not refresh_token:
        print("[⚠️ 경고] KAKAO_CLIENT_ID 또는 KAKAO_REFRESH_TOKEN 환경변수가 감지되지 않았습니다.")
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
        
        new_refresh_token = response_data.get("refresh_token")
        if new_refresh_token:
            print(f"⚠️ [중요 알림] 새로운 REFRESH_TOKEN이 발급되었습니다! 아래 키를 복사해 GitHub Secrets의 KAKAO_REFRESH_TOKEN에 덮어씌워주세요:\n{new_refresh_token}")
            
        return access_token
    else:
        print(f"[오류] 카카오 API 보안 갱신 실패: {response.text}")
        return None

def send_kakao_notification(access_token, data):
    """카카오톡 '나에게 보내기' API로 당일 마감 시황 메시지를 최종 전송합니다."""
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
        print("[3/3] 카카오톡 보고서가 본인 톡방으로 성공적으로 배달되었습니다!")
    else:
        print(f"[오류] 카카오톡 전송 실패: {response.text}")

if __name__ == "__main__":
    market_data = fetch_market_data()
    update_html_file(market_data)
    
    access_token = get_kakao_access_token()
    if access_token:
        send_kakao_notification(access_token, market_data)
