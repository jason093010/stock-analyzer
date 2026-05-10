import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from google import genai
import time

# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="股市小白分析系統",
    page_icon="📈",
    layout="wide"
)

# ─────────────────────────────────────────────
# 名詞解釋資料庫
# ─────────────────────────────────────────────
GLOSSARY = {
    "多頭": "📈 多頭（Bull）\n\n白話說：市場看漲，大家都在買，股價往上走。\n\n就像一頭牛用角把東西往上頂，所以用牛來代表上漲。",
    "空頭": "📉 空頭（Bear）\n\n白話說：市場看跌，大家都在賣，股價往下走。\n\n就像一隻熊用爪子把東西往下拍，所以用熊來代表下跌。",
    "超買": "🔴 超買（Overbought）\n\n白話說：股價漲太快、太多了，很多人已經買進，短期可能會休息甚至回跌。\n\n就像一個人跑太快，需要停下來喘口氣。",
    "超賣": "🟢 超賣（Oversold）\n\n白話說：股價跌太快、太多了，可能跌過頭，短期有機會反彈回升。\n\n就像橡皮筋拉太緊，有可能彈回來。",
    "均線": "📊 均線（Moving Average）\n\n白話說：把過去幾天的收盤價加起來取平均，畫成一條線。\n\n• MA5 = 最近5天平均價\n• MA20 = 最近20天平均價（約一個月）\n• MA60 = 最近60天平均價（約一季）\n\n股價在均線上方 = 強勢；在下方 = 弱勢。",
    "均線糾結": "🔀 均線糾結\n\n白話說：MA5、MA20、MA60 三條線纏在一起，代表市場方向不明，多空雙方勢均力敵，正在等待一個明確方向。\n\n這時候最好觀望，等方向明朗再行動。",
    "RSI": "📏 RSI（相對強弱指標）\n\n白話說：衡量股票「最近是漲比較多還是跌比較多」的工具，數值介於 0~100。\n\n• RSI > 70：超買，漲太多了，小心回跌\n• RSI < 30：超賣，跌太多了，留意反彈\n• RSI 50 附近：多空平衡，方向不明",
    "MACD": "📡 MACD（指數平滑異同移動平均線）\n\n白話說：用來判斷股票「動能是在加速還是減速」的工具。\n\n• MACD 柱狀圖由負轉正 = 動能轉強，可能要漲\n• MACD 柱狀圖由正轉負 = 動能轉弱，可能要跌",
    "ATR": "📐 ATR（平均真實波幅）\n\n白話說：衡量這支股票「每天平均會波動多少」的工具。\n\n• ATR 高 = 每天起伏很大，風險較高\n• ATR 低 = 比較穩，每天波動小",
    "支撐": "🛡️ 支撐（Support）\n\n白話說：股價跌到某個價位就會停下來反彈。就像地板，股價跌到這裡就被「撐住」了。",
    "壓力": "🚧 壓力（Resistance）\n\n白話說：股價漲到某個價位就會遇到阻力下跌。就像天花板，股價漲到這裡就被「擋住」了。",
    "成交量": "📦 成交量（Volume）\n\n白話說：今天這支股票總共被買賣了幾張。\n\n• 量大 + 價漲 = 真的在漲\n• 量小 + 價漲 = 假漲，不可靠\n• 量大 + 價跌 = 有人在出貨，要小心",
    "52週高低": "📅 52週高低\n\n白話說：這支股票過去一整年的最高價和最低價。\n\n現價接近高點 = 相對貴；接近低點 = 相對便宜。",
}

# ─────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input(
        "🔑 Gemini API 金鑰",
        type="password",
        placeholder="AIza..."
    )
    st.caption("金鑰只存在你的瀏覽器，完全不會被儲存或上傳")

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("選擇股票市場", ["🇹🇼 台股", "🇺🇸 美股"])
    period = st.selectbox(
        "分析時間區間",
        ["3mo", "6mo", "1y", "2y"],
        index=1,
        format_func=lambda x: {
            "3mo": "3個月（短線參考）",
            "6mo": "6個月（中線參考）",
            "1y":  "1年（長線參考）",
            "2y":  "2年（趨勢參考）"
        }[x]
    )

    st.divider()
    st.header("📖 名詞解釋小百科")
    st.caption("點擊任一名詞查看白話解釋")
    for term in GLOSSARY:
        with st.expander(term):
            st.info(GLOSSARY[term])

