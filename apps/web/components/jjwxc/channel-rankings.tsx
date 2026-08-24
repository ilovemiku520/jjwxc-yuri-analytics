"use client";

import Link from "next/link";
import { useState } from "react";

import type { JjwxcChannelRankingResponse } from "../../types/api";

export function ChannelRankings({
  channelGold,
  newcomer,
}: {
  channelGold: JjwxcChannelRankingResponse;
  newcomer: JjwxcChannelRankingResponse;
}) {
  const [selected, setSelected] = useState<"channel_gold" | "newcomer">(
    "channel_gold",
  );
  const active = selected === "channel_gold" ? channelGold : newcomer;

  return (
    <section className="channel-ranking-panel" aria-label="晋江百合频道榜单">
      <div className="channel-ranking-heading">
        <div>
          <p className="eyebrow">Official channel discovery</p>
          <h2>百合频道双榜</h2>
        </div>
        <div className="ranking-tabs" role="tablist" aria-label="选择榜单">
          {[channelGold, newcomer].map((ranking) => (
            <button
              aria-selected={selected === ranking.ranking_key}
              key={ranking.ranking_key}
              onClick={() => setSelected(ranking.ranking_key)}
              role="tab"
              type="button"
            >
              {ranking.label}
            </button>
          ))}
        </div>
      </div>
      <div className="ranking-context">
        <span>{active.observation_day ?? "等待首次采集"}</span>
        <span>{active.items.length} 部入榜作品</span>
      </div>
      {active.items.length ? (
        <ol className="channel-ranking-list">
          {active.items.map((item) => (
            <li key={`${active.ranking_key}-${item.novel_id}`}>
              <span className="channel-rank-number">
                {String(item.rank).padStart(2, "0")}
              </span>
              <span>
                <Link href={`/novels/${item.novel_id}`}>{item.title}</Link>
                <small>{item.author_display_name ?? "作者信息补全中"}</small>
              </span>
              <span className="ranking-source">JJWXC</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="chart-empty">首次频道采集完成后显示榜单。</p>
      )}
    </section>
  );
}
