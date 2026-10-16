import csv,sys,statistics,os
SP=os.path.dirname(os.path.abspath(__file__))
def fmt(s): return f"{int(s//60)}:{int(s%60):02d}"
for v in sys.argv[1:]:
    for pk in ('greedy','random'):
        for cell in ('nov1','gen3'):
            rows=list(csv.DictReader(open(f"{SP}/{v}-{pk}-{cell}/runs.csv")))
            n=len(rows); won=sum(r['won']=='1' for r in rows)
            fe=[float(r['first_evolution']) for r in rows if r['first_evolution']] or [1e9]
            med=statistics.median(fe)
            alive6=[r for r in rows if float(r['secs'])>=360 or r['won']=='1']
            ev6=sum(1 for r in alive6 if r['first_evolution'] and float(r['first_evolution'])<=360)
            print(f"{v} | {pk} | {cell} | {100*won//n}% | {fmt(med) if med<1e8 else '—'} | {100*ev6//max(1,len(alive6))}%")
