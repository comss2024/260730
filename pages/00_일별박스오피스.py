# 필요한 라이브러리들을 불러옵니다.
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# 앱의 제목과 안내 문구를 설정합니다.
st.set_page_config(page_title="한 달간의 박스오피스 추이", page_icon="🍿", layout="wide")
st.title("🍿 한 달간의 영화별 박스오피스 추이")
st.markdown("한국 시간 기준 '어제'부터 **과거 30일간**의 매출액과 관객수 증감을 꺾은선 그래프로 확인합니다.")

# 1. 한국 시간(KST) 기준으로 '어제' 날짜 계산하기
# 배포 서버의 시간이 한국과 다를 수 있으므로 강제로 한국 시간대를 적용합니다.
kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
yesterday = now_kst - timedelta(days=1)

# 2. 스트림릿 비밀 금고(secrets)에서 API 키 불러오기
try:
    API_KEY = st.secrets["KOBIS_KEY"]
except KeyError:
    # 키가 없을 경우 빈 화면 대신 에러 메시지를 띄우고 앱을 멈춥니다.
    st.error("⚠️ 스트림릿 비밀 금고(secrets)에 'KOBIS_KEY'가 설정되지 않았습니다. 앱 설정(Settings) -> Secrets에 인증키를 등록해 주세요.")
    st.stop()

# 3. 한 달 치 데이터 수집 함수 (로딩 속도를 위해 캐싱 적용)
# @st.cache_data를 쓰면 한 번 불러온 데이터는 기억해두어 앱이 새로고침될 때마다 30번씩 다시 요청하지 않습니다.
@st.cache_data(show_spinner="한 달 치 박스오피스 데이터를 불러오는 중입니다. 잠시만 기다려주세요... ⏳")
def fetch_month_boxoffice(api_key, end_date, days=30):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    all_data = []
    
    # 30일 전부터 어제까지 차례대로 반복하며 데이터를 가져옵니다.
    for i in range(days - 1, -1, -1):
        target_date = end_date - timedelta(days=i)
        target_dt_str = target_date.strftime('%Y%m%d')
        display_date_str = target_date.strftime('%Y-%m-%d')
        
        params = {
            "key": api_key,
            "targetDt": target_dt_str
        }
        
        response = requests.get(url, params=params)
        
        # 4-1. 네트워크 오류 처리
        if response.status_code != 200:
            return None, "⚠️ API 요청에 실패했습니다. 네트워크 상태나 영화진흥위원회 서버 상태를 확인해 주세요."
            
        data = response.json()
        
        # 4-2. API 인증키 오류 처리 (faultInfo 상자가 온 경우)
        if "faultInfo" in data:
            return None, "⚠️ API 인증키가 잘못되었거나 유효하지 않습니다. 발급받은 KOBIS_KEY가 정확한지 확인해 주세요."
            
        daily_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
        
        # 가져온 하루치 데이터에 '날짜' 정보를 추가하여 전체 목록에 합칩니다.
        for item in daily_list:
            item['date'] = display_date_str
            all_data.append(item)
            
    # 4-3. 데이터가 아예 없는 경우 처리
    if not all_data:
        return None, "⚠️ 조회된 데이터가 없습니다. 어제 날짜 기준으로 아직 집계가 끝나지 않았거나 API 제공 지연일 수 있으니 나중에 다시 시도해 주세요."
        
    # 수집한 데이터를 판다스 데이터프레임으로 변환하여 반환합니다.
    return pd.DataFrame(all_data), None

# 함수를 실행하여 데이터와 에러 메시지를 받습니다.
df, error_msg = fetch_month_boxoffice(API_KEY, yesterday)

# 에러 메시지가 있다면 화면에 띄우고 앱을 멈춥니다.
if error_msg:
    st.error(error_msg)
    st.stop()

# 5. 데이터 가공하기 (문자열을 숫자로 변환)
# API에서 온 값들은 모두 '문자열'이므로, 그래프를 그리려면 숫자로 바꿔주어야 합니다.
df['salesAmt'] = pd.to_numeric(df['salesAmt'])  # 일일 매출액
df['audiCnt'] = pd.to_numeric(df['audiCnt'])    # 일일 관객수
df['scrnCnt'] = pd.to_numeric(df['scrnCnt'])    # 스크린수
df['showCnt'] = pd.to_numeric(df['showCnt'])    # 상영횟수

st.write(f"📅 **조회 기간:** {(yesterday - timedelta(days=29)).strftime('%Y년 %m월 %d일')} ~ {yesterday.strftime('%Y년 %m월 %d일')}")
st.markdown("---")

# 6. 사용자 인터페이스 (영화 선택기)
# 데이터에 있는 모든 영화의 이름을 중복 없이 가져옵니다.
unique_movies = df['movieNm'].unique()

# 한 달 동안 꾸준히 상위권에 있었던 영화를 기본으로 선택해 둡니다. (누적 관객수 기준 1등 영화 등)
# 여기서는 어제(마지막 날짜) 기준 1위 영화를 기본값으로 넣습니다.
default_movie = [df.iloc[-1]['movieNm']] if len(df) > 0 else []

st.subheader("🔍 분석할 영화 선택")
# 사용자가 직접 여러 영화를 골라서 비교할 수 있는 멀티셀렉트 박스입니다.
selected_movies = st.multiselect(
    "그래프에 표시할 영화를 선택하세요 (여러 개 선택 가능):", 
    options=unique_movies, 
    default=default_movie
)

if not selected_movies:
    st.info("👆 위에서 분석하고 싶은 영화를 하나 이상 선택해 주세요.")
    st.stop()

# 사용자가 선택한 영화만 남기도록 데이터를 필터링합니다.
filtered_df = df[df['movieNm'].isin(selected_movies)]

# 7. 꺾은선 그래프 그리기
# 스트림릿의 st.line_chart를 사용하기 위해 데이터를 [날짜, 영화명1, 영화명2...] 형태로 바꿉니다(pivot_table).

# 7-1. 매출액 증감 그래프
st.subheader("💰 영화별 매출액 추이 (단위: 원)")
sales_chart_data = pd.pivot_table(
    filtered_df, 
    values='salesAmt', 
    index='date', 
    columns='movieNm', 
    aggfunc='sum'
).fillna(0) # 값이 없는 날짜는 0으로 채웁니다.
st.line_chart(sales_chart_data)

# 7-2. 관객수 증감 그래프
st.subheader("👥 영화별 관객수 추이 (단위: 명)")
audi_chart_data = pd.pivot_table(
    filtered_df, 
    values='audiCnt', 
    index='date', 
    columns='movieNm', 
    aggfunc='sum'
).fillna(0)
st.line_chart(audi_chart_data)

st.markdown("---")

# 8. 부가 정보: 스크린수 및 상영횟수 추이 (선택 사항)
col1, col2 = st.columns(2)

with col1:
    st.subheader("📽️ 스크린수 추이 (단위: 개)")
    scrn_chart_data = pd.pivot_table(filtered_df, values='scrnCnt', index='date', columns='movieNm', aggfunc='sum').fillna(0)
    st.line_chart(scrn_chart_data)

with col2:
    st.subheader("🎬 상영횟수 추이 (단위: 회)")
    show_chart_data = pd.pivot_table(filtered_df, values='showCnt', index='date', columns='movieNm', aggfunc='sum').fillna(0)
    st.line_chart(show_chart_data)
