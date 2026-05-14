import json
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from app import fetch_data, calc_indicators

TW_TZ = timezone(timedelta(hours=8))

def get_full_universe():
    """動態獲取全台灣上市/上櫃所有標的，並自動分類"""
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 正在從 FinMind 獲取全市場最新標的清單...")
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        df = dl.taiwan_stock_info()
        
        # 僅保留上市 (twse) 與上櫃 (tpex)
        df = df[df['type'].isin(['twse', 'tpex'])]
        
        universe = {"個股": {}, "被動式ETF": {}, "主動式ETF": {}}
        
        for _, row in df.iterrows():
            sym = str(row['stock_id'])
            name = str(row['stock_name'])
            ind = str(row['industry_category'])
            
            suffix = ".TW" if row['type'] == 'twse' else ".TWO"
            full_sym = f"{sym}{suffix}"
            
            # 分類邏輯
            if ind == 'ETF' or sym.startswith('00'):
                # 台灣主動式 ETF 命名慣例為字尾 'A'
                if sym.endswith('A'):
                    universe["主動式ETF"][full_sym] = name
                else:
                    universe["被動式ETF"][full_sym] = name
            else:
                # 一般個股通常為 4 碼數字 (排除權證、ETN 等)
                if len(sym) == 4 and sym.isdigit():
                    universe["個股"][full_sym] = name
                    
        return universe
    except Exception as e:
        print(f"獲取全市場清單失敗: {e}")
        return None

def analyze_asset(sym, name, category):
    h, info, err = fetch_data(sym, "6mo")
    if err or h is None or h.empty: 
        return None
    
    ind = calc_indicators(h)
    
    dt_score = min(100, int((ind["vol_ratio"] / 2.5 * 40) + (20 if ind["price"] > ind["vwap"] else 0) + (ind["rsi"] * 0.4)))
    st_score = min(100, int((30 if ind["ma5"] > ind["ma20"] else 0) + (30 if ind["macd_hist"] > 0 else 0) + (ind["stoch_k"] * 0.4)))
    lt_score = min(100, int((40 if ind["price"] > ind["ma60"] else 0) + (30 if 30 <= ind["position_52w"] <= 70 else 10) + (30 if ind["ma20"] > ind["ma60"] else 0)))
    
    total_score = round(dt_score * 0.2 + st_score * 0.4 + lt_score * 0.4, 1)
    
    reason = []
    if dt_score > 75: reason.append(f"量能放大({ind['vol_ratio']:.1f}x)")
    if st_score > 75: reason.append("短線均線多頭")
    if lt_score > 75: reason.append("站穩季線支撐")
    if not reason: reason.append("震盪盤整中")

    return {
        "sym": sym.replace(".TW", "").replace(".TWO", ""),
        "name": name,
        "category": category,
        "score": total_score,
        "dt_score": dt_score,
        "st_score": st_score,
        "lt_score": lt_score,
        "status": ind["status"],
        "reason": " | ".join(reason),
        "update_time": datetime.now(TW_TZ).strftime("%m/%d %H:%M")
    }

def generate_leaderboard():
    universe = get_full_universe()
    if not universe:
        print("無法取得清單，排程暫停。")
        return
        
    total_items = sum(len(v) for v in universe.values())
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 開始執行全市場 {total_items} 檔標的掃描 (預計需時 45-60 分鐘)...")
    
    all_results = {"個股": [], "被動式ETF": [], "主動式ETF": []}
    count = 0
    
    for category, symbols_dict in universe.items():
        for sym, name in symbols_dict.items():
            count += 1
            if count % 100 == 0:
                print(f"  > 進度: {count} / {total_items} ...")
                
            res = analyze_asset(sym, name, category)
            if res: all_results[category].append(res)
            
            time.sleep(1.2)  # 嚴格的 API 速率控制，避免 IP 被封鎖
            
    # 掃描完畢，對每個分類取 Top 10
    final_lb = {}
    for cat, items in all_results.items():
        final_lb[cat] = sorted(items, key=lambda x: x["score"], reverse=True)[:10]
        
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(final_lb, f, ensure_ascii=False, indent=4)
        
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] ✅ 全市場排行榜更新完成並寫入檔案！")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        # 由於一次掃描已耗時約一小時，因此掃描間隔縮短為 2 小時 (7200秒)
        time.sleep(7200)