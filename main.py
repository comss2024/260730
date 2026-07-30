# -*- coding: utf-8 -*-
"""
전국 고령화 지도 (시군구별 65세 이상 인구 비율 단계구분도)
- 인구 데이터: 읍·면·동 단위 연도별 인구 (2015~2026)
- 경계 데이터: 전국 시군구 255개 GeoJSON
- '코드' 앞 5자리로 시군구를 구분하여 두 데이터를 연결한다.
"""

import re

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# 0. 기본 설정
# ----------------------------------------------------------------------------
st.set_page_config(page_title="전국 고령화 지도", layout="wide")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

# 5단계 구간 경계값 (전국 시군구를 다섯 덩어리로 나눈 실제 값)
BIN_EDGES = [-0.01, 19, 23, 28, 38, 100]
BIN_LABELS = ["19% 미만", "19% ~ 23%", "23% ~ 28%", "28% ~ 38%", "38% 이상"]

# 옅은 색 -> 진한 색 순서 (파란 계열 5단계)
BIN_COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"]
COLOR_MAP = dict(zip(BIN_LABELS, BIN_COLORS))


# ----------------------------------------------------------------------------
# 1. 데이터 불러오기 (캐시 사용: 앱이 다시 실행돼도 매번 새로 내려받지 않음)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population():
    """인구 CSV를 읽어서 '계_' (남녀 합계) 나이별 열만 남긴다."""
    # 먼저 전체 열 이름만 확인한다 (0행만 읽어서 빠르게 처리)
    all_cols = pd.read_csv(POP_URL, compression="gzip", nrows=0).columns.tolist()

    # 필요한 열만 골라서 읽는다: 기본 정보 열 + '계_'로 시작하는 나이별 열
    base_cols = ["연도", "시도", "시군구", "코드"]
    age_cols = [c for c in all_cols if c.startswith("계_")]
    use_cols = base_cols + age_cols

    # '코드'는 계산용 숫자가 아니라 이름표이므로 반드시 문자열로 읽는다.
    df = pd.read_csv(
        POP_URL,
        compression="gzip",
        usecols=use_cols,
        dtype={"코드": str},
    )
    return df, age_cols


@st.cache_data(show_spinner="지도 경계 데이터를 불러오는 중입니다...")
def load_geojson():
    """시군구 경계 GeoJSON을 내려받는다."""
    res = requests.get(GEO_URL)
    res.raise_for_status()
    return res.json()


def parse_age(col_name: str) -> int:
    """'계_0세', '계_65세', '계_100세 이상' 같은 열 이름에서 나이를 숫자로 뽑아낸다."""
    match = re.search(r"(\d+)", col_name)
    return int(match.group(1)) if match else 0


# ----------------------------------------------------------------------------
# 2. 시군구 단위로 65세 이상 인구 비율 계산
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="시군구별 고령화율을 계산하는 중입니다...")
def build_sigungu_ratio(df: pd.DataFrame, age_cols: list, target_year: int):
    """읍·면·동 인구를 시군구 단위로 합쳐서 65세 이상 인구 비율(%)을 구한다."""

    # 65세 이상에 해당하는 나이별 열만 골라낸다.
    elderly_cols = [c for c in age_cols if parse_age(c) >= 65]

    year_df = df[df["연도"] == target_year].copy()

    # 전체 인구, 65세 이상 인구를 읍·면·동 단위로 먼저 계산한다.
    year_df["전체인구"] = year_df[age_cols].sum(axis=1)
    year_df["고령인구"] = year_df[elderly_cols].sum(axis=1)

    # '코드' 앞 5자리 = 시군구 코드
    year_df["시군구코드"] = year_df["코드"].str[:5]

    # 시군구 단위로 인구를 합산한다. (시도/시군구 이름은 대표값 하나만 사용)
    grouped = (
        year_df.groupby("시군구코드")
        .agg(
            시도=("시도", "first"),
            시군구=("시군구", "first"),
            전체인구=("전체인구", "sum"),
            고령인구=("고령인구", "sum"),
        )
        .reset_index()
    )

    grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"] * 100).round(2)

    # 5단계 구간으로 나누어 범례용 문자열 열을 만든다.
    grouped["구간"] = pd.cut(
        grouped["고령화율"], bins=BIN_EDGES, labels=BIN_LABELS
    )

    return grouped


