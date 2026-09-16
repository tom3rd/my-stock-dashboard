import os
import ssl
import time
import requests
import json
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import pytz
import urllib3
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# SSL 보안 우회
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['PYTHONHTTPSVERIFY'] = '0'

st.set_page_config(page_title="AX Stock App", layout="wide", initial_sidebar_state="collapsed")

# 토스증권 스타일 모바일 CSS
st.markdown("""
    <style>
        .block-container { padding-top: 0.8rem !important; padding-bottom: 2.0rem; padding-left: 0.8rem; padding-right: 0.8rem; }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; overflow-x: auto; white-space: nowrap; }
        .stTabs [data-baseweb="tab"] {
            padding: 6px 14px !important;
            border-radius: 16px !important;
            background-color: #F2F4F6 !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
        }
        .stTabs [aria-selected="true"] {
            background-color: #3182F6 !important;
            color: white !important;
        }
        .price-large { font-size: 2.2rem; font-weight: 800; margin-bottom: 2px; line-height: 1.1; }
        .diff-red { color: #F04452; font-weight: 700; font-size: 1.05rem; }
        .diff-blue { color: #3182F6; font-weight: 700; font-size: 1.05rem; }
        .signal-badge-buy { background-color: #FFF0F1; color: #F04452; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.85rem; }
        .signal-badge-sell { background-color: #E8F3FF; color: #3182F6; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.85rem; }
        .signal-badge-hold { background-color: #F2F4F6; color: #8B95A1; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.85rem; }
    </style>
""", unsafe_allow_html=True)

kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.datetime.now(kst)
today_str = now_kst.strftime("%Y-%m-%d")

# --- 텔레그램 전송 ---
def send_telegram_msg(message):
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

# --- API 연동 ---
app_key = os.getenv("KIS_APP_KEY", "").strip()
app_secret = os.getenv("KIS_APP_SECRET", "").strip()
URL_BASE = "https://openapi.koreainvestment.com:9443"

@st.cache_data(ttl=86000)
def get_access_token_cached(key, secret):
    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json; charset=UTF-8"}
    body = {"grant_type": "client_credentials", "appkey": key, "appsecret": secret}
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10, verify=False)
        res_json = res.json()
        if "access_token" in res_json:
            return True, res_json["access_token"], "성공"
        return False, None, res_json.get("msg1", str(res_json))
    except Exception as e:
        return False, None, str(e)