# ─────────────────────────────────────────────
# 主標題
# ─────────────────────────────────────────────
st.title("📈 股市小白分析系統")
st.caption("不懂技術分析也沒關係，AI 幫你用白話解釋每一個數字的意義")

st.info("""
💡 **使用方式很簡單：**
1. 左側輸入你的 Gemini API 金鑰
2. 選擇台股或美股
3. 輸入股票代號（台股例如：2330、0050；美股例如：AAPL、TSLA）
4. 按下「開始分析」，等 AI 幫你解讀！
""")

# ─────────────────────────────────────────────
# 股票代號輸入
# ─────────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    if "台股" in market:
        ticker_input = st.text_input(
            "輸入台股代號",
            placeholder="例如：2330（台積電）、0050（元大台灣50）、2454（聯發科）",
        )
    else:
        ticker_input = st.text_input(
            "輸入美股代號",
            placeholder="例如：AAPL（蘋果）、TSLA（特斯拉）、NVDA（輝達）",
        )
with col2:
    st.write("")
    st.write("")
    analyze_btn = st.button("🔍 開始分析", use_container_width=True, type="primary")

# ─────────────────────────────────────────────
# 工具函數
# ─────────────────────────────────────────────

def get_ticker_symbol(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"):
        return raw + ".TW"
    return raw

def fetch_stock_data(symbol: str, period: str):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            hist   = ticker.history(period=period)
            info   = ticker.info
            if hist.empty:
                return None, None, "查無此股票代號，請確認輸入是否正確"
            return hist, info, None
        except Exception as e:
            if attempt == 2:
                return None, None, f"數據抓取失敗：{str(e)}"
            time.sleep(1)

def calculate_indicators(hist: pd.DataFrame) -> dict:
    close = hist["Close"]
    ma5   = close.rolling(5).mean()
    ma20  = close.rolling(20).mean()
    ma60  = close.rolling(60).mean()

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))

    ema12     = close.ewm(span=12).mean()
    ema26     = close.ewm(span=26).mean()
    macd      = ema12 - ema26
    signal    = macd.ewm(span=9).mean()
    hist_macd = macd - signal

    high, low = hist["High"], hist["Low"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    latest = {
        "price"      : round(float(close.iloc[-1]), 2),
        "ma5"        : round(float(ma5.iloc[-1]), 2),
        "ma20"       : round(float(ma20.iloc[-1]), 2),
        "ma60"       : round(float(ma60.iloc[-1] if len(close) >= 60 else ma20.iloc[-1]), 2),
        "rsi"        : round(float(rsi.iloc[-1]), 1),
        "macd"       : round(float(macd.iloc[-1]), 4),
        "macd_signal": round(float(signal.iloc[-1]), 4),
        "macd_hist"  : round(float(hist_macd.iloc[-1]), 4),
        "atr"        : round(float(atr.iloc[-1]), 2),
        "volume"     : int(hist["Volume"].iloc[-1]),
        "vol_avg20"  : int(hist["Volume"].rolling(20).mean().iloc[-1]),
        "change_pct" : round(float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100), 2),
        "high_52w"   : round(float(close.rolling(252).max().iloc[-1]), 2),
        "low_52w"    : round(float(close.rolling(252).min().iloc[-1]), 2),
    }

    rsi_val = latest["rsi"]
    if latest["ma5"] > latest["ma20"] > latest["ma60"] and rsi_val > 55:
        latest["status"]       = "強勢多頭 📈"
        latest["status_color"] = "🟢"
        latest["status_desc"]  = "三條均線整齊向上排列，RSI 也偏強，目前市場氣氛偏好，多方佔優勢。"
    elif latest["ma5"] < latest["ma20"] < latest["ma60"] and rsi_val < 45:
        latest["status"]       = "強勢空頭 📉"
        latest["status_color"] = "🔴"
        latest["status_desc"]  = "三條均線整齊向下排列，RSI 偏弱，目前市場下跌趨勢明顯，空方佔優勢。"
    elif rsi_val < 30:
        latest["status"]       = "超賣，留意反彈 🟡"
        latest["status_color"] = "🟡"
        latest["status_desc"]  = "RSI 低於 30，股價短期跌太多，像橡皮筋拉太緊，有機會反彈，但不代表一定會漲。"
    elif rsi_val > 70:
        latest["status"]       = "超買，留意回調 🟡"
        latest["status_color"] = "🟡"
        latest["status_desc"]  = "RSI 高於 70，股價短期漲太多，像跑太快需要喘息，短期可能會休息甚至小跌。"
    elif abs(latest["ma5"] - latest["ma20"]) / latest["price"] < 0.02:
        latest["status"]       = "均線糾結，方向未明 ⚪"
        latest["status_color"] = "⚪"
        latest["status_desc"]  = "三條均線糾纏在一起，多空雙方勢均力敵，市場在等待明確訊號，建議觀望。"
    else:
        latest["status"]       = "弱勢盤整 🟠"
        latest["status_color"] = "🟠"
        latest["status_desc"]  = "股價走勢疲軟，沒有明顯方向，在區間內來回震盪，目前不是進場好時機。"

    if rsi_val >= 70:
        latest["rsi_desc"] = f"⚠️ RSI {rsi_val}，數值偏高（超買區），短期漲太快，要小心回跌"
    elif rsi_val <= 30:
        latest["rsi_desc"] = f"💡 RSI {rsi_val}，數值偏低（超賣區），短期跌太多，留意反彈機會"
    elif rsi_val >= 50:
        latest["rsi_desc"] = f"✅ RSI {rsi_val}，數值偏強，多方略佔優勢"
    else:
        latest["rsi_desc"] = f"⚠️ RSI {rsi_val}，數值偏弱，空方略佔優勢"

    vol_ratio = latest["volume"] / latest["vol_avg20"] if latest["vol_avg20"] > 0 else 1
    latest["vol_ratio"] = round(vol_ratio, 2)
    if vol_ratio >= 1.5:
        latest["vol_desc"] = f"📢 今日成交量是近期平均的 {vol_ratio:.1f} 倍，成交活躍，市場關注度高"
    elif vol_ratio >= 0.8:
        latest["vol_desc"] = f"📊 今日成交量接近近期平均（{vol_ratio:.1f} 倍），市場熱度正常"
    else:
        latest["vol_desc"] = f"😴 今日成交量只有近期平均的 {vol_ratio:.1f} 倍，交投冷清，訊號可信度較低"

    price_range = latest["high_52w"] - latest["low_52w"]
    position = (latest["price"] - latest["low_52w"]) / price_range * 100 if price_range > 0 else 50
    latest["position_52w"] = round(position, 1)
    if position >= 80:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於相對高位，買進需謹慎"
    elif position <= 20:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於相對低位，相對便宜但需確認趨勢"
    else:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於中間區域"

    return latest

