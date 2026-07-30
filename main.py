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
import plotly.graph_objects as go
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


@st.cache_data(show_spinner="연도별 학령인구 변동 데이터를 계산하는 중입니다...")
def build_time_series(df: pd.DataFrame, age_cols: list):
    """모든 연도에 대해 시군구별 13~15세 인구(명)와 비율(%)을 한 번에 계산한다.
    (최근 10년 변동 추이 그래프에 사용)"""

    middle_cols = [f"계_{age}세" for age in MIDDLE_SCHOOL_AGES]

    work_df = df.copy()
    work_df["전체인구"] = work_df[age_cols].sum(axis=1)
    work_df["중학교인구"] = work_df[middle_cols].sum(axis=1)
    work_df["시군구코드"] = work_df["코드"].str[:5]

    # '연도'와 '시군구코드' 두 기준으로 묶어서 연도별 시계열 데이터를 만든다.
    ts = (
        work_df.groupby(["연도", "시군구코드"])
        .agg(
            시도=("시도", "first"),
            시군구=("시군구", "first"),
            전체인구=("전체인구", "sum"),
            중학교인구=("중학교인구", "sum"),
        )
        .reset_index()
    )
    ts["학령인구비율"] = (ts["중학교인구"] / ts["전체인구"] * 100).round(2)
    return ts


@st.cache_data(show_spinner="초등학생 수를 바탕으로 향후 5년 중학교 학령인구를 예측하는 중입니다...")
def build_forecast(df: pd.DataFrame, base_year: int, horizon: int = 5):
    """'초등학생이 그대로 나이만 먹고 진급한다'는 단순 가정으로 향후 N년의
    13~15세(중학교) 인구를 예측한다.

    예) 올해 12세인 학생은 1년 뒤 13세가 되어 중학교 학령인구에 포함된다.
        올해 8세인 학생은 5년 뒤 13세가 되어 중학교 학령인구에 포함된다.
    전출입·사망 등은 고려하지 않는 아주 단순한(naive) 예측이라는 점에 유의해야 한다.
    """

    # 예측에 필요한 나이는 8~14세이다.
    # (5년 뒤 13세가 될 사람은 지금 8세, 1년 뒤 15세가 될 사람은 지금 14세)
    needed_ages = sorted({target - d for target in (13, 14, 15) for d in range(1, horizon + 1)})
    needed_cols = [f"계_{age}세" for age in needed_ages]

    base_df = df[df["연도"] == base_year].copy()
    base_df["시군구코드"] = base_df["코드"].str[:5]

    # 시군구 단위로 나이별 인구를 합산해 둔다.
    agg_dict = {"시도": ("시도", "first"), "시군구": ("시군구", "first")}
    agg_dict.update({col: (col, "sum") for col in needed_cols})
    grouped = base_df.groupby("시군구코드").agg(**agg_dict).reset_index()

    # 연도(d년 후)별로 '13세+14세+15세가 될 사람 수'를 계산해서 쌓는다.
    forecast_rows = []
    for d in range(1, horizon + 1):
        forecast_year = base_year + d
        # 3개 연령(13,14,15세)을 만들 나이별 인구를 더한다.
        중학교인구_예측 = sum(grouped[f"계_{target - d}세"] for target in (13, 14, 15))
        forecast_rows.append(
            pd.DataFrame(
                {
                    "연도": forecast_year,
                    "시군구코드": grouped["시군구코드"],
                    "시도": grouped["시도"],
                    "시군구": grouped["시군구"],
                    "중학교인구": 중학교인구_예측,
                }
            )
        )

    return pd.concat(forecast_rows, ignore_index=True)


# ----------------------------------------------------------------------------
# 3. 실제 데이터 로딩 & 연도 선택
# ----------------------------------------------------------------------------
pop_df, age_cols = load_population()
geojson = load_geojson()

# 데이터에 있는 모든 연도를 최신순으로 나열한다.
available_years = sorted(pop_df["연도"].unique(), reverse=True)
latest_year = available_years[0]

