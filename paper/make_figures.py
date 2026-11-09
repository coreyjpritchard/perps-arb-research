"""Builds the extra figures for the paper from ../results CSVs only."""
import pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np
R="../results/"
plt.rcParams.update({"font.size":9,"font.family":"serif"})
# Fig 3: quarterly mean spread (8-coin average)
q=pd.read_csv(R+"bt_funding_by_quarter.csv")
g=q.groupby("quarter")[["HL_ann","BIN_ann","BYB_ann"]].mean()*100
x=np.arange(len(g)); w=0.38
fig,ax=plt.subplots(figsize=(6.2,2.9))
ax.bar(x-w/2,g.HL_ann-g.BIN_ann,w,label="HL − Binance",color="#1f4e79")
ax.bar(x+w/2,g.HL_ann-g.BYB_ann,w,label="HL − Bybit",color="#9dc3e6")
for i,v in enumerate(g.HL_ann-g.BIN_ann): ax.text(i-w/2,v+0.3,f"{v:.1f}",ha="center",fontsize=7)
ax.axvspan(6.5,8.5,color="grey",alpha=0.12); ax.text(7.5,17.5,"OOS window\n(2026Q3–Q4)",ha="center",fontsize=7)
ax.set_xticks(x); ax.set_xticklabels(g.index); ax.set_ylabel("Funding spread, %/yr")
ax.axhline(0,color="k",lw=0.6); ax.legend(frameon=False); ax.spines[["top","right"]].set_visible(False)
fig.tight_layout(); fig.savefig("figures/quarterly_spread.png",dpi=200)
# Fig 4: cost breakdown
s=pd.read_csv(R+"bt_summary.csv"); s=s[s.period!="FULL"]
lab={"a":"(a) spread","b":"(b) carry","c":"(c) perp/perp","c2":"ref: spot"}
s["name"]=s.strategy.map(lab)+"\n"+s.period
cols=[("ann_fund","Gross funding","#2e7d32"),("ann_basis","Basis/price drift","#a5d6a7"),
      ("ann_fee","Fees","#c62828"),("ann_slip","Slippage","#ef9a9a"),("ann_leg","Leg risk","#ffcc80")]
fig,ax=plt.subplots(figsize=(6.2,3.1)); xs=np.arange(len(s))
pos=np.zeros(len(s)); neg=np.zeros(len(s))
for c,l,col in cols:
    v=s[c].values*100
    b=np.where(v>=0,pos,neg); ax.bar(xs,v,0.6,bottom=b,label=l,color=col)
    pos+=np.where(v>=0,v,0); neg+=np.where(v<0,v,0)
ax.scatter(xs,s.ann_net*100,color="k",marker="D",s=14,zorder=5,label="Net")
ax.set_xticks(xs); ax.set_xticklabels(s.name,fontsize=7); ax.set_ylabel("% of capital per year")
ax.axhline(0,color="k",lw=0.6); ax.axhline(4.5,color="grey",ls="--",lw=0.8); ax.text(1.0,4.65,"4.5% hurdle",ha="center",fontsize=7,color="grey")
ax.legend(frameon=False,fontsize=7,ncol=3,loc="upper left"); ax.set_ylim(-2,8.5); ax.spines[["top","right"]].set_visible(False)
fig.tight_layout(); fig.savefig("figures/cost_breakdown.png",dpi=200)
print("ok")