def build_chart(hist: pd.DataFrame, symbol: str):
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[
            "K線圖 + 均線（紅=漲、綠=跌）",
            "成交量（今天買賣了多少）",
            "RSI 強弱指標（70以上過熱、30以下過冷）"
        ]
    )

    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="K線",
        increasing_line_color="#ef5350",
        decreasing_line_color="#26a69a"
    ), row=1, col=1)

    close = hist["Close"]
    for span, color, name in [
        (5,  "#FFA726", "MA5（5日均線）"),
        (20, "#42A5F5", "MA20（20日均線）"),
        (60, "#AB47BC", "MA60（60日均線）")
    ]:
        fig.add_trace(go.Scatter(
            x=hist.index, y=close.rolling(span).mean(),
            line=dict(color=color, width=1.5), name=name
        ), row=1, col=1)

    colors = ["#ef5350" if c >= o else "#26a69a"
              for c, o in zip(hist["Close"], hist["Open"])]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=colors, name="成交量", showlegend=False
    ), row=2, col=1)

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
    fig.add_trace(go.Scatter(
        x=hist.index, y=rsi,
        line=dict(color="#FF7043", width=1.5), name="RSI", showlegend=False
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,83,80,0.5)",  row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(38,166,154,0.5)", row=3, col=1)

    fig.update_layout(
        title=f"{symbol} 技術分析圖表",
        height=700,
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#1E1E1E",
        paper_bgcolor="#1E1E1E",
        font_color="#FFFFFF",
        legend=dict(orientation="h", y=1.02)
    )
    return fig

