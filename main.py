# -*- coding: utf-8 -*-
"""
전국 학령인구 지도 (시군구별 13~15세 중학교 학령인구 비율 단계구분도)
- 인구 데이터: 읍·면·동 단위 연도별 인구 (2015~2026)
- 경계 데이터: 전국 시군구 255개 GeoJSON
- '코드' 앞 5자리로 시군구를 구분하여 두 데이터를 연결한다.

※ 참고: 5단계 구간 경계값은 '13~15세 인구 비율'의 실제 분포를 5등분(20/40/60/80
  백분위수)해서 계산한 값이다. (65세 이상 고령화율용 경계값과는 지표 자체가
  다르므로 그대로 쓸 수 없어 새로 계산했다.)
"""

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# 0. 기본 설정
# ----------------------------------------------------------------------------
st.set_page_config(page_title="전국 중학교 학령인구 지도", layout="wide")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

# 중학교 학령인구(13~15세)에 해당하는 나이 범위
MIDDLE_SCHOOL_AGES = range(13, 16)  # 13세, 14세, 15세

# 5단계 구간 경계값
# (전국 시군구의 '13~15세 인구 비율'을 실제로 5등분한 값. 아래 build_ratio 함수에서
#  매번 새로 계산해서 쓰기 때문에, 연도가 바뀌어도 항상 실제 분포에 맞는 경계값이 된다.)
BIN_COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"]  # 옅은색 -> 진한색


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


# ----------------------------------------------------------------------------
# 2. 시군구 단위로 13~15세(중학교) 학령인구 비율 계산
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="시군구별 중학교 학령인구 비율을 계산하는 중입니다...")
def build_sigungu_ratio(df: pd.DataFrame, age_cols: list, target_year: int):
    """읍·면·동 인구를 시군구 단위로 합쳐서 13~15세 인구 비율(%)을 구한다."""

    # 13~15세(중학교)에 해당하는 나이별 열만 골라낸다. 예: '계_13세','계_14세','계_15세'
    middle_cols = [f"계_{age}세" for age in MIDDLE_SCHOOL_AGES]

    year_df = df[df["연도"] == target_year].copy()

    # 전체 인구, 13~15세 인구를 읍·면·동 단위로 먼저 계산한다.
    year_df["전체인구"] = year_df[age_cols].sum(axis=1)
    year_df["중학교인구"] = year_df[middle_cols].sum(axis=1)

    # '코드' 앞 5자리 = 시군구 코드
    year_df["시군구코드"] = year_df["코드"].str[:5]

    # 시군구 단위로 인구를 합산한다. (시도/시군구 이름은 대표값 하나만 사용)
    grouped = (
        year_df.groupby("시군구코드")
        .agg(
            시도=("시도", "first"),
            시군구=("시군구", "first"),
            전체인구=("전체인구", "sum"),
            중학교인구=("중학교인구", "sum"),
        )
        .reset_index()
    )

    grouped["학령인구비율"] = (
        grouped["중학교인구"] / grouped["전체인구"] * 100
    ).round(2)

    return grouped


def make_bins(ratio_series: pd.Series):
    """비율 값의 실제 분포를 5등분(20/40/60/80 백분위수)한 경계값과 구간 라벨을 만든다."""
    q20, q40, q60, q80 = np.percentile(ratio_series.dropna(), [20, 40, 60, 80])
    edges = [-0.01, round(q20, 2), round(q40, 2), round(q60, 2), round(q80, 2), 100]
    labels = [
        f"{edges[1]}% 미만",
        f"{edges[1]}% ~ {edges[2]}%",
        f"{edges[2]}% ~ {edges[3]}%",
        f"{edges[3]}% ~ {edges[4]}%",
        f"{edges[4]}% 이상",
    ]
    return edges, labels


# ----------------------------------------------------------------------------
# 3. 실제 데이터 로딩 & 계산 실행
# ----------------------------------------------------------------------------
pop_df, age_cols = load_population()
geojson = load_geojson()

latest_year = int(pop_df["연도"].max())
ratio_df = build_sigungu_ratio(pop_df, age_cols, latest_year)

# 실제 분포를 기준으로 5단계 구간 경계값과 라벨을 만든다.
bin_edges, bin_labels = make_bins(ratio_df["학령인구비율"])
color_map = dict(zip(bin_labels, BIN_COLORS))

ratio_df["구간"] = pd.cut(
    ratio_df["학령인구비율"], bins=bin_edges, labels=bin_labels
)

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
st.title("🏫 전국 중학교 학령인구 지도")
st.markdown(
    f"**{latest_year}년** 기준, 시군구별 **13~15세(중학교) 학령인구 비율**(전체 인구 대비 %) 단계구분도입니다."
)

# 색상 매핑에 '데이터 없음'을 회색으로 추가
color_map_full = dict(color_map)
color_map_full["데이터 없음"] = "#e0e0e0"
category_order = bin_labels + ["데이터 없음"]

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
        "학령인구비율": ":.2f",
        "시군구코드": False,
        "구간": False,
    },
    labels={
        "구간": "학령인구 비율 구간",
        "학령인구비율": "중학교 학령인구 비율(%)",
        "시도": "시도",
    },
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
    legend_title_text="학령인구 비율 구간",
)

st.plotly_chart(fig, use_container_width=True)

st.caption("지도에 마우스를 올리면 시군구 이름·시도·중학교 학령인구 비율(%)을 확인할 수 있습니다.")

# ----------------------------------------------------------------------------
# 5. 학령인구 비율 상위 10 / 하위 10 표
# ----------------------------------------------------------------------------
st.subheader("중학교 학령인구 비율 상위 10 / 하위 10")

# 실제 값이 있는 지역만 순위에 사용 (데이터 없음 제외)
valid_df = ratio_df.dropna(subset=["학령인구비율"])

top10 = (
    valid_df.sort_values("학령인구비율", ascending=False)
    .head(10)[["시도", "시군구", "학령인구비율"]]
    .reset_index(drop=True)
)
top10.index = top10.index + 1

bottom10 = (
    valid_df.sort_values("학령인구비율", ascending=True)
    .head(10)[["시도", "시군구", "학령인구비율"]]
    .reset_index(drop=True)
)
bottom10.index = bottom10.index + 1

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**🔺 중학교 학령인구 비율 높은 지역 Top 10**")
    st.dataframe(
        top10.style.format({"학령인구비율": "{:.2f}%"}),
        use_container_width=True,
    )

with col_right:
    st.markdown("**🔻 중학교 학령인구 비율 낮은 지역 Top 10**")
    st.dataframe(
        bottom10.style.format({"학령인구비율": "{:.2f}%"}),
        use_container_width=True,
    )