@st.cache_data(ttl=60)
def get_kis_stock_daily_real(code, key, secret, token):
    time.sleep(0.15)
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": key,
        "appsecret": secret,
        "tr_id": "FHKST03010100",
        "custtype": "P"
    }
    today = datetime.datetime.today().strftime("%Y%m%d")
    start_date = (datetime.datetime.today() - datetime.timedelta(days=180)).strftime("%Y%m%d")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": today,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10, verify=False)
        res_json = res.json()
        if "output2" in res_json and len(res_json["output2"]) > 0:
            df = pd.DataFrame(res_json["output2"])
            df = df[['stck_bsop_date', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_clpr', 'acml_vol']]
            df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                df[col] = pd.to_numeric(df[col])
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            df.set_index('Date', inplace=True)
            return True, df, "성공"
        return False, None, res_json.get("msg1", "데이터 없음")
    except Exception as e:
        return False, None, str(e)

# --- 세션 초기화 ---
if "interest_stocks" not in st.session_state:
    st.session_state.interest_stocks = {
        "삼성전자": "005930", "SK하이닉스": "000660", "한화엔진": "082740",
        "삼양식품": "003230", "에코프로": "086520", "현대차": "005380"
    }

if "display_stocks" not in st.session_state:
    st.session_state.display_stocks = ["삼성전자", "SK하이닉스", "한화엔진", "삼양식품", "에코프로", "현대차"]

if "alert_sent" not in st.session_state:
    st.session_state.alert_sent = {}

# 종목 추가 전용 공통 함수
def add_target_stock(name, code):
    name = name.strip()
    code = code.strip()
    if name and code:
        st.session_state.interest_stocks[name] = code
        if name not in st.session_state.display_stocks:
            st.session_state.display_stocks.append(name)
            st.toast(f"✅ '{name}' 종목 탭이 추가되었습니다!", icon="🎉")
        else:
            st.toast(f"ℹ️ '{name}' 종목은 이미 탭에 존재합니다.", icon="💡")

is_auth_ok, token, auth_msg = get_access_token_cached(app_key, app_secret)

# --- 사이드바 ---
st.sidebar.header("🔍 종목 추가 및 관리")
search_query = st.sidebar.text_input("종목명 또는 6자리 코드 입력")

if search_query:
    fallback_db = {
        "고영": "053670", "카카오": "035720", "네이버": "035420", "NAVER": "035420",
        "삼성전자": "005930", "SK하이닉스": "000660", "한화엔진": "082740", "삼양식품": "003230",
        "에코프로": "086520", "현대차": "005380", "기아": "000270", "알테오젠": "196170",
        "카카오뱅크": "323410", "크래프톤": "259960", "셀트리온": "068270", "POSCO홀딩스": "005490"
    }
    matches = [(k, v) for k, v in fallback_db.items() if search_query.upper() in k.upper() or search_query in v]
    
    if matches:
        for r_name, r_code in matches:
            col_s1, col_s2 = st.sidebar.columns([3, 1])
            col_s1.write(f"{r_name} ({r_code})")
            if col_s2.button("➕", key=f"side_add_{r_code}"):
                add_target_stock(r_name, r_code)
                st.rerun()
    else:
        # DB에 없어도 코드(6자리) 직접 등록 허용
        if len(search_query) == 6 and search_query.isdigit():
            if st.sidebar.button(f"➕ 코드 '{search_query}' 직접 추가", key="add_custom_code"):
                add_target_stock(f"종목_{search_query}", search_query)
                st.rerun()
        else:
            st.sidebar.info("검색 결과가 없습니다. 6자리 코드를 입력하면 직접 추가가 가능합니다.")

st.sidebar.divider()
strategy = st.sidebar.selectbox("📊 차트 분석 기법", ["tom3rd (정밀 모멘텀)", "이동평균선 (MA Cross)", "RSI 과매도/과매수", "볼린저 밴드"])

if st.sidebar.button("🔔 텔레그램 연동 테스트"):
    send_telegram_msg("🚨 [AX Stock] 텔레그램 테스트 메시지입니다.")
    st.sidebar.success("발송 완료!")

# --- 메인 화면 ---
if not app_key or not app_secret or not is_auth_ok:
    st.error("🔑 한투 API 연동 상태를 확인해 주세요.")
else:
    if not st.session_state.display_stocks:
        st.info("👈 사이드바 메뉴에서 관심 종목을 추가해 주세요.")
    else:
        # 상단 종목 이동 탭
        tabs = st.tabs(st.session_state.display_stocks)

        for i, stock_name in enumerate(st.session_state.display_stocks):
            with tabs[i]:
                code = st.session_state.interest_stocks[stock_name]
                is_data_ok, df, data_msg = get_kis_stock_daily_real(code, app_key, app_secret, token)

                if not is_data_ok or df is None or df.empty:
                    st.error(f"데이터 로드 실패: {data_msg}")
                    continue

                # 지표 및 신호 계산
                df['Buy_Signal'] = np.nan
                df['Sell_Signal'] = np.nan
                df['MA5'] = df['Close'].rolling(window=5).mean()
                df['MA20'] = df['Close'].rolling(window=20).mean()
                df['MA50'] = df['Close'].rolling(window=50).mean()

                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['RSI'] = 100 - (100 / (1 + rs))

                df['STD20'] = df['Close'].rolling(window=20).std()
                df['Upper'] = df['MA20'] + (df['STD20'] * 2)
                df['Lower'] = df['MA20'] - (df['STD20'] * 2)

                if strategy == "이동평균선 (MA Cross)":
                    buy_cond = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
                    sell_cond = (df['MA5'] < df['MA20']) & (df['MA5'].shift(1) >= df['MA20'].shift(1))
                elif strategy == "RSI 과매도/과매수":
                    buy_cond = df['RSI'] < 30
                    sell_cond = df['RSI'] > 70
                elif strategy == "볼린저 밴드":
                    buy_cond = df['Close'] <= df['Lower']
                    sell_cond = df['Close'] >= df['Upper']
                else:  # tom3rd
                    buy_cond = (df['Close'] > df['MA50']) & (df['RSI'] < 45)
                    sell_cond = (df['Close'] < df['MA50']) & (df['RSI'] > 60)

                df.loc[buy_cond, 'Buy_Signal'] = df['Low'] * 0.98
                df.loc[sell_cond, 'Sell_Signal'] = df['High'] * 1.02

                latest = df.iloc[-1]
                prev = df.iloc[-2]
                diff_price = latest['Close'] - prev['Close']
                diff_rate = (diff_price / prev['Close']) * 100
                latest_date = latest.name.strftime("%Y-%m-%d")

                # 텔레그램 알림 체크
                alert_key = f"{code}_{latest_date}_{strategy}"
                if alert_key not in st.session_state.alert_sent:
                    if pd.notna(latest['Buy_Signal']):
                        send_telegram_msg(f"🟢 *[매수 신호]* {stock_name} ({int(latest['Close']):,}원)")
                        st.session_state.alert_sent[alert_key] = "BUY"
                    elif pd.notna(latest['Sell_Signal']):
                        send_telegram_msg(f"🔴 *[손절 신호]* {stock_name} ({int(latest['Close']):,}원)")
                        st.session_state.alert_sent[alert_key] = "SELL"

                # --- 토스 스타일 타이틀 & 현재가 헤더 ---
                c_title, c_del = st.columns([5, 1])
                c_title.markdown(f"**{stock_name}** `{code}`")
                if c_del.button("삭제", key=f"toss_del_{code}"):
                    st.session_state.display_stocks.remove(stock_name)
                    st.rerun()

                st.markdown(f"<div class='price-large'>{int(latest['Close']):,}원</div>", unsafe_allow_html=True)

                if diff_price >= 0:
                    st.markdown(f"<div class='diff-red'>어제보다 +{int(diff_price):,}원 (+{diff_rate:.2f}%)</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='diff-blue'>어제보다 {int(diff_price):,}원 ({diff_rate:.2f}%)</div>", unsafe_allow_html=True)

                st.write("")
                
                if pd.notna(latest['Buy_Signal']):
                    st.markdown("<span class='signal-badge-buy'>🟢 AI 매수 타점 포착</span>", unsafe_allow_html=True)
                elif pd.notna(latest['Sell_Signal']):
                    st.markdown("<span class='signal-badge-sell'>🔴 AI 손절/축소 타점 포착</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span class='signal-badge-hold'>⚪ AI 관망 유지 구간</span>", unsafe_allow_html=True)

                st.write("")

                # --- 라인 차트 ---
                max_price = df['High'].max()
                min_price = df['Low'].min()

                fig = go.Figure()

                line_color = '#F04452' if diff_price >= 0 else '#3182F6'
                fig.add_trace(go.Scatter(
                    x=df.index, y=df['Close'],
                    mode='lines',
                    line=dict(color=line_color, width=2.5),
                    name="종가"
                ))

                fig.add_trace(go.Scatter(
                    x=df.index, y=df['Buy_Signal'], mode='markers',
                    marker=dict(symbol='circle', size=10, color='#F04452'), name='매수'
                ))
                fig.add_trace(go.Scatter(
                    x=df.index, y=df['Sell_Signal'], mode='markers',
                    marker=dict(symbol='circle', size=10, color='#3182F6'), name='매도'
                ))

                fig.add_annotation(
                    x=df['High'].idxmax(), y=max_price,
                    text=f"최고 {int(max_price):,}원", showarrow=True, arrowhead=1, arrowcolor="#F04452", font=dict(color="#F04452", size=10)
                )
                fig.add_annotation(
                    x=df['Low'].idxmin(), y=min_price,
                    text=f"최저 {int(min_price):,}원", showarrow=True, arrowhead=1, arrowcolor="#3182F6", font=dict(color="#3182F6", size=10), ay=25
                )

                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    height=340,
                    margin=dict(l=5, r=5, t=10, b=5),
                    template="plotly_white",
                    showlegend=False,
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=True, gridcolor='#F2F4F6')
                )

                st.plotly_chart(fig, use_container_width=True)