def ai_analysis_beginner(ind: dict, info: dict, symbol: str, api_key: str) -> str:
    """呼叫 Gemini AI（新版 google-genai 套件），自動切換模型"""
    client = genai.Client(api_key=api_key)

    # 模型優先順序
    models_to_try = [
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash（備用）"),
        ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite（備用）"),
    ]

    company_name = info.get("longName") or info.get("shortName") or symbol
    sector       = info.get("sector", "未知產業")
    pe_ratio     = info.get("trailingPE", "N/A")

    prompt = f"""你是一位專門服務股市新手的財經老師，擅長用最簡單的白話文解釋股票。

請根據以下數據，寫一份「完全給股市小白看的分析報告」。

規則：
- 所有專業術語出現時，必須立刻用括號加上白話解釋
- 禁止使用「一定」「保證」「必漲」「必跌」等詞
- 語氣像在跟朋友解釋，輕鬆但客觀
- 每個結論都要說明「為什麼」
- 若數據不足，直接說「目前資訊不夠，無法判斷」
- 請使用繁體中文

【股票資料】
代號：{symbol}
公司：{company_name}
產業：{sector}
本益比：{pe_ratio}（本益比 = 你花多少錢買 1 元的獲利，越低可能越便宜）

【技術數據】
現價：{ind['price']}
技術狀態：{ind['status']}
今日漲跌：{ind['change_pct']}%
RSI：{ind['rsi']}（0~100，70以上過熱，30以下過冷）
MACD 動能：{'正向（上漲動能）' if ind['macd_hist'] > 0 else '負向（下跌動能）'}
成交量狀況：{ind['vol_desc']}
52週位置：{ind['position_desc']}
MA5 vs MA20：{'MA5在MA20上方（短線偏強）' if ind['ma5'] > ind['ma20'] else 'MA5在MA20下方（短線偏弱）'}

請依照以下格式輸出：

## 🔰 這支股票現在是什麼狀況？
（用 2~3 句話，像跟朋友說話一樣，說明目前股票的大致狀態）

## 📊 各項指標白話解讀

**均線（股價平均走勢）：**
（說明 MA5、MA20、MA60 的排列代表什麼意思）

**RSI（超買超賣指標）：**
（說明現在 RSI 數值代表什麼，要注意什麼）

**MACD（動能指標）：**
（說明現在動能是在增強還是減弱）

**成交量（市場熱度）：**
（說明今天的成交量狀況）

## 🎯 短期可能的走勢？
（1~2週內，客觀說明可能往上或往下的理由）

## ⚠️ 新手要特別注意什麼？
（條列 2~3 個新手容易犯的錯誤）

## 📌 總結（用一句話說重點）
（一句話總結，並說明信心程度：高／中／低）

## 📖 本報告用到的名詞解釋
（整理所有專業名詞的白話解釋）"""

    last_error = None
    for model_id, model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt
            )
            return f"> 🤖 本次使用模型：{model_name}\n\n{response.text}"
        except Exception as e:
            error_msg = str(e)
            if any(kw in error_msg for kw in ["quota", "429", "404", "not found", "RESOURCE_EXHAUSTED"]):
                last_error = f"{model_name} 額度不足或不可用"
                continue
            else:
                raise

    raise Exception(f"所有模型均無法使用。最後錯誤：{last_error}")

