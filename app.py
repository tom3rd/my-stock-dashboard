import os
import ssl
import time
import requests
import json
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

st.set_page_config(page_title="AX Stock Mobile", layout="wide")

# 모바일 UI 여백 및 패딩 최적화
st.markdown("""
    <style>
        .block-container { padding-top: 1.0rem !important; padding-bottom: 2.0rem; padding-left: 0.5rem; padding-right: 0.5rem; }
        h3 { font-size: 1.1rem !important; margin-bottom: 0.2rem !important; }
        div[data-testid="stMetricValue"] { font-size: 0.95rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
        .stButton button { padding: 4px 10px !important; font-size: 0.85rem !important; width: 100%; }
        .stock-card { background-color: #f8f9fa; border-radius: 8px; padding: 10px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.datetime.now(kst)
today_str = now_kst.strftime("%Y-%m-%d")

is_weekday = now_kst.weekday() < 5
start_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
end_time = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
is_market_open = is_weekday and (start_time <= now_kst <= end_time)

# --- 1. 모바일 헤더 ---
status_badge = "🟢 **LIVE**" if is_market_open else "⚪ **장 마감**"
st.markdown(f"### 📈 AX Stock ({today_str}) | {status_badge}")
st.divider()

# --- 2. API 연결 ---
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

# --- 3. 세션 관리 ---
if "interest_stocks" not in st.session_state:
    st.session_state.interest_stocks = {
        "삼성전자": "005930", "SK하이닉스": "000660", "한화엔진": "082740",
        "삼양식품": "003230", "에코프로": "086520", "현대차": "005380"
    }

if "display_stocks" not in st.session_state:
    st.session_state.display_stocks = ["삼성전자", "SK하이닉스", "한화엔진", "삼양식품", "에코프로", "현대차"]

is_auth_ok, token, auth_msg = get_access_token_cached(app_key, app_secret)

# --- 4. 사이드바 (설정 메뉴) ---
st.sidebar.header("🔍 종목 검색 & 관리")
search_query = st.sidebar.text_input("종목명 또는 코드 입력")

if search_query:
    fallback_db = {
        "고영": "053670", "카카오": "035720", "네이버": "035420", "NAVER": "035420",
        "삼성전자": "005930", "SK하이닉스": "000660", "한화엔진": "082740", "삼양식품": "003230",
        "에코프로": "086520", "현대차": "005380", "기아": "000270", "알테오젠": "196170"
    }
    matches = [(k, v) for k, v in fallback_db.items() if search_query.upper() in k.upper()]
    for r_name, r_code in matches:
        col_s1, col_s2 = st.sidebar.columns([3, 1])
        col_s1.write(f"{r_name} ({r_code})")
        if col_s2.button("➕", key=f"add_{r_code}"):
            st.session_state.interest_stocks[r_name] = r_code
            if r_name not in st.session_state.display_stocks and len(st.session_state.display_stocks) < 6:
                st.session_state.display_stocks.append(r_name)
            st.rerun()

st.sidebar.divider()
strategy = st.sidebar.selectbox("📊 차트 분석 기법", ["tom3rd (정밀 모멘텀)", "이동평균선 (MA Cross)", "RSI 과매도/과매수", "볼린저 밴드"])

# --- 5. 메인 대시보드 (모바일 1열 세로 스크롤) ---
if not app_key or not app_secret:
    st.error("⚠️ KIS_APP_KEY 설정 필요")
elif not is_auth_ok:
    st.error(f"🔑 실전 API 인증 실패: {auth_msg}")
else:
    if not st.session_state.display_stocks:
        st.info("👈 왼쪽 상단 > 메뉴를 눌러 화면에 표시할 종목을 추가해 주세요.")
    else:
        # 모바일용 1열 루프
        for stock_name in list(st.session_state.display_stocks):
            code = st.session_state.interest_stocks[stock_name]
            is_data_ok, df, data_msg = get_kis_stock_daily_real(code, app_key, app_secret, token)
            
            # 종목 타이틀 및 모바일 제거 버튼
            col_t1, col_t2 = st.columns([4, 1])
            col_t1.markdown(f"#### 📌 {stock_name} (`{code}`)")
            if col_t2.button("❌", key=f"mob_del_{code}"):
                st.session_state.display_stocks.remove(stock_name)
                st.rerun()

            if not is_data_ok or df is None or df.empty:
                st.error(f"데이터 로드 실패: {data_msg}")
                continue

            # 지표 계산
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
            
            # 모바일 3칸 핵심 수치 카드
            m1, m2, m3 = st.columns(3)
            m1.metric("현재가", f"{int(latest['Close']):,}원")
            m2.metric("RSI", f"{latest['RSI']:.1f}" if pd.notna(latest['RSI']) else "-")
            
            if pd.notna(latest['Buy_Signal']):
                m3.markdown("🟢 **매수**")
            elif pd.notna(latest['Sell_Signal']):
                m3.markdown("🔴 **손절/축소**")
            else:
                m3.markdown("⚪ **관망**")

            # 모바일 가로폭 감안한 차트 (높이 280px)
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="주가"), row=1, col=1)
            
            if strategy == "이동평균선 (MA Cross)":
                fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='orange', width=1), name='5일'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='blue', width=1), name='20일'), row=1, col=1)
            elif strategy == "볼린저 밴드":
                fig.add_trace(go.Scatter(x=df.index, y=df['Upper'], line=dict(color='gray', dash='dash'), name='상단'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Lower'], line=dict(color='gray', dash='dash'), name='하단'), row=1, col=1)
            else:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='#00A8FF', width=1), name='50일'), row=1, col=1)

            fig.add_trace(go.Scatter(x=df.index, y=df['Buy_Signal'], mode='markers', marker=dict(symbol='triangle-up', size=8, color='green'), name='매수'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Sell_Signal'], mode='markers', marker=dict(symbol='triangle-down', size=8, color='red'), name='손절'), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name="거래량", marker_color='lightblue'), row=2, col=1)

            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=280,
                margin=dict(l=2, r=2, t=5, b=2),
                template="plotly_white",
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
            st.divider()