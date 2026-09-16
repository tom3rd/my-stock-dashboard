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

# .env 로드
load_dotenv()

# SSL 보안 우회
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['PYTHONHTTPSVERIFY'] = '0'

st.set_page_config(page_title="AX Stock Intelligence (실전 API)", layout="wide")

# --- CSS 최적화 (Streamlit 기본 헤더/메뉴 숨김 및 미세 여백 조절) ---
st.markdown("""
    <style>
        /* Streamlit 기본 상단 헤더 바 완전히 숨김 (Deploy 버튼 영역) */
        header[data-testid="stHeader"] { visibility: hidden; height: 0px; }
        
        /* 메인 컨테이너 상단 여백 최적화 (1.2rem) */
        .block-container { 
            padding-top: 1.2rem !important; 
            padding-bottom: 0rem !important; 
            padding-left: 1rem !important; 
            padding-right: 1rem !important; 
        }
        
        /* 제목 폰트 및 간격 설정 */
        h3 { font-size: 1.2rem !important; margin-bottom: 0.1rem !important; padding-top: 0px !important; }
        
        /* 사이드바 여백 및 폰트 콤팩트화 (스크롤 완전 방지) */
        [data-testid="stSidebar"] { font-size: 0.8rem !important; }
        [data-testid="stSidebar"] .block-container { padding-top: 1rem !important; }
        [data-testid="stSidebar"] h2 { font-size: 0.9rem !important; font-weight: bold; margin-bottom: 0.1rem !important; margin-top: 0.3rem !important; }
        [data-testid="stSidebar"] .stButton button { padding: 1px 5px !important; font-size: 0.72rem !important; min-height: 0px !important; }
        [data-testid="stSidebar"] input { font-size: 0.78rem !important; padding: 2px 6px !important; }
        [data-testid="stSidebar"] hr { margin: 0.4rem 0 !important; }
        
        /* metric 메인 디자인 */
        div[data-testid="stMetricValue"] { font-size: 0.85rem !important; font-weight: bold; }
        div[data-testid="stMetricLabel"] { font-size: 0.7rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- 로컬 파일 영구 저장 시스템 ---
DATA_FILE = "portfolio.json"

def load_portfolio():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "interest_stocks": {
            "삼성전자": "005930", "SK하이닉스": "000660", "한화엔진": "082740",
            "삼양식품": "003230", "에코프로": "086520", "현대차": "005380", "고영": "053670"
        },
        "display_stocks": ["삼성전자", "SK하이닉스", "한화엔진", "삼양식품", "에코프로", "현대차"]
    }

def save_portfolio():
    data = {
        "interest_stocks": st.session_state.interest_stocks,
        "display_stocks": st.session_state.display_stocks
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if "interest_stocks" not in st.session_state or "display_stocks" not in st.session_state:
    saved_data = load_portfolio()
    st.session_state.interest_stocks = saved_data.get("interest_stocks", {})
    st.session_state.display_stocks = saved_data.get("display_stocks", [])

# --- KRX 전종목 내장 검색 엔진 ---
@st.cache_data
def load_full_krx_db():
    url = "https://raw.githubusercontent.com/corazzon/finance-data-analysis/main/krx.csv"
    try:
        df = pd.read_csv(url)
        db = {}
        for _, row in df.iterrows():
            name = str(row['Name']).strip()
            code = str(row['Symbol']).zfill(6)
            db[name] = code
        return db
    except Exception:
        return {
            "삼성전자": "005930", "삼성전기": "009150", "삼성SDI": "006400", "삼성바이오로직스": "207940",
            "SK하이닉스": "000660", "SK이노베이션": "096770", "SK텔레콤": "017670", "현대차": "005380",
            "기아": "000270", "현대모비스": "012330", "NAVER": "035420", "네이버": "035420",
            "카카오": "035720", "카카오뱅크": "377300", "카카오페이": "377300", "LG에너지솔루션": "373220",
            "LG화학": "051910", "LG전자": "066570", "한화엔진": "082740", "한화에어로스페이스": "012450",
            "한화솔루션": "009830", "삼양식품": "003230", "에코프로": "086520", "에코프로비엠": "247540",
            "고영": "053670", "셀트리온": "068270", "POSCO홀딩스": "005490", "포스코퓨처엠": "003670",
            "알테오젠": "196170", "HLB": "028300", "두산에너빌리티": "034020", "LIG넥스원": "079550",
            "한미반도체": "042700", "크래프톤": "259960", "엔씨소프트": "036570", "넷마블": "251270",
            "금호전기": "001210"
        }

krx_db = load_full_krx_db()

def search_stock_local(query_text):
    query = query_text.replace(" ", "").upper()
    results = []
    if len(query) == 6 and query.isdigit():
        for name, code in krx_db.items():
            if code == query:
                return [(name, code)]
        return [(f"종목_{query}", query)]
        
    for name, code in krx_db.items():
        if query in name.replace(" ", "").upper():
            results.append((name, code))
            if len(results) >= 8:
                break
    return results

kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.datetime.now(kst)
today_str = now_kst.strftime("%Y-%m-%d")

is_weekday = now_kst.weekday() < 5
start_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
end_time = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
is_market_open = is_weekday and (start_time <= now_kst <= end_time)

# --- 1. 상단 헤더 ---
status_badge = "🟢 **LIVE (실전 장 중)**" if is_market_open else "⚪ **장 마감 (대기 중)**"
st.subheader(f"📈 AX Stock Intelligence ({today_str}) | {status_badge}")
st.divider()

# --- 2. 환경 변수 ---
app_key = os.getenv("KIS_APP_KEY", "").strip()
app_secret = os.getenv("KIS_APP_SECRET", "").strip()
URL_BASE = "https://openapi.koreainvestment.com:9443"

# --- 3. KIS API 실전 통신 ---
@st.cache_data(ttl=86000)
def get_access_token_cached(key, secret):
    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json; charset=UTF-8"}
    body = {"grant_type": "client_credentials", "appkey": key, "appsecret": secret}
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10, verify=False)
        res_json = res.json()
        if "access_token" in res_json:
            return True, res_json["access_token"], "인증 성공"
        return False, None, res_json.get("msg1", str(res_json))
    except Exception as e:
        return False, None, str(e)

@st.cache_data(ttl=60)
def get_kis_stock_daily_real(code, key, secret, token):
    time.sleep(0.25)
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

is_auth_ok, token, auth_msg = get_access_token_cached(app_key, app_secret)

# --- 4. 사이드바 UI ---

# [최상단] 차트 분석 기법 선택
st.sidebar.header("📊 차트 분석 기법 선택")
strategy = st.sidebar.selectbox(
    "분석 기법",
    ["tom3rd (정밀 모멘텀)", "이동평균선 (MA Cross)", "RSI 과매도/과매수", "볼린저 밴드"],
    label_visibility="collapsed"
)

st.sidebar.divider()

# [1 영역] 종목 검색
st.sidebar.header("🔍 1. 종목 검색")
search_query = st.sidebar.text_input("종목명/코드 입력", key="search_input_val", placeholder="예: 삼성전기")

if search_query:
    results = search_stock_local(search_query.strip())
    if results:
        for r_name, r_code in results:
            col_s1, col_s2 = st.sidebar.columns([3, 1])
            col_s1.write(f"**{r_name}** ({r_code})")
            if col_s2.button("➕", key=f"add_search_{r_code}"):
                st.session_state.interest_stocks[r_name] = r_code
                save_portfolio()
                st.sidebar.success(f"[{r_name}] 추가!")
                st.rerun()
    else:
        st.sidebar.warning("결과 없음")

st.sidebar.divider()

# [2 영역] 관심종목 리스트
st.sidebar.header("⭐ 2. 관심 종목 리스트")
st.sidebar.caption(f"총 {len(st.session_state.interest_stocks)}개 등록됨")

for name, code in list(st.session_state.interest_stocks.items()):
    col1, col2, col3 = st.sidebar.columns([2.5, 1, 1])
    col1.write(f"• {name}")
    
    if name not in st.session_state.display_stocks:
        if col2.button("➕", key=f"to_disp_{code}", help="화면에 표시"):
            if len(st.session_state.display_stocks) < 6:
                st.session_state.display_stocks.append(name)
                save_portfolio()
                st.rerun()
            else:
                st.sidebar.error("최대 6개 가능")
    else:
        col2.write("✅")
        
    if col3.button("🗑️", key=f"del_int_{code}", help="삭제"):
        del st.session_state.interest_stocks[name]
        if name in st.session_state.display_stocks:
            st.session_state.display_stocks.remove(name)
        save_portfolio()
        st.rerun()

st.sidebar.divider()

# [3 영역] 화면 표시 종목 리스트
st.sidebar.header("🖥️ 3. 화면 표시 종목")
st.sidebar.caption(f"선택됨: ({len(st.session_state.display_stocks)} / 6개)")

for d_name in list(st.session_state.display_stocks):
    col_d1, col_d2 = st.sidebar.columns([3, 1])
    col_d1.write(f"📌 **{d_name}**")
    if col_d2.button("❌", key=f"remove_disp_{d_name}", help="화면 제외"):
        st.session_state.display_stocks.remove(d_name)
        save_portfolio()
        st.rerun()

# --- 5. 메인 대시보드 렌더링 ---
if not app_key or not app_secret:
    st.error("⚠️ `.env` 파일에 KIS_APP_KEY 및 KIS_APP_SECRET이 설정되지 않았습니다.")
elif not is_auth_ok:
    st.error(f"🔑 실전 API 인증 실패: {auth_msg}")
else:
    st.success("✅ 한국투자증권 실전 API 연동 완료")
    
    if not st.session_state.display_stocks:
        st.warning("👈 사이드바 [2단계 관심종목 리스트]에서 ➕ 버튼을 눌러 화면에 띄울 종목을 선택해 주세요.")
    else:
        num_stocks = len(st.session_state.display_stocks)
        cols_per_row = 3 if num_stocks > 2 else num_stocks
        cols = st.columns(cols_per_row)
        chart_height = 210 if num_stocks > 3 else (300 if num_stocks > 2 else 420)

        for idx, stock_name in enumerate(st.session_state.display_stocks):
            code = st.session_state.interest_stocks[stock_name]
            is_data_ok, df, data_msg = get_kis_stock_daily_real(code, app_key, app_secret, token)
            
            col_target = cols[idx % cols_per_row]
            
            with col_target:
                if not is_data_ok or df is None or df.empty:
                    st.error(f"{stock_name} ({code}) 로드 실패: {data_msg}")
                    continue

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

                reason_msg = ""
                
                if strategy == "이동평균선 (MA Cross)":
                    buy_cond = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
                    sell_cond = (df['MA5'] < df['MA20']) & (df['MA5'].shift(1) >= df['MA20'].shift(1))
                    
                    latest_ma5 = df['MA5'].iloc[-1]
                    latest_ma20 = df['MA20'].iloc[-1]
                    if latest_ma5 > latest_ma20:
                        reason_msg = f"5일선({latest_ma5:,.0f})이 20일선({latest_ma20:,.0f}) 상단에 위치한 상승 흐름입니다."
                    else:
                        reason_msg = f"5일선({latest_ma5:,.0f})이 20일선({latest_ma20:,.0f}) 하단에 위치한 약세 흐름입니다."
                        
                elif strategy == "RSI 과매도/과매수":
                    buy_cond = df['RSI'] < 30
                    sell_cond = df['RSI'] > 70
                    latest_rsi = df['RSI'].iloc[-1]
                    if latest_rsi < 30:
                        reason_msg = f"RSI 수치가 {latest_rsi:.1f}로 30 이하 과매도 구간(반등 기대)입니다."
                    elif latest_rsi > 70:
                        reason_msg = f"RSI 수치가 {latest_rsi:.1f}로 70 이상 과매수 구간(조정 주의)입니다."
                    else:
                        reason_msg = f"RSI 수치가 {latest_rsi:.1f}로 중립 구간(30~70)을 유지하고 있습니다."
                        
                elif strategy == "볼린저 밴드":
                    buy_cond = df['Close'] <= df['Lower']
                    sell_cond = df['Close'] >= df['Upper']
                    latest_close = df['Close'].iloc[-1]
                    latest_upper = df['Upper'].iloc[-1]
                    latest_lower = df['Lower'].iloc[-1]
                    if latest_close <= latest_lower:
                        reason_msg = f"주가({latest_close:,.0f})가 볼린저 하단선({latest_lower:,.0f})을 이탈/터치했습니다."
                    elif latest_close >= latest_upper:
                        reason_msg = f"주가({latest_close:,.0f})가 볼린저 상단선({latest_upper:,.0f})을 터치했습니다."
                    else:
                        reason_msg = f"주가가 볼린저 밴드 이평선 범위 내에서 안정적인 흐름입니다."
                        
                else:  # tom3rd
                    buy_cond = (df['Close'] > df['MA50']) & (df['RSI'] < 45)
                    sell_cond = (df['Close'] < df['MA50']) & (df['RSI'] > 60)
                    latest_close = df['Close'].iloc[-1]
                    latest_ma50 = df['MA50'].iloc[-1]
                    latest_rsi = df['RSI'].iloc[-1]
                    
                    if buy_cond.iloc[-1]:
                        reason_msg = f"50일선({latest_ma50:,.0f}) 상단 유지 중 RSI({latest_rsi:.1f}) 눌림목이 완성되었습니다."
                    elif sell_cond.iloc[-1]:
                        reason_msg = f"50일선({latest_ma50:,.0f}) 이탈 및 RSI({latest_rsi:.1f}) 과열로 위험 관리 필요 구간입니다."
                    else:
                        diff_pct = ((latest_close - latest_ma50) / latest_ma50) * 100
                        reason_msg = f"50일선 대비 {diff_pct:+.1f}%, RSI는 {latest_rsi:.1f}로 추세 관망 구간입니다."

                df.loc[buy_cond, 'Buy_Signal'] = df['Low'] * 0.98
                df.loc[sell_cond, 'Sell_Signal'] = df['High'] * 1.02

                latest = df.iloc[-1]
                st.markdown(f"**{stock_name}** ({code})")
                
                m1, m2, m3 = st.columns([1.2, 1, 1.2])
                m1.metric("현재가", f"{int(latest['Close']):,}원")
                m2.metric("RSI", f"{latest['RSI']:.1f}" if pd.notna(latest['RSI']) else "-")
                
                status_label = ""
                if pd.notna(latest['Buy_Signal']):
                    status_label = "🟢 매수"
                    m3.markdown("<span style='color:green; font-weight:bold;'>🟢 매수</span>", unsafe_allow_html=True)
                elif pd.notna(latest['Sell_Signal']):
                    status_label = "🔴 손절/축소"
                    m3.markdown("<span style='color:red; font-weight:bold;'>🔴 손절/축소</span>", unsafe_allow_html=True)
                else:
                    status_label = "⚪ 관망"
                    m3.markdown("<span style='color:gray;'>⚪ 관망</span>", unsafe_allow_html=True)

                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="주가"), row=1, col=1)
                
                if strategy == "이동평균선 (MA Cross)":
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='orange', width=1), name='5일선'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='blue', width=1), name='20일선'), row=1, col=1)
                elif strategy == "볼린저 밴드":
                    fig.add_trace(go.Scatter(x=df.index, y=df['Upper'], line=dict(color='gray', dash='dash'), name='상단'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['Lower'], line=dict(color='gray', dash='dash'), name='하단'), row=1, col=1)
                else:
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='#00A8FF', width=1), name='50일선'), row=1, col=1)

                fig.add_trace(go.Scatter(x=df.index, y=df['Buy_Signal'], mode='markers', marker=dict(symbol='triangle-up', size=7, color='green'), name='매수'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Sell_Signal'], mode='markers', marker=dict(symbol='triangle-down', size=7, color='red'), name='손절'), row=1, col=1)
                fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name="거래량", marker_color='lightblue'), row=2, col=1)

                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    height=chart_height,
                    margin=dict(l=5, r=5, t=5, b=5),
                    template="plotly_white",
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True)
                
                if "매수" in status_label:
                    st.success(f"💡 **판단 근거**: {reason_msg}")
                elif "손절" in status_label:
                    st.warning(f"💡 **판단 근거**: {reason_msg}")
                else:
                    st.info(f"💡 **판단 근거**: {reason_msg}")