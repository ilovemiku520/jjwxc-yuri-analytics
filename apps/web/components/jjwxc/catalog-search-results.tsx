import Link from "next/link";

import { formatCount } from "../../lib/format/number";
import type { JjwxcCatalogSearchItem } from "../../types/api";

export function CatalogSearchResults({
  items,
}: {
  items: JjwxcCatalogSearchItem[];
}) {
  if (!items.length) {
    return <p className="chart-empty">当前索引中没有匹配作品；分页扫描仍会持续扩大覆盖。</p>;
  }
  return (
    <section className="catalog-index-grid" aria-live="polite" aria-label="全站百合作品索引结果">
      {items.map((item) => (
        <article className="catalog-index-card" key={item.novel_id}>
          <div className="novel-card-header">
            <span>{item.status}</span>
            <small>JJWXC {item.novel_id}</small>
          </div>
          <h2>
            {item.detail_available ? (
              <Link href={`/novels/${item.novel_id}`}>{item.title}</Link>
            ) : (
              <a
                href={`https://www.jjwxc.net/onebook.php?novelid=${item.novel_id}`}
                rel="noreferrer"
                target="_blank"
              >
                {item.title}
              </a>
            )}
          </h2>
          <p className="catalog-index-author">{item.author_display_name}</p>
          <p className="novel-type">{item.novel_type}</p>
          <dl className="catalog-index-metrics">
            <div>
              <dt>字数</dt>
              <dd>{formatCount(item.word_count)}</dd>
            </div>
            <div>
              <dt>作品积分</dt>
              <dd>{formatCount(item.points)}</dd>
            </div>
            <div>
              <dt>详细分析</dt>
              <dd>{item.detail_available ? "已就绪" : "排队补全"}</dd>
            </div>
          </dl>
        </article>
      ))}
    </section>
  );
}
