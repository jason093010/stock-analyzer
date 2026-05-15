import os
import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client

# 初始化 Supabase 客戶端
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TW_TZ = timezone(timedelta(hours=8))

def calc_ml_features(hist: pd.DataFrame) -> pd.DataFrame:
    """計算機器學習所需的量化特徵與預測標籤"""
    df = hist.copy()
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float)
    
    # --- 1. 基礎技術特徵 ---
    df['ma5'] = c.rolling(5).mean()
    df['ma20'] = c.rolling(20).mean()
    df['ma60'] = c.rolling(60).mean()
    df['dist_ma20'] = (c - df['ma20']) / df['ma20']
    
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_h = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
    df['macd_hist'] = macd_h
    df['macd_slope'] = macd_h.diff()
    
    diff = c.diff()
    up_m = diff.clip(lower=0).rolling(14).mean()
    dn_m = -diff.clip(upper=0).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + up_m / dn_m.replace(0, 1e-10)))
    
    bb_m = df['ma20']
    bb_s = c.rolling(20).std()
    df['bb_pct'] = (c - (bb_m - 2*bb_s)) / (4*bb_s + 1e-10)
    df['vol_ratio'] = v / v.rolling(20).mean().replace(0, 1)
    
    # --- 2. 進階波動與型態特徵 ---
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df['atr_ratio'] = tr.rolling(14).mean() / c
    df['gap_pct'] = (df['Open'] - c.shift(1)) / c.shift(1)
    
    # 新增：K棒影線比例 (衡量潛在買賣壓)
    df['upper_shadow'] = (h - df[['Open', 'Close']].max(axis=1)) / (h - l + 1e-10)
    df['lower_shadow'] = (df[['Open', 'Close']].min(axis=1) - l) / (h - l + 1e-10)

    # 新增：價格動能加速度 (辨識發動跡象)
    df['roc_5'] = c.pct_change(5)
    df['roc_20'] = c.pct_change(20)
    df['mom_accel'] = df['roc_5'] - df['roc_20'] / 4
    
    # --- 3. 嚴格化預測標籤 (Triple Barrier) ---
    future_close = c.shift(-3)
    future_low = l.shift(-3).rolling(3).min()
    
    # 條件：未來三天收盤大於 2%，且期間低點未跌破 -1.5%
    df['target'] = (
        ((future_close / c - 1) > 0.02) & 
        ((future_low / c - 1) > -0.015)
    ).astype(int)
    
    return df.dropna()

def get_universe():
    """獲取台股全市場清單，包含個股與 ETF"""
    try:
        from FinMind.data import DataLoader
        df = DataLoader().taiwan_stock_info()
        df = df[df['type'].isin(['twse', 'tpex'])]
        uni = {"個股": {}, "被動式ETF": {}, "主動式ETF": {}}
        for _, r in df.iterrows():
            sym = str(r['stock_id'])
            name = str(r['stock_name'])
            ind = str(r['industry_category'])
            f_sym = f"{sym}.TW" if r['type'] == 'twse' else f"{sym}.TWO"
            
            if ind == 'ETF' or sym.startswith('00'):
                uni["主動式ETF" if sym.endswith('A') else "被動式ETF"][f_sym] = name
            elif len(sym) == 4 and sym.isdigit(): 
                uni["個股"][f_sym] = name
        return uni
    except Exception as e:
        print(f"❌ 取得股票清單失敗，錯誤訊息：{e}")
        return None

