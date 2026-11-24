from collections import Counter
from itertools import combinations
from math import comb
from statistics import mean, median
from scipy.stats import chi2, rankdata


TEMPLATES = ("a","b","c")
COLUMNS = (
    ("label", "模板或比较"), ("count", "审修员"), ("time", "中位完工（分钟）"), ("rank", "平均块内秩"),
    ("estimate", "前者比后者中位省时（分钟）"), ("fre", "整体 Friedman Q"),
    ("p", "原始 p 值"), ("adjusted", "Holm p 值"), ("decision", "确认"),
)


def validate(row):
    if row["sequence"] not in {"ABC","ACB","BAC","BCA","CAB","CBA"} or not all(1 <= row[key] <= 240 for key in TEMPLATES):
        raise ValueError("随机序列需含每版一次，每版工时须为 1–240 分钟")


def sign_test(values):
    wins = sum(value>0 for value in values)
    losses = sum(value<0 for value in values)
    if wins+losses == 0:
        return 1.0
    return min(1.0,sum(comb(wins+losses,i) for i in range(min(wins,losses)+1))/2**(wins+losses-1))


def analyze(rows, parameters):
    minimum = parameters.get("min_saving",2)
    alpha = parameters.get("alpha",0.05)
    if len(rows) < 4:
        raise ValueError("三模板对照需要至少四个独立的完整审修区组")
    if len({row["reviewer"] for row in rows}) != len(rows):
        raise ValueError("审修员的同一三版区组有重复记录")
    for row in rows:
        validate(row)
    ranks = [rankdata([row[key] for key in TEMPLATES],method="average") for row in rows]
    average = [float(mean(order[index] for order in ranks)) for index in range(3)]
    n = len(rows)
    tied = sum(denominator(row) for row in rows)
    correction = 1-tied/(24*n)
    statistic = n*sum((rank-2)**2 for rank in average)/correction if correction else 0.0
    p = float(chi2.sf(statistic,2))
    results = [dict(label="三版本总体",count=n,fre=round(statistic,6),p=round(p,8),
                    decision="整体显著" if p <= alpha else "整体需补证据")]
    typical = {key:median(row[key] for row in rows) for key in TEMPLATES}
    for key,rank in zip(TEMPLATES,average):
        results.append(dict(label=f"模板 {key.upper()}",count=n,time=typical[key],rank=round(rank,4)))
    comparisons = []
    for first,second in combinations(TEMPLATES,2):
        delta = [row[second]-row[first] for row in rows]
        comparisons.append((sign_test(delta),first,second,median(delta)))
    adjusted_so_far = 0.0
    wins = {key:0 for key in TEMPLATES}
    for index,(raw,first,second,effect) in enumerate(sorted(comparisons)):
        adjusted_so_far = min(1.0,max(adjusted_so_far,raw*(len(comparisons)-index)))
        accepted = p <= alpha and adjusted_so_far <= alpha and abs(effect) >= minimum and effect != 0
        if accepted:
            wins[first if effect > 0 else second] += 1
        results.append(dict(label=f"{first.upper()} 相对 {second.upper()}",count=n,estimate=round(effect,3),
                            p=round(raw,8),adjusted=round(adjusted_so_far,8),
                            decision="达到实用与统计改善线" if accepted else "暂待确认"))
    candidates = [key for key,count in wins.items() if count == 2]
    title = f"模板 {candidates[0].upper()} 达到三版试跑切换线" if candidates else "保留现用模板，补齐差异证据"
    return report(title,
                  f"每位审修员组三版并在块内取秩。整体检验通过后比较 Holm p 和最低 {minimum:g} 分钟的配对中位差。",
                  [("独立审修区组",n,"组"),("Friedman p",round(p,8),""),("确认切换候选",len(candidates),"版")],
                  COLUMNS,results,"三种模板平均块内用时秩",[(key.upper(),round(rank,4)) for key,rank in zip(TEMPLATES,average)])


def denominator(row):
    return sum(ties**3-ties for ties in Counter(row[key] for key in TEMPLATES).values())


def seed():
    sequences = ("ABC","ACB","BAC","BCA","CAB","CBA")
    rows = []
    for index in range(24):
        sequence = sequences[index%len(sequences)]
        center = 27+(index*13%17)*0.49
        times = {}
        for key,offset in zip(TEMPLATES,(2.5,-3.4,1.8)):
            times[key] = round(center+offset+((index+ord(key)*4)%13-6)*0.35-sequence.index(key.upper())*0.24,2)
        rows.append(dict(reviewer=f"YG-{index+1:02d}",sequence=sequence,**times))
    return rows


def report(headline, summary, metrics, columns, rows, chart_label, chart_values, unit=""):
    return {
        "headline": headline, "summary": summary,
        "metrics": [{"label": label, "value": value, "unit": suffix} for label, value, suffix in metrics],
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": [{key: row.get(key) for key, _ in columns} for row in rows],
        "chart": {"label": chart_label, "unit": unit,
                  "points": [{"label": label, "value": value} for label, value in chart_values]},
    }
