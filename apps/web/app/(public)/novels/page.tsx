import { NovelExplorer } from "../../../components/jjwxc/novel-explorer";
import { fetchApi } from "../../../lib/api/client";
import type { JjwxcNovelPage } from "../../../types/api";

export const dynamic = "force-dynamic";

export default async function NovelsPage() {
  let page: JjwxcNovelPage | null = null;
  try { page = await fetchApi<JjwxcNovelPage>("/api/v1/jjwxc/novels?sort=favorites&limit=200"); } catch {}
  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Interactive novel explorer</p><h1>百合小说分析</h1></div>
        <p>在浏览器内即时组合检索、进度与排序；不会触发外部采集。</p>
      </header>
      {page ? <NovelExplorer novels={page.items} /> : <section className="state-panel"><p>分析数据服务暂不可用。</p></section>}
    </main>
  );
}