# 사이드바에 연도 선택 상자를 둔다. 기본값은 가장 최신 연도.
st.sidebar.header("🔎 조회 조건")
selected_year = st.sidebar.selectbox(
    "조회할 연도를 선택하세요",
    options=available_years,
    index=0,  # available_years[0] = 최신 연도
)

# 선택한 연도를 기준으로 시군구별 학령인구 비율을 계산한다.
ratio_df = build_sigungu_ratio(pop_df, age_cols, selected_year)

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
    f"**{selected_year}년** 기준, 시군구별 **13~15세(중학교) 학령인구 비율**(전체 인구 대비 %) 단계구분도입니다."
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

st.caption(
    "지도에 마우스를 올리면 시군구 이름·시도·중학교 학령인구 비율(%)을 확인할 수 있습니다.  \n"
    f"※ 5단계 구간 경계값은 {selected_year}년 실제 분포를 5등분한 값이라, 연도를 바꾸면 경계값도 함께 바뀝니다. "
    f"(현재 경계값: {bin_edges[1]}% · {bin_edges[2]}% · {bin_edges[3]}% · {bin_edges[4]}%)"
)

# ----------------------------------------------------------------------------
# 5. 학령인구 비율 상위 10 / 하위 10 표
# ----------------------------------------------------------------------------
st.subheader(f"{selected_year}년 중학교 학령인구 비율 상위 10 / 하위 10")

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


# ----------------------------------------------------------------------------
# 6. 최근 10년 학령인구 감소율 상위 지역의 변동 추이 (꺾은선 그래프)
# ----------------------------------------------------------------------------
st.subheader("최근 10년 학령인구 감소율 TOP 지역 변동 추이")

# 모든 연도의 시군구별 중학교 학령인구(명)를 한 번에 계산한다.
ts_df = build_time_series(pop_df, age_cols)

# '최근 10년' = 데이터에 있는 연도 중 가장 최근 10개 (연도가 10개보다 적으면 있는 만큼 전부 사용)
recent_years = sorted(pop_df["연도"].unique())[-10:]
start_year, end_year = recent_years[0], recent_years[-1]

ts_recent = ts_df[ts_df["연도"].isin(recent_years)].copy()

# 감소율(%) = (시작 연도 인구 - 끝 연도 인구) / 시작 연도 인구 x 100
# 값이 클수록 그동안 학령인구가 많이 줄어든 지역이라는 뜻이다.
start_pop = ts_recent[ts_recent["연도"] == start_year][["시군구코드", "중학교인구"]].rename(
    columns={"중학교인구": "시작인구"}
)
end_pop = ts_recent[ts_recent["연도"] == end_year][
    ["시군구코드", "시도", "시군구", "중학교인구"]
].rename(columns={"중학교인구": "끝인구"})

# 두 연도 모두에 데이터가 있는 지역만 비교한다 (예: 세종시처럼 중간에 생긴 지역은 제외).
decline_df = end_pop.merge(start_pop, on="시군구코드", how="inner")
decline_df = decline_df[decline_df["시작인구"] > 0]  # 0으로 나누기 방지
decline_df["감소율"] = (
    (decline_df["시작인구"] - decline_df["끝인구"]) / decline_df["시작인구"] * 100
).round(2)

# 감소율이 큰 순서로 정렬해서 상위 5개 지역을 뽑는다.
top_decline = decline_df.sort_values("감소율", ascending=False).head(5)

# ----------------------------------------------------------------------------
# 6-1. 향후 5년 예측: 초등학생(7~12세) 수를 바탕으로 미래 중학교 학령인구 추정
# ----------------------------------------------------------------------------
FORECAST_HORIZON = 5
forecast_df = build_forecast(pop_df, base_year=end_year, horizon=FORECAST_HORIZON)

# 예측 마지막 연도(끝인구 대비)의 감소율도 함께 계산해서 선택 상자 라벨에 보여준다.
forecast_last = forecast_df[forecast_df["연도"] == end_year + FORECAST_HORIZON][
    ["시군구코드", "중학교인구"]
].rename(columns={"중학교인구": "예측인구"})
decline_df = decline_df.merge(forecast_last, on="시군구코드", how="left")
decline_df["예측감소율"] = np.where(
    decline_df["끝인구"] > 0,
    ((decline_df["끝인구"] - decline_df["예측인구"]) / decline_df["끝인구"] * 100).round(2),
    np.nan,
)

