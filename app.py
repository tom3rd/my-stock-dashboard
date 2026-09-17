import os
import ssl
import json
import time
import requests
import datetime
import threading
import pytz
import urllib3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

# SSL 경고 및 검사 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['PYTHONHTTPSVERIFY'] = '0'

st.set_page_config(page_title="AX Stock Intelligence", layout="wide")

# CSS 레이아웃 커스텀
st.markdown("""
    <style>
        .block-container { padding-top: 2.2rem !important; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem; }
        h3 { font-size: 1.3rem !important; margin-bottom: 0.3rem !important; }
        div[data-testid="stMetricValue"] { font-size: 0.9rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    </style>
""", unsafe_allow_html=True)

# 환경 변수 로드
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "").strip()
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
KIS_CANO = os.getenv("KIS_CANO", "").strip()
KIS_ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01").strip()

URL_BASE = "https://openapi.koreainvestment.com:9443"

# --- 1. KIS API 토큰 캐싱 및 통신 ---
@st.cache_data(ttl=86000)
def get_access_token():
    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json; charset=UTF-8"}
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET
    }
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10, verify=False)
        res_json = res.json()
        return res_json.get("access_token", None)
    except Exception:
        return None

def execute_kis_buy_order(code, qty=1):
    token = get_access_token()
    if not token:
        return False, "인증 토큰 발급 실패"

    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": "TTTC0802U",
        "custtype": "P"
    }
    body = {
        "CANO": KIS_CANO,
        "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
        "PDNO": code,
        "ORD_DVSN": "01",
        "ORD_QTY": str(qty),
        "ORD_PRC": "0"
    }
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10, verify=False)
        res_json = res.json()
        if res_json.get("rt_cd") == "0":
            return True, f"주문 성공 (주문번호: {res_json.get('output', {}).get('ODNO', 'N/A')})"
        else:
            return False, f"주문 실패: [{res_json.get('msg_cd')}] {res_json.get('msg1')}"
    except Exception as e:
        return False, f"통신 에러: {str(e)}"

# --- 2. 텔레그램 인라인 버튼 발송 ---
def send_telegram_inline_buy_signal(stock_name, code, price):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    text = (
        f"🚨 **[tom3rd 매수 타점 포착]**\n\n"
        f"• **종목명**: {stock_name} ({code})\n"
        f"• **포착가**: {price:,}원\n\n"
        f"아래 버튼을 누르면 1주 시장가 매수 주문이 즉시 실행됩니다."
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ YES (1주 매수)", "callback_data": f"BUY_{code}_{stock_name}"},
                {"text": "❌ NO (취소)", "callback_data": f"CANCEL_{stock_name}"}
            ]
        ]
    }
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup)
    }
    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except Exception:
        return False

# --- 3. 텔레그램 백그라운드 스레드 ---
def telegram_listener_thread():
    offset = 0
    while True:
        if not TELEGRAM_TOKEN:
            time.sleep(10)
            continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=12).json()
            
            for result in res.get("result", []):
                offset = result["update_id"] + 1
                
                if "callback_query" in result:
                    callback = result["callback_query"]
                    callback_id = callback["id"]
                    chat_id = callback["message"]["chat"]["id"]
                    data = callback.get("data", "")
                    
                    if data.startswith("BUY_"):
                        _, code, name = data.split("_")
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": callback_id, "text": "🚀 매수 주문 발주 중..."})
                        
                        success, msg = execute_kis_buy_order(code, qty=1)
                        result_msg = (
                            f"🟢 **[{name}] 1주 매수 완료**\n결과: {msg}" if success 
                            else f"🔴 **[{name}] 매수 주문 실패**\n사유: {msg}"
                        )
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                      json={"chat_id": chat_id, "text": result_msg, "parse_mode": "Markdown"})
                        
                    elif data.startswith("CANCEL_"):
                        name = data.split("_")[1]
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": callback_id, "text": "매수 주문 취소됨"})
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                      json={"chat_id": chat_id, "text": f"⚪ [{name}] 매수 주문이 취소되었습니다."})
        except Exception:
            time.sleep(3)
        time.sleep(1)

