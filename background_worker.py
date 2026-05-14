import time
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client

# 填入您的 Supabase 資訊 (請確保與 app.py 的 secrets 一致)
SUPABASE_URL = "https://kwnwylttozycqabvfjwa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3bnd5bHR0b3p5Y3FhYnZmandhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg0MTgzNTEsImV4cCI6MjA5Mzk5NDM1MX0.1jEu7cR5GVks8RZPPwqSuoCBdGTtE8s3O4c0z5ZGdAc"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
TW_TZ = timezone(timedelta(hours=8))

def calc_ml_features(hist: pd.DataFrame) -> pd.DataFrame:
    """計算並回傳包含特徵與標籤的 DataFrame，供 ML 訓練使用"""
    df = hist.copy()
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float)
    
    # 技術指標 (特徵)
    df['ma5'] = c.rolling(5).mean()
    df['ma20'] = c.rolling(20).mean()
    df['ma60'] = c.rolling(60).mean()
    df['dist_ma20'] = (c - df['ma20']) / df['ma20']
    
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_s = macd.ewm(span=9, adjust=False).mean()
    df['macd_hist'] = macd - macd_s
    df['macd_slope'] = df['macd_hist'].diff()
    
    diff = c.diff()
    gain = diff.clip(lower=0).rolling(14).mean()
    loss = (-diff.clip(upper=0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))
    
    bb_m = df['ma20']
    bb_s = c.rolling(20).std()
    bb_u, bb_l = bb_m + 2*bb_s, bb_m - 2*bb_s
    df['bb_pct'] = (c - bb_l) / (bb_u - bb_l + 1e-10)
    
    vol_ma20 = v.rolling(20).mean()
    df['vol_ratio'] = v / vol_ma20.replace(0, 1)
    
    high_52w = c.rolling(252, min_periods=1).max()
    low_52w = c.rolling(252, min_periods=1).min()
    df['pos_52w'] = (c - low_52w) / (high_52w - low_52w + 1e-10)
    
    # 目標標籤 (Label): 未來 3 天內最高價是否超過今日收盤價 2%
    future_high = h.shift(-3).rolling(3).max()
    df['target'] = ((future_high / c - 1) > 0.02).astype(int)
    
    return df.dropna()

def train_and_predict(all_dfs: dict):
    """將全市場數據聚合，訓練隨機森林模型，並預測最新勝率"""
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] ⚙️ 正在建構機器學習特徵與訓練模型...")
    features = ['dist_ma20', 'macd_hist', 'macd_slope', 'rsi', 'bb_pct', 'vol_ratio', 'pos_52w']
    
    train_data_list = []
    latest_data_dict = {}
    
    for sym, df in all_dfs.items():
        if len(df) < 60: continue
        feat_df = calc_ml_features(df)
        if len(feat_df) < 5: continue
        
        # 排除最後 3 天作為訓練集 (因為標籤是未來 3 天，最後 3 天是未知)
        train_data_list.append(feat_df.iloc[:-3])
        # 保留最後 1 筆作為預測輸入
        latest_data_dict[sym] = feat_df.iloc[-1:][features]
        
    if not train_data_list: return {}
    
    full_train_df = pd.concat(train_data_list)
    X_train = full_train_df[features]
    y_train = full_train_df['target']
    
    # 訓練隨機森林
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    # 預測全市場最新勝率
    win_probs = {}
    for sym, X_latest in latest_data_dict.items():
        prob = model.predict_proba(X_latest)[0][1] # 取類別 1 (上漲) 的機率
        win_probs[sym] = round(prob * 100, 1)
        
    return win_probs

