import Link from "next/link";

import { fetchApi } from "../../../../lib/api/client";
import { formatCount } from "../../../../lib/format/number";
import { safeRouteSegment } from "../../../../lib/url/search";
import type { CatalogWorkPage, TagDetail } from "../../../../types/api";

export const dynamic = "force-dynamic";

export default async function TagDetailPage({ params }: { params: Promise<{ tagName: string }> }) {
  const tagName = safeRouteSegment((await params).tagName);
  let tag: TagDetail | null = null;
  let works: CatalogWorkPage | null = null;
  if (tagName) {
    try {
      [tag, works] = await Promise.all([
        fetchApi<TagDetail>(`/api/v1/tags/${encodeURIComponent(tagName)}`),
        fetchApi<CatalogWorkPage>(`/api/v1/works?limit=20&tag=${encodeURIComponent(tagName)}`),
      ]);
    } catch {
      // Fixed not-found/unavailable state below.
    }
  }
  if (!tag) return <main className="catalog-page"><section className="state-panel"><p>标签不存在或只读 API 暂不可用。</p></section></main>;
  return (
    <main className="catalog-page">
      <header className="detail-heading"><p className="eyebrow">Tag detail</p><h1>#{tag.tag_name}</h1><span>{tag.tag_translation ?? "暂无公开翻译"} · {formatCount(tag.work_count)} 件作品</span></header>
      <section className="directory-list">
        {works?.items.map((work) => <Link className="directory-row" href={`/works/${encodeURIComponent(work.work_id)}`} key={work.work_id}><span><strong>{work.work_title}</strong><small>{work.author_display_name}</small></span><span>{formatCount(work.public_like_count ?? 0)} 赞</span></Link>)}
      </section>
    </main>
  );
}