# ─────────────────────────────────────────────
# 主邏輯
# ─────────────────────────────────────────────
if analyze_btn:
    if not ticker_input.strip():
        st.warning("⚠️ 請輸入股票代號")
        st.stop()
    if not api_key:
        st.warning("⚠️ 請在左側輸入 Gemini API 金鑰")
        st.stop()

    symbol = get_ticker_symbol(ticker_input, market)

    with st.spinner(f"正在抓取 {symbol} 的股票數據..."):
        hist, info, error = fetch_stock_data(symbol, period)

    if error:
        st.error(f"❌ {error}")
        st.stop()

    ind          = calculate_indicators(hist)
    company_name = info.get("longName") or info.get("shortName") or symbol

    st.subheader(f"📌 {company_name}（{symbol}）")

    st.markdown(f"""
    <div style="background:#1e1e2e;border-radius:12px;padding:20px;margin-bottom:16px;border-left:5px solid #7c3aed">
        <h3 style="margin:0;color:#e2e8f0">{ind['status_color']} 目前狀態：{ind['status']}</h3>
        <p style="margin:8px 0 0 0;color:#94a3b8;font-size:15px">{ind['status_desc']}</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    change_color = "🔴" if ind['change_pct'] >= 0 else "🟢"
    c1.metric("💰 現價",     f"{ind['price']}")
    c2.metric("📅 今日漲跌", f"{change_color} {ind['change_pct']}%")
    c3.metric("📏 RSI 強弱", f"{ind['rsi']}")
    c4.metric("📐 ATR 波動", f"{ind['atr']}")
    c5.metric("📦 量比",     f"{ind['vol_ratio']}x")

    st.markdown("### 🔍 各指標白話說明")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"**📏 RSI 強弱指標**\n\n{ind['rsi_desc']}")
        st.info(f"**📦 成交量熱度**\n\n{ind['vol_desc']}")
    with col_b:
        st.info(f"**📅 52週價格位置**\n\n{ind['position_desc']}")
        macd_desc = "📈 MACD 柱狀圖為正值，上漲動能增強" if ind['macd_hist'] > 0 else "📉 MACD 柱狀圖為負值，下跌動能增強"
        st.info(f"**📡 MACD 動能**\n\n{macd_desc}")

    st.divider()

    st.markdown("### 📈 互動式圖表")
    st.caption("提示：滑鼠滾輪可縮放，拖曳可移動時間範圍；紅色代表上漲，綠色代表下跌")
    fig = build_chart(hist, symbol)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    st.markdown("### 🤖 AI 小白版分析報告")
    st.caption("由 Gemini AI 根據上方數據自動生成，僅供參考，不構成投資建議")

    with st.spinner("AI 老師正在幫你分析，請稍候（約 15~30 秒）..."):
        try:
            report = ai_analysis_beginner(ind, info, symbol, api_key)
            st.markdown(report)
        except Exception as e:
            st.error(f"❌ AI 分析失敗：{str(e)}")

    st.divider()
    st.warning("""
    ⚠️ **重要提醒**

    本系統提供的所有分析內容**僅供學習與參考用途**，不構成任何投資建議。
    股票投資有風險，過去的技術指標不保證未來走勢。
    請務必獨立判斷，或諮詢專業財務顧問後再做決策。
    """)

    with st.expander("🔧 進階：查看完整技術指標原始數據"):
        st.caption("這些是給比較進階的使用者看的原始計算數值")
        df_ind = pd.DataFrame({
            "指標": ["現價","MA5","MA20","MA60","RSI","MACD","MACD Signal",
                    "MACD Hist","ATR","成交量","20日均量","漲跌幅","52週高","52週低"],
            "數值": [ind["price"], ind["ma5"], ind["ma20"], ind["ma60"],
                    ind["rsi"], ind["macd"], ind["macd_signal"], ind["macd_hist"],
                    ind["atr"], ind["volume"], ind["vol_avg20"], f"{ind['change_pct']}%",
                    ind["high_52w"], ind["low_52w"]]
        })
        st.dataframe(df_ind, use_container_width=True, hide_index=True)