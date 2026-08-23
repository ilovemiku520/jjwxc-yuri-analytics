import Link from "next/link";

import { NextPageLink } from "../../../components/ui/next-page-link";
import { fetchApi } from "../../../lib/api/client";
import { formatCount } from "../../../lib/format/number";
import { firstSearchValue, pageHref, type RawSearchParams } from "../../../lib/url/search";
import type { TagAggregatePage } from "../../../types/api";

export const dynamic = "force-dynamic";

export default async function TagsPage({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
  const raw = await searchParams;
  const cursor = firstSearchValue(raw.cursor, 1_024);
  const query = new URLSearchParams({ limit: "50" });
  if (cursor) query.set("cursor", cursor);
  let page: TagAggregatePage | null = null;
  try {
    page = await fetchApi<TagAggregatePage>(`/api/v1/analytics/tags?${query}`);
  } catch {
    // Fixed private-service failure state below.
  }

  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Tag index</p><h1>标签索引</h1></div>
        <p>事实标签与公开翻译，不包含模型推断。</p>
      </header>
      {page ? (
        <>
          <section className="tag-directory" aria-label="标签列表">
            {page.items.map((tag) => (
              <Link className="tag-directory-card" href={`/tags/${encodeURIComponent(tag.tag_name)}`} key={tag.tag_name}>
                <strong>#{tag.tag_name}</strong>
                <span>{tag.tag_translation ?? "暂无公开翻译"}</span>
                <small>{formatCount(tag.work_count)} 件作品</small>
              </Link>
            ))}
          </section>
          <div className="pagination">
            <NextPageLink href={page.next_cursor ? pageHref("/tags", { cursor: page.next_cursor }) : null} />
          </div>
        </>
      ) : <section className="state-panel"><p>标签 API 暂不可用。</p></section>}
    </main>
  );
}