# ----------------------------------------------------------------------------
# 3. 실제 데이터 로딩 & 계산 실행
# ----------------------------------------------------------------------------
pop_df, age_cols = load_population()
geojson = load_geojson()

latest_year = int(pop_df["연도"].max())
ratio_df = build_sigungu_ratio(pop_df, age_cols, latest_year)

# GeoJSON에 있는 시군구 코드 목록(255개)을 기준으로 왼쪽 조인한다.
# -> 경계는 있는데 인구 데이터가 없는 지역도 지도에는 빠짐없이 표시하기 위함.
geo_codes = pd.DataFrame(
    [
        {
            "시군구코드": f["properties"]["코드"],
            "시군구_geo": f["properties"]["시군구"],
            "시도_geo": f["properties"]["시도"],
        }
        for f in geojson["features"]
    ]
)
map_df = geo_codes.merge(ratio_df, on="시군구코드", how="left")

# 이름은 GeoJSON 쪽 이름으로 통일한다 (지도와 데이터가 100% 같은 이름을 쓰도록).
map_df["시군구"] = map_df["시군구_geo"]
map_df["시도"] = map_df["시도_geo"]
map_df["구간"] = map_df["구간"].astype(object).where(map_df["구간"].notna(), "데이터 없음")


# ----------------------------------------------------------------------------
# 4. 화면 구성
# ----------------------------------------------------------------------------
st.title("🇰🇷 전국 고령화 지도")
st.markdown(f"**{latest_year}년** 기준, 시군구별 **65세 이상 인구 비율(고령화율)** 단계구분도입니다.")

# 색상 매핑에 '데이터 없음'을 회색으로 추가
color_map_full = dict(COLOR_MAP)
color_map_full["데이터 없음"] = "#e0e0e0"
category_order = BIN_LABELS + ["데이터 없음"]

fig = px.choropleth(
    map_df,
    geojson=geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="구간",
    color_discrete_map=color_map_full,
    category_orders={"구간": category_order},
    hover_name="시군구",
    hover_data={
        "시도": True,
        "고령화율": ":.2f",
        "시군구코드": False,
        "구간": False,
    },
    labels={"구간": "고령화율 구간", "고령화율": "고령화율(%)", "시도": "시도"},
)

# 배경 지도 타일 없이 경계선만 보이도록 설정
fig.update_geos(
    fitbounds="locations",
    visible=False,          # 기본 지도(바다, 육지 색 등)를 숨김
    showcountries=False,
    showcoastlines=False,
    showland=False,
)
fig.update_traces(marker_line_color="white", marker_line_width=0.6)
fig.update_layout(
    height=750,
    margin=dict(l=0, r=0, t=10, b=0),
    legend_title_text="고령화율 구간",
)

st.plotly_chart(fig, use_container_width=True)

st.caption("지도에 마우스를 올리면 시군구 이름·시도·고령화율을 확인할 수 있습니다.")

# ----------------------------------------------------------------------------
# 5. 고령화율 상위 10 / 하위 10 표
# ----------------------------------------------------------------------------
st.subheader("고령화율 상위 10 / 하위 10")

# 실제 값이 있는 지역만 순위에 사용 (데이터 없음 제외)
valid_df = ratio_df.dropna(subset=["고령화율"])

top10 = (
    valid_df.sort_values("고령화율", ascending=False)
    .head(10)[["시도", "시군구", "고령화율"]]
    .reset_index(drop=True)
)
top10.index = top10.index + 1

bottom10 = (
    valid_df.sort_values("고령화율", ascending=True)
    .head(10)[["시도", "시군구", "고령화율"]]
    .reset_index(drop=True)
)
bottom10.index = bottom10.index + 1

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**🔺 고령화율 높은 지역 Top 10**")
    st.dataframe(
        top10.style.format({"고령화율": "{:.2f}%"}),
        use_container_width=True,
    )

with col_right:
    st.markdown("**🔻 고령화율 낮은 지역 Top 10**")
    st.dataframe(
        bottom10.style.format({"고령화율": "{:.2f}%"}),
        use_container_width=True,
    )
