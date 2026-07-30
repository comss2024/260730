# 필요한 라이브러리들을 불러옵니다.
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# 앱의 제목을 설정합니다.
st.title("🍿 일일 박스오피스 순위")

# 1. 한국 시간(KST) 기준으로 '어제' 날짜 계산하기
# 배포 서버의 시간이 한국과 다를 수 있으므로 강제로 한국 시간대를 적용합니다.
kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
# 현재 시간에서 하루(1일)를 빼서 어제 날짜를 구합니다.
yesterday = now_kst - timedelta(days=1)
# API가 요구하는 'YYYYMMDD' 형식의 문자열로 변환합니다.
targetDt = yesterday.strftime('%Y%m%d')

st.write(f"📅 **조회 일자:** {yesterday.strftime('%Y년 %m월 %d일')}")

# 2. 스트림릿 비밀 금고(secrets)에서 API 키 불러오기
try:
    API_KEY = st.secrets["KOBIS_KEY"]
except KeyError:
    # 키가 없을 경우 빈 화면 대신 에러 메시지를 띄우고 앱을 멈춥니다.
    st.error("⚠️ 스트림릿 비밀 금고(secrets)에 'KOBIS_KEY'가 설정되지 않았습니다. 앱 설정에서 인증키를 등록해 주세요.")
    st.stop()

# 3. 영화진흥위원회(KOBIS) API 요청 준비 및 실행
url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
params = {
    "key": API_KEY,
    "targetDt": targetDt
}

# API에 데이터를 요청합니다.
response = requests.get(url, params=params)

# 4. 오류 처리 (네트워크 오류, 인증키 오류, 데이터 없음)
# 4-1. 요청 자체가 실패한 경우 (상태 코드 200이 아님)
if response.status_code != 200:
    st.error("⚠️ API 요청에 실패했습니다. 네트워크 상태나 영화진흥위원회 서버 상태를 확인해 주세요.")
    st.stop()

data = response.json()

# 4-2. API 인증키가 틀려 오류 상자(faultInfo)가 돌아온 경우
if "faultInfo" in data:
    st.error("⚠️ API 인증키가 잘못되었거나 유효하지 않습니다. 발급받은 KOBIS_KEY가 정확한지 확인해 주세요.")
    st.stop()

# 박스오피스 목록 데이터를 안전하게 추출합니다.
boxoffice_result = data.get("boxOfficeResult", {})
movie_list = boxoffice_result.get("dailyBoxOfficeList", [])

# 4-3. 추출한 영화 목록이 비어있는 경우 (아직 집계가 안 된 경우 등)
if not movie_list:
    st.error(f"⚠️ {targetDt} 기준 박스오피스 데이터가 비어있거나 아직 집계되지 않았습니다. 나중에 다시 시도해 주세요.")
    st.stop()

# 5. 데이터를 판다스(Pandas) 데이터프레임으로 변환
df = pd.DataFrame(movie_list)

# 필요한 열의 데이터 타입을 숫자로 바꿔줍니다. (그래프와 지표 카드에 쓰기 위함)
df['audiCnt'] = pd.to_numeric(df['audiCnt'])       # 일일 관객수
df['audiAcc'] = pd.to_numeric(df['audiAcc'])       # 누적 관객수
df['scrnCnt'] = pd.to_numeric(df['scrnCnt'])       # 스크린수
df['audiInten'] = pd.to_numeric(df['audiInten'])   # 전일 대비 관객수 증감량

st.markdown("---")

# 6. 1위 영화 지표 카드 (크게 3장)
top1_movie = df.iloc[0] # 데이터프레임의 첫 번째 줄(1위 영화)을 가져옵니다.

st.subheader(f"🏆 1위 영화: {top1_movie['movieNm']}")

# 화면을 3개의 세로 단(column)으로 나눕니다.
col1, col2, col3 = st.columns(3)

# 첫 번째 단: 일일 관객수 (어제 대비 증감량 표시)
col1.metric(
    label="일일 관객수", 
    value=f"{top1_movie['audiCnt']:,}명", 
    delta=f"{top1_movie['audiInten']:,}명"
)
# 두 번째 단: 누적 관객수
col2.metric(
    label="누적 관객수", 
    value=f"{top1_movie['audiAcc']:,}명"
)
# 세 번째 단: 스크린수
col3.metric(
    label="상영 스크린수", 
    value=f"{top1_movie['scrnCnt']:,}개"
)

st.markdown("---")

# 7. 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5편")
# 상위 5개 데이터만 잘라내서 새로운 데이터프레임을 만듭니다.
top5_df = df.head(5)
# 그래프의 X축으로 사용할 '영화명'을 인덱스로 설정합니다.
chart_data = top5_df.set_index('movieNm')[['audiCnt']]
# 스트림릿의 기본 막대그래프를 그려줍니다.
st.bar_chart(chart_data)

st.markdown("---")

# 8. 전체 순위 데이터 표 (순위, 영화명, 개봉일, 관객수, 누적관객, 스크린수)
st.subheader("📋 전체 박스오피스 표")

# 표에 보여줄 열(column)만 선택해서 가져옵니다.
table_df = df[['rank', 'movieNm', 'openDt', 'audiCnt', 'audiAcc', 'scrnCnt']]
# 화면에 표시될 열의 이름을 보기 좋은 한국어로 바꿔줍니다.
table_df.columns = ['순위', '영화명', '개봉일', '관객수(명)', '누적관객(명)', '스크린수(개)']

# 숫자에 천 단위 쉼표가 찍히도록 스타일을 적용해서 표를 출력합니다.
st.dataframe(
    table_df.style.format({
        '관객수(명)': '{:,}',
        '누적관객(명)': '{:,}',
        '스크린수(개)': '{:,}'
    }), 
    use_container_width=True, # 화면 너비에 맞게 표를 꽉 채웁니다.
    hide_index=True           # 불필요한 기본 인덱스(0, 1, 2...)를 숨깁니다.
)