def get_full_universe():
    try:
        from FinMind.data import DataLoader
        df = DataLoader().taiwan_stock_info()
        df = df[df['type'].isin(['twse', 'tpex'])]
        universe = {"個股": {}, "被動式ETF": {}, "主動式ETF": {}}
        for _, row in df.iterrows():
            sym, name, ind = str(row['stock_id']), str(row['stock_name']), str(row['industry_category'])
            full_sym = f"{sym}.TW" if row['type'] == 'twse' else f"{sym}.TWO"
            if ind == 'ETF' or sym.startswith('00'):
                if sym.endswith('A'): universe["主動式ETF"][full_sym] = name
                else: universe["被動式ETF"][full_sym] = name
            elif len(sym) == 4 and sym.isdigit(): universe["個股"][full_sym] = name
        return universe
    except Exception as e: return None

def generate_leaderboard():
    universe = get_full_universe()
    if not universe: return
        
    all_tickers = [sym for cat in universe.values() for sym in cat.keys()]
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 📥 開始批次下載 {len(all_tickers)} 檔歷史數據...")
    data = yf.download(all_tickers, period="6mo", group_by="ticker", threads=True, progress=False)
    
    # 整理有效 DataFrame 供 ML 使用
    valid_dfs = {}
    for sym in all_tickers:
        try:
            df = data[sym] if len(all_tickers) > 1 else data
            if "Close" in df.columns and len(df.dropna(subset=["Close"])) >= 60:
                valid_dfs[sym] = df.dropna(subset=["Close"])
        except: continue

    # 執行 ML 預測
    ml_win_probs = train_and_predict(valid_dfs)
    update_time = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    db_records = []
    
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 🧠 進行指標評分與資料庫寫入...")
    for category, symbols_dict in universe.items():
        for sym, name in symbols_dict.items():
            if sym not in valid_dfs or sym not in ml_win_probs: continue
            
            df = valid_dfs[sym]
            c = float(df["Close"].iloc[-1])
            vol = float(df["Volume"].iloc[-1])
            if vol < 500 and category == "個股": continue # 流動性過濾
            
            # 使用最新的一筆特徵計算傳統分數 (沿用 V7.7 邏輯保留相容性)
            ma5, ma20, ma60 = df["Close"].rolling(5).mean().iloc[-1], df["Close"].rolling(20).mean().iloc[-1], df["Close"].rolling(60).mean().iloc[-1]
            vwap = ((df["High"]+df["Low"]+df["Close"])/3*df["Volume"]).rolling(20).sum().iloc[-1] / (df["Volume"].rolling(20).sum().iloc[-1]+1e-10)
            vol_ratio = vol / (df["Volume"].rolling(20).mean().iloc[-1] + 1)
            
            close_strength = (c - df["Low"].iloc[-1]) / max((df["High"].iloc[-1] - df["Low"].iloc[-1]), 0.01)
            dt_score = min(100, int((vol_ratio * 15) + (close_strength * 30) + (20 if c > vwap else 0)))
            st_score = min(100, int(35 if ma5 > ma20 else 0))
            lt_score = min(100, int(40 if c > ma60 else 0))
            total_score = round(dt_score * 0.2 + st_score * 0.4 + lt_score * 0.4, 1)
            
            db_records.append({
                "symbol": sym.replace(".TW", "").replace(".TWO", ""),
                "name": name,
                "category": category,
                "total_score": total_score,
                "ml_win_prob": ml_win_probs[sym],
                "dt_score": dt_score,
                "st_score": st_score,
                "lt_score": lt_score,
                "dt_reason": f"AI 勝率預測: {ml_win_probs[sym]}%",
                "st_reason": f"量比: {vol_ratio:.1f}x",
                "lt_reason": "技術面強度" if ma20 > ma60 else "空頭排列",
                "status": "AI 分析完成",
                "update_time": update_time
            })
            
    # 寫入 Supabase (使用 upsert 避免主鍵衝突)
    if db_records:
        try:
            supabase.table("ai_leaderboard").upsert(db_records).execute()
            print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] ✅ 成功寫入 {len(db_records)} 筆紀錄至 Supabase！")
        except Exception as e:
            print(f"寫入資料庫失敗: {e}")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        time.sleep(3600)