def run_pipeline():
    universe = get_universe()
    if not universe: 
        print("⚠️ 程式提前終止：無法獲取股票清單。請檢查 API 連線或套件狀態。")
        return
        
    tickers = [s for cat in universe.values() for s in cat.keys()]
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 開始下載 {len(tickers)} 檔歷史數據 (單線程防擋模式)...")
    
    # 關閉多線程 (threads=False) 以避免 Yahoo Finance 阻擋
    data = yf.download(tickers, period="6mo", group_by="ticker", threads=False, progress=False)
    
    valid_dfs = {}
    for sym in tickers:
        try:
            df = data[sym] if len(tickers) > 1 else data
            if "Close" in df.columns and len(df.dropna(subset=["Close"])) >= 20:
                valid_dfs[sym] = df.dropna(subset=["Close"])
        except: 
            continue

    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 進行特徵工程與模型訓練...")
    
    # 擴充後的 12 個 AI 評估特徵
    features = [
        'dist_ma20', 'macd_hist', 'macd_slope', 'rsi', 'bb_pct', 
        'vol_ratio', 'atr_ratio', 'gap_pct', 'upper_shadow', 
        'lower_shadow', 'roc_5', 'mom_accel'
    ]
    
    train_list = []
    latest_dict = {}
    
    for sym, df in valid_dfs.items():
        f_df = calc_ml_features(df)
        if len(f_df) < 5: 
            continue
        if len(df) >= 60: 
            train_list.append(f_df.iloc[:-3]) # 扣除最後三天以避免資料穿越 (Look-ahead bias)
        latest_dict[sym] = f_df.iloc[-1:][features]
        
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
    
    if train_list:
        full_train = pd.concat(train_list)
        model.fit(full_train[features], full_train['target'])
    
    win_probs = {sym: round(model.predict_proba(X)[0][1] * 100, 1) for sym, X in latest_dict.items()} if train_list else {}
    
    db_records = []
    upd_time = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    
    for cat, syms in universe.items():
        for sym, name in syms.items():
            if sym not in valid_dfs or sym not in win_probs: 
                continue
            
            df = valid_dfs[sym]
            c = df["Close"].iloc[-1]
            h = df["High"].iloc[-1]
            l = df["Low"].iloc[-1]
            v = df["Volume"].iloc[-1]
            
            # 流動性濾網：剔除成交量過低的個股
            if v < 500 and cat == "個股": 
                continue
            
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            ma20 = df["Close"].rolling(20).mean().iloc[-1]
            ma60 = df["Close"].rolling(60).mean().iloc[-1]
            
            vwap = ((df["High"]+df["Low"]+df["Close"])/3*df["Volume"]).rolling(20).sum().iloc[-1] / (df["Volume"].rolling(20).sum().iloc[-1]+1e-10)
            vr = v / (df["Volume"].rolling(20).mean().iloc[-1] + 1e-10)
            cs = (c - l) / max((h - l), 0.01)
            
            up_m = df["Close"].diff().clip(lower=0).rolling(14).mean().iloc[-1]
            dn_m = -df["Close"].diff().clip(upper=0).rolling(14).mean().iloc[-1]
            rsi_val = 100 - (100 / (1 + up_m / max(dn_m, 1e-10)))
            
            # 傳統技術面量化評分
            dt_s = min(100, int((vr * 15) + (cs * 30) + (20 if c > vwap else 0)))
            st_s = min(100, int((35 if ma5 > ma20 else 0) + (15 if 40 <= rsi_val <= 70 else 0)))
            lt_s = min(100, int((40 if c > ma60 else 0) + (30 if ma20 > ma60 else 0)))
            
            db_records.append({
                "symbol": sym.replace(".TW", "").replace(".TWO", ""), 
                "name": name, 
                "category": cat,
                "total_score": round(dt_s * 0.2 + st_s * 0.4 + lt_s * 0.4, 1), 
                "ml_win_prob": win_probs[sym],
                "dt_score": dt_s, 
                "st_score": st_s, 
                "lt_score": lt_s,
                "dt_reason": f"收盤近最高({cs*100:.0f}%)" if cs > 0.8 else f"量能({vr:.1f}x)",
                "st_reason": "均線多頭" if ma5 > ma20 else "均線震盪",
                "lt_reason": "長線多頭" if ma20 > ma60 else "長線偏弱",
                "status": "AI 預測完成", 
                "update_time": upd_time
            })
            
    if db_records:
        supabase.table("ai_leaderboard").upsert(db_records).execute()
        print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 成功寫入 {len(db_records)} 筆至 Supabase")

if __name__ == "__main__":
    run_pipeline()