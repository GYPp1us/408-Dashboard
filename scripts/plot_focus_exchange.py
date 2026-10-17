"""Reproducible, synthetic parameter/anchor study; no production data."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".tmp/matplotlib"))
sys.path.insert(0, str(ROOT))

import json
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

from app.focus_exchange import BookInput, ExchangeParameters, FocusClock, PriceBook
from app.focus_kline import _seed_for, build_focus_klines, close_return, trading_session_windows

OUTPUT = ROOT / "artifacts/focus-exchange-study"
DAY = datetime(2026, 10, 15, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
START = int(DAY.timestamp() * 1000)
EARLIER = ExchangeParameters(noise_volatility=.003, value_relaxation_seconds=90)
FOCUS_COLOR = "#74a68a"
VALUE_COLOR = "#287eab"
FORECAST_COLOR = "#b57834"
PRICE_COLOR = "#262d34"


def segments_for(spans):
    return [(DAY + timedelta(minutes=a), DAY + timedelta(minutes=b)) for a, b in spans]


def finish(fig, name):
    fig.savefig(OUTPUT / (name + ".png"), dpi=160)
    fig.savefig(OUTPUT / (name + ".svg"))
    plt.close(fig)


def fixed_book(spans, parameters, seed=127, minutes=240):
    def inputs(ms):
        minute = (ms - START) / 60000
        return BookInput(True, "morning", any(a <= minute < b for a, b in spans),
                         100, 100, 90, 110)
    return PriceBook(START, 100, seed, parameters, record_trades=True).advance(
        START + minutes * 60000, inputs)


def metrics(book):
    prices = [p["price"] for p in book.samples if not p["changed"]]
    changes = [b - a for a, b in zip(prices, prices[1:])]
    trades = book.all_trades
    return {
        "minute_change_std": statistics.pstdev(changes),
        "maximum_value_gap_percent": max(abs(p - 100) for p in prices),
        "fraction_outside_value_zone": sum(abs(p - 100) > 1.2 for p in prices) / len(prices),
        "minimum_trade_interval_ms": min((b["timestamp_ms"] - a["timestamp_ms"]
                                          for a, b in zip(trades, trades[1:])), default=0),
        "maximum_trade_step": max((abs(b["price"] - a["price"])
                                    for a, b in zip(trades, trades[1:])), default=0),
        "execution_count": len(trades),
    }


def parameter_study():
    spans = [(20, 50), (75, 105), (130, 160), (185, 215)]
    candidates = {
        "低扰动对照：.003 / 跟随 90 秒": EARLIER,
        "扰动 .006 / 跟随 45 秒": ExchangeParameters(noise_volatility=.006),
        "采用：扰动 .009 / 跟随 45 秒": ExchangeParameters(),
        "扰动 .012 / 跟随 45 秒": ExchangeParameters(noise_volatility=.012),
        "扰动 .009 / 跟随 30 秒": ExchangeParameters(value_relaxation_seconds=30),
    }
    report = {}
    for name, parameters in candidates.items():
        observations = [metrics(fixed_book(spans, parameters, seed))
                        for seed in (42, 127, 371, 839, 20261015)]
        report[name] = {key: round(statistics.mean(row[key] for row in observations), 6)
                        for key in observations[0]}

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 6), sharex=True, sharey=True,
                             layout="constrained")
    for axis, parameters, title in zip(axes, (EARLIER, ExchangeParameters()),
                                      ("低扰动对照：.003 / 90 秒", "采用：.009 / 45 秒；切换压力仍分 8 分钟释放")):
        book = fixed_book(spans, parameters)
        axis.plot([(p["timestamp_ms"] - START) / 60000 for p in book.samples],
                  [p["price"] for p in book.samples], color=PRICE_COLOR, lw=1.25)
        axis.axhline(100, color=VALUE_COLOR, ls="--", lw=.9, label="固定价值 100（控制实验）")
        axis.axhline(101.2, color="#858585", ls=":", lw=.8, label="反向动量开始积累的位置 ±1.2%")
        axis.axhline(98.8, color="#858585", ls=":", lw=.8)
        for a, b in spans:
            axis.axvspan(a, b, color=FOCUS_COLOR, alpha=.13, lw=0)
        axis.set_title(title, loc="left", fontsize=11)
        axis.set_ylabel("指数点")
        axis.grid(alpha=.13)
    axes[0].legend(loc="upper right", fontsize=8, ncol=2)
    axes[-1].set_xlabel("分钟；绿色区域为专注；两图使用相同扰动种子与相同纵轴")
    finish(fig, "volatility-adjustment")
    return report


def soft_zone_study():
    spans=[(20,80),(110,170)]
    candidates={
        "不加区间反向动量":ExchangeParameters(reversion_strength=0),
        "较弱回拉 .2":ExchangeParameters(reversion_strength=.2),
        "采用回拉 .35":ExchangeParameters(),
        "较强回拉 .6":ExchangeParameters(reversion_strength=.6),
    }
    report={}
    for name,parameters in candidates.items():
        rows=[metrics(fixed_book(spans,parameters,seed)) for seed in (42,127,371,839,20261015)]
        report[name]={key:round(statistics.mean(row[key] for row in rows),6) for key in rows[0]}
    book=fixed_book(spans,ExchangeParameters(),seed=127)
    unopposed=fixed_book(spans,ExchangeParameters(reversion_strength=0),seed=127)
    fig,axes=plt.subplots(2,1,figsize=(11.5,6.2),sharex=True,layout="constrained",
                          gridspec_kw={"height_ratios":[1.7,1]})
    times=[(p['timestamp_ms']-START)/60000 for p in book.samples]
    axes[0].plot([(p['timestamp_ms']-START)/60000 for p in unopposed.samples],
                 [p['price'] for p in unopposed.samples],color='#a6a6a6',lw=.9,label='不加区间反向动量')
    axes[0].plot(times,[p['price'] for p in book.samples],color=PRICE_COLOR,lw=1.2,label='采用：区间外逐层积累反向动量')
    axes[0].axhline(100,color=VALUE_COLOR,ls='--',lw=.8,label='固定价值 100（控制实验）')
    axes[0].axhline(101.2,color='#b89069',ls=':',lw=.8,label='反向动量起点；允许穿越')
    axes[0].axhline(98.8,color='#b89069',ls=':',lw=.8)
    axes[0].set_ylabel('指数点')
    axes[0].set_title('价值区间是回拉起点：可以越过，也可以继续向外成交',loc='left',fontsize=12)
    axes[0].legend(loc='upper right',fontsize=8,ncol=2)
    axes[1].plot(times,[p['reversion_momentum']*100 for p in book.samples],
                 color=FORECAST_COLOR,lw=1.1,label='已积累的价值反向动量')
    axes[1].axhline(0,color='#999',lw=.6)
    axes[1].set_ylabel('反向动量（%）')
    axes[1].set_title('高估时积累向下压力，低估时积累向上压力；回到区间后逐渐消散',loc='left',fontsize=10)
    for axis in axes:
        for a,b in spans:axis.axvspan(a,b,color=FOCUS_COLOR,alpha=.1,lw=0)
        axis.grid(alpha=.13)
    axes[-1].set_xlabel('分钟；绿色为专注；同一扰动种子；保留每日涨跌停限制')
    finish(fig,'soft-value-zones')
    report['example']={**metrics(book),'outside_outward_executions':sum(
        t['price']>101.2 and t['direction']>0 or t['price']<98.8 and t['direction']<0
        for t in book.all_trades)}
    return report


def full_row(spans, parameters=None):
    return build_focus_klines(
        now=DAY.replace(hour=22), daily_focus_seconds={DAY.date(): sum((b-a)*60 for a, b in spans)},
        daily_segments={DAY.date(): segments_for(spans)}, exchange_at=DAY,
        exchange_parameters=parameters, user_key=27,
    )[0]


def session_plot(axis, points, field, *, label, color, linestyle="-", linewidth=1.2):
    for index, session in enumerate(("morning", "afternoon")):
        group = [p for p in points if p["session"] == session]
        times = [(datetime.fromisoformat(p["timestamp"]) - DAY).total_seconds()/3600 + 8 for p in group]
        axis.plot(times, [p[field] for p in group], label=label if index == 0 else None,
                  color=color, ls=linestyle, lw=linewidth)


def anchor_explanation():
    # Morning idleness, then catch-up: actual focus crosses 4/7/9 hours.
    spans = [(180, 240), (330, 630), (660, 840)]  # 11–12, 13:30–18:30, 19–22; 9 h.
    row = full_row(spans)
    points = [p for p in row["intraday"] if "value" in p]
    clock = FocusClock(segments_for(spans))
    windows = trading_session_windows(DAY.date(), target_zone=DAY.tzinfo)
    total_market = sum((w["end"] - w["start"]).total_seconds() for w in windows)
    actual, forecast, targets = [], [], []
    for point in points:
        at = datetime.fromisoformat(point["timestamp"])
        earned = clock.total(at.timestamp()) / 3600
        elapsed = sum(max(0, (min(at, w["end"]) - w["start"]).total_seconds()) for w in windows)
        projected = min(24, earned * total_market / max(1, elapsed))
        actual.append(earned)
        forecast.append(projected)
        targets.append(100 * (1 + close_return(projected)))
    times = [(datetime.fromisoformat(p["timestamp"]) - DAY).total_seconds()/3600 + 8 for p in points]

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7), sharex=True, layout="constrained",
                             gridspec_kw={"height_ratios": [1, 1.6]})
    axes[0].plot(times, forecast, color=FORECAST_COLOR, lw=1.4, label="按目前效率预计全天专注")
    axes[0].plot(times, actual, color=FOCUS_COLOR, lw=1.6, label="已实际完成的专注")
    for threshold, value in ((4, 90), (7, 100), (9, 110)):
        axes[0].axhline(threshold, color="#999", ls=":", lw=.7)
        axes[0].text(8.06, threshold+.1, f"{threshold} 小时 → 收盘价值 {value}", fontsize=8, color="#666")
    axes[0].set_ylim(0, 10.4)
    axes[0].set_ylabel("专注小时")
    axes[0].set_title("上午较空、下午追上：当天最终专注 9 小时（合成示例）", loc="left", fontsize=12)
    axes[0].legend(loc="upper left", bbox_to_anchor=(.22, 1), fontsize=9, ncol=2)

    forecast_points = [dict(p, forecast_target=value) for p, value in zip(points, targets)]
    session_plot(axes[1], forecast_points, "forecast_target", label="预计收盘价值",
                 color=FORECAST_COLOR, linestyle=":", linewidth=1.2)
    session_plot(axes[1], points, "value", label="盘中价值锚点", color=VALUE_COLOR,
                 linestyle="--", linewidth=1.3)
    session_plot(axes[1], points, "price", label="调整后的实际成交价格", color=PRICE_COLOR,
                 linewidth=1.15)
    for session in ("morning", "afternoon"):
        group = [p for p in points if p["session"] == session]
        x = [(datetime.fromisoformat(p["timestamp"]) - DAY).total_seconds()/3600 + 8 for p in group]
        axes[1].fill_between(x, [p["support"] for p in group], [p["resistance"] for p in group],
                             color="#718797", alpha=.08)
    axes[1].scatter([22], [row["close"]], s=18, color=PRICE_COLOR, zorder=5)
    axes[1].set_ylabel("指数点")
    axes[1].set_title("锚点向预计收盘价值逐渐靠近；预期改变时，它也会转弯", loc="left", fontsize=11)
    axes[1].legend(loc="upper left", fontsize=9, ncol=3)
    for axis in axes:
        for a, b in spans:
            axis.axvspan(8+a/60, 8+b/60, color=FOCUS_COLOR, alpha=.07, lw=0)
        axis.axvspan(12, 13.5, color="#d8d8d8", alpha=.2, lw=0)
        axis.grid(alpha=.13)
        axis.set_xlim(8, 22.25)
    axes[-1].set_xticks(range(8, 23), [f"{hour}:00" for hour in range(8, 23)])
    axes[-1].set_xlabel("绿色为专注；灰色为午休（不成交）；22:00 圆点为收盘竞价")
    finish(fig, "value-anchor-explained")
    return {"actual_focus_hours": 9, "close": row["close"],
            "minimum_value": min(p["value"] for p in points),
            "maximum_value": max(p["value"] for p in points),
            "forecast_hours_range": [min(forecast), max(forecast)]}


def switch_study():
    report = {}
    for name, spans in {
        "one_30_minute_focus": [(60, 90)],
        "toggle_every_minute": [(minute, minute+1) for minute in range(60, 90, 2)],
        "continuous_focus": [(60, 180)],
    }.items():
        book = fixed_book(spans, ExchangeParameters(), _seed_for(27, DAY.date().isoformat()), 200)
        report[name] = {key: round(value, 6) for key, value in metrics(book).items()}
        report[name]["pending_switch_return"] = book.pending_switch
    return report


def individual_executions():
    book = fixed_book([(1, 12)], ExchangeParameters(noise_volatility=0), seed=42, minutes=12)
    trades = [t for t in book.all_trades if START+6*60000 <= t["timestamp_ms"] <= START+6*60000+10000]
    fig, axis = plt.subplots(figsize=(11, 3), layout="constrained")
    axis.step([(t["timestamp_ms"]-START-6*60000)/1000 for t in trades],
              [t["price"] for t in trades], where="post", color=PRICE_COLOR, marker=".", ms=4)
    axis.set_xlabel("秒")
    axis.set_ylabel("指数点")
    axis.set_title("真实成交记录：每笔移动 0.001，两笔至少间隔 100 毫秒", loc="left", fontsize=11)
    axis.ticklabel_format(axis="y", style="plain", useOffset=False)
    axis.grid(alpha=.15)
    finish(fig, "individual-executions")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists():
        plt.rcParams["font.family"] = FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    report = {"soft_zones":soft_zone_study(), "parameters": parameter_study(), "value_scenario": anchor_explanation(),
              "switches": switch_study()}
    individual_executions()
    (OUTPUT / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
