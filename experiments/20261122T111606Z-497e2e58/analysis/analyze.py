import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
root=Path(sys.argv[1])
out=Path(__file__).parent
corpora=['mail-public','enronqa-en','enronqa-ru']
labels=['SmartMail','EnronQA EN','EnronQA RU']
models=['e5-cosine','bm25-then-e5','e5-then-bm25','e5-bm25-rrf','bm25-event-aware']
names=['E5','BM25 → E5','E5 → BM25','RRF','BM25']
rows=[]
stats=['# Парные сравнения','', 'Одна единица наблюдения — запрос. Доверительные интервалы описательные, 95%, процентильный bootstrap 5 000 раз с пересэмплированием целых ящиков. В каждой выборке среднее взвешено по запросам. Перевод EnronQA и оригинал рассмотрены отдельно. При малом числе ящиков интервалы нестабильны.','', '| Набор | Сравнение (nDCG@10) | Δ | 95% интервал | Выше / равно / ниже | Ящиков |','|---|---|---:|---:|---:|---:|']
for corpus,label in zip(corpora,labels):
    samples = {}
    for model in models:
        samples[model]={r['query_id']:r for line in (root/corpus/model/'per_query.jsonl').read_text().splitlines() if (r:=json.loads(line))}
    ref=samples[models[-1]]
    ids=list(ref)
    assert all(set(d)==set(ids) for d in samples.values())
    boxes=np.array([ref[i]['synthetic_user'] for i in ids])
    groups=np.unique(boxes)
    vals=np.array([[d[i]['metrics']['10']['ndcg'] for i in ids] for d in samples.values()])
    rows.append(vals.mean(axis=1))
    for j,k in [(3,0),(3,4)]:
        delta=vals[j]-vals[k]
        sizes=np.array([np.count_nonzero(boxes==g) for g in groups])
        totals=np.array([sum(delta[boxes==g]) for g in groups])
        ix=np.random.default_rng(47).integers(len(groups),size=(5000,len(groups)))
        lo,hi=np.quantile(totals[ix].sum(axis=1)/sizes[ix].sum(axis=1),[.025,.975])
        wins=int(sum(delta>1e-12));losses=int(sum(delta< -1e-12))
        stats.append(f'| {label} | {names[j]} − {names[k]} | {delta.mean():+.4f} | [{lo:+.4f}, {hi:+.4f}] | {wins} / {len(ids)-wins-losses} / {losses} | {len(groups)} |')
(out/'stats-appendix.md').write_text('\n'.join(stats)+'\n')
fig,ax=plt.subplots(figsize=(8,4.2),layout='constrained')
x=np.arange(3)
for j,name in enumerate(names):
    ax.bar(x+.15*(j-2),np.array(rows)[:,j],.145,label=name,color=['#9fa9b5','#7baac5','#5189a9','#176888','#314361'][j])
ax.set(xticks=x,xticklabels=labels,ylabel='nDCG@10',ylim=(0,1.05),title='Качество поиска на трёх корпусах')
ax.spines[['top','right']].set_visible(False)
ax.legend(loc='lower center',bbox_to_anchor=(.5,-.22),ncol=5,frameon=False)
fig.savefig(out/'figures/quality.pdf')
fig,ax=plt.subplots(figsize=(7,3.3),layout='constrained')
values=[json.loads((root/'mail-public'/k/'metrics.json').read_text())['by_k']['10']['ndcg'] for k in ['e5-cosine','e5-receipt-day-control','e5-bm25-rrf','bm25-event-aware']]
ax.barh(['E5','E5 с датой','RRF с датой','BM25 с датой'],values,color=['#9fa9b5','#7baac5','#176888','#314361'])
for y,val in enumerate(values):ax.text(val-.016,y,f'{val:.4f}',ha='right',va='center',color='white')
ax.set(xlim=(0,1.01),xlabel='nDCG@10',title='Вклад даты получения на 99 запросах SmartMail')
ax.spines[['top','right']].set_visible(False)
fig.savefig(out/'figures/date-control.pdf')
(out/'figure-catalog.md').write_text('# Графики\n\n[Качество](figures/quality.pdf) показывает среднее nDCG@10 для пяти вариантов на полном корпусе по каждому языку. По вертикали общая шкала от 0 до 1. Серии RU и EN относятся к параллельным версиям одних вопросов.\n\n[Контроль даты](figures/date-control.pdf) показывает результат добавления к E5 отдельного фильтра даты получения. На SmartMail этот шаг объясняет большую долю прироста гибрида.\n')