st.markdown(
    f"**{start_year}년 → {end_year}년**(실선, 실제 자료) 동안 중학교 학령인구(13~15세, 명)가 "
    "가장 많이 줄어든(감소율이 큰) 지역들의 변동 추이이며, "
    f"**{end_year}년 → {end_year + FORECAST_HORIZON}년**(점선, 예측)은 "
    "현재 초등학생(7~12세) 수가 그대로 나이만 먹고 진급한다고 가정한 단순 예측입니다. "
    "전출입·사망 등은 반영하지 않은 참고용 수치입니다."
)

# 사용자가 비교하고 싶은 지역을 직접 골라볼 수 있도록 선택 상자를 제공한다.
# 기본값은 (실제) 감소율 상위 5개 지역으로 미리 채워둔다.
all_region_options = decline_df.sort_values("감소율", ascending=False)
option_codes = all_region_options["시군구코드"].tolist()
option_labels = {
    row["시군구코드"]: (
        f"{row['시도']} {row['시군구']} "
        f"(최근10년 -{row['감소율']}% / 향후5년 예측 -{row['예측감소율']}%)"
    )
    for _, row in all_region_options.iterrows()
}

selected_codes = st.multiselect(
    "그래프에 표시할 지역 선택 (기본값: 최근 10년 감소율 상위 5개 지역)",
    options=option_codes,
    default=top_decline["시군구코드"].tolist(),
    format_func=lambda code: option_labels.get(code, code),
)

if selected_codes:
    # 지역마다 서로 다른 색을 지정해서, 실선(실측)과 점선(예측)이 같은 색으로 짝이 맞도록 한다.
    palette = px.colors.qualitative.Plotly
    color_of = {code: palette[i % len(palette)] for i, code in enumerate(selected_codes)}

    trend_fig = go.Figure()

    for code in selected_codes:
        region_label = option_labels.get(code, code).split(" (")[0]  # '시도 시군구'만 사용
        color = color_of[code]

        # (1) 실선: 최근 10년 실제 데이터
        actual = ts_recent[ts_recent["시군구코드"] == code].sort_values("연도")
        trend_fig.add_trace(
            go.Scatter(
                x=actual["연도"],
                y=actual["중학교인구"],
                mode="lines+markers",
                name=region_label,
                legendgroup=code,
                line=dict(color=color, dash="solid"),
                hovertemplate=f"{region_label}<br>%{{x}}년(실측): %{{y:,}}명<extra></extra>",
            )
        )

        # (2) 점선: 향후 5년 예측 데이터 (실선의 마지막 점과 이어지도록 end_year 지점을 포함)
        future = forecast_df[forecast_df["시군구코드"] == code].sort_values("연도")
        connect_x = [end_year] + future["연도"].tolist()
        connect_y = [actual["중학교인구"].iloc[-1]] + future["중학교인구"].tolist()
        trend_fig.add_trace(
            go.Scatter(
                x=connect_x,
                y=connect_y,
                mode="lines+markers",
                name=region_label + " (예측)",
                legendgroup=code,
                showlegend=False,  # 범례는 실선 쪽에만 표시 (같은 색이라 구분 가능)
                line=dict(color=color, dash="dash"),
                marker=dict(symbol="circle-open"),
                hovertemplate=f"{region_label}<br>%{{x}}년(예측): %{{y:,}}명<extra></extra>",
            )
        )

    trend_fig.update_layout(
        height=470,
        margin=dict(l=0, r=0, t=10, b=0),
        legend_title_text="지역 (실선=실측, 점선=예측)",
        xaxis=dict(dtick=1, title="연도"),
        yaxis=dict(title="중학교 학령인구(명)"),
        hovermode="closest",
    )
    st.plotly_chart(trend_fig, use_container_width=True)
else:
    st.info("비교할 지역을 하나 이상 선택해 주세요.")