if "telegram_thread_started" not in st.session_state:
    st.session_state.telegram_thread_started = True
    t = threading.Thread(target=telegram_listener_thread, daemon=True)
    t.start()

# --- 4. Streamlit UI 대시보드 ---
kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.datetime.now(kst)
today_str = now_kst.strftime("%Y-%m-%d")

is_weekday = now_kst.weekday() < 5
start_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
end_time = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
is_market_open = is_weekday and (start_time <= now_kst <= end_time)

status_badge = "🟢 **LIVE (실전 장 중)**" if is_market_open else "⚪ **장 마감 (대기 중)**"
st.subheader(f"📈 AX Stock Intelligence ({today_str}) | {status_badge}")
st.divider()

# 한투 초당 호출 제한 방지 적용 (time.sleep)
@st.cache_data(ttl=60)
def get_kis_stock_daily_real(code):
    time.sleep(0.5)  # API 제한 우회용 0.5초 대기
    token = get_access_token()
    if not token:
        return False, None, "인증 토큰 발급 실패"
    
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
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
        else:
            return False, None, res_json.get("msg1", "데이터 없음")
    except Exception as e:
        return False, None, str(e)

if "my_watchlist" not in st.session_state:
    st.session_state.my_watchlist = {
        "삼성전자": "005930",
        "SK하이닉스": "000660",
        "한화엔진": "082740",
        "삼양식품": "003230",
        "에코프로": "086520",
        "현대차": "005380"
    }

selected_stocks = st.sidebar.multiselect(
    "화면 표시 종목",
    options=list(st.session_state.my_watchlist.keys()),
    default=list(st.session_state.my_watchlist.keys())[:6]
)

strategy = st.sidebar.selectbox(
    "차트 분석 기법",
    ["tom3rd (정밀 모멘텀)", "이동평균선 (MA Cross)", "RSI 과매도/과매수", "볼린저 밴드"]
)

if st.sidebar.button("🔔 텔레그램 YES/NO 알림 테스트"):
    success = send_telegram_inline_buy_signal("삼성전자", "005930", 73500)
    if success:
        st.sidebar.success("텔레그램 메시지 발송 완료!")
    else:
        st.sidebar.error("텔레그램 발송 실패")

if selected_stocks:
    num_stocks = len(selected_stocks)
    cols_per_row = 3 if num_stocks > 2 else num_stocks
    cols = st.columns(cols_per_row)

    for idx, stock_name in enumerate(selected_stocks):
        code = st.session_state.my_watchlist[stock_name]
        is_ok, df, msg = get_kis_stock_daily_real(code)
        col_target = cols[idx % cols_per_row]
        
        with col_target:
            if not is_ok or df is None:
                st.error(f"{stock_name} 데이터 로드 실패: {msg}")
                continue

            df['MA50'] = df['Close'].rolling(window=50).mean()
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            buy_cond = (df['Close'] > df['MA50']) & (df['RSI'] < 45)
            df['Buy_Signal'] = np.nan
            df.loc[buy_cond, 'Buy_Signal'] = df['Low'] * 0.98

            latest = df.iloc[-1]
            st.markdown(f"**{stock_name}** ({code})")
            
            m1, m2, m3 = st.columns([1.2, 1, 1.2])
            m1.metric("현재가", f"{int(latest['Close']):,}원")
            m2.metric("RSI", f"{latest['RSI']:.1f}" if pd.notna(latest['RSI']) else "-")
            
            if pd.notna(latest['Buy_Signal']):
                m3.markdown("<span style='color:green; font-weight:bold;'>🟢 매수</span>", unsafe_allow_html=True)
            else:
                m3.markdown("<span style='color:gray;'>⚪ 관망</span>", unsafe_allow_html=True)

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color='lightblue'), row=2, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False, height=250, margin=dict(l=5, r=5, t=5, b=5), template="plotly_white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)