"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { formatCount } from "../../lib/format/number";
import type {
  JjwxcNovel,
  JjwxcNovelSort,
  JjwxcNovelStatus,
} from "../../types/api";

const sortLabels: Record<JjwxcNovelSort, string> = {
  favorites: "收藏",
  reviews: "书评",
  points: "积分",
  words: "字数",
  clicks: "章均点击",
};

function sortValue(novel: JjwxcNovel, sort: JjwxcNovelSort) {
  if (sort === "favorites") return novel.favorite_count;
  if (sort === "reviews") return novel.review_count;
  if (sort === "points") return novel.points;
  if (sort === "words") return novel.word_count;
  return novel.average_non_v_chapter_click_count;
}

export function NovelExplorer({ novels }: { novels: JjwxcNovel[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<JjwxcNovelStatus | "全部">("全部");
  const [sort, setSort] = useState<JjwxcNovelSort>("favorites");
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("zh-CN");
    return novels
      .filter((item) => status === "全部" || item.status === status)
      .filter(
        (item) =>
          !needle ||
          `${item.title} ${item.author_display_name} ${item.tags.join(" ")}`
            .toLocaleLowerCase("zh-CN")
            .includes(needle),
      )
      .toSorted(
        (left, right) =>
          (sortValue(right, sort) ?? -1) - (sortValue(left, sort) ?? -1) ||
          left.novel_id.localeCompare(right.novel_id),
      );
  }, [novels, query, sort, status]);

  return (
    <>
      <section className="explorer-controls" aria-label="小说筛选与排序">
        <label>
          结果内筛选
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="继续按标签或状态缩小结果"
            maxLength={100}
          />
        </label>
        <label>
          进度
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as JjwxcNovelStatus | "全部")
            }
          >
            <option>全部</option>
            <option>连载</option>
            <option>完结</option>
            <option>暂停</option>
          </select>
        </label>
        <div className="sort-buttons" role="group" aria-label="排序指标">
          {(Object.keys(sortLabels) as JjwxcNovelSort[]).map((item) => (
            <button
              aria-pressed={sort === item}
              key={item}
              onClick={() => setSort(item)}
              type="button"
            >
              {sortLabels[item]}
            </button>
          ))}
        </div>
        <span className="explorer-count">{visible.length} 部</span>
      </section>
      <section
        className="novel-grid"
        aria-live="polite"
        aria-label="百合小说分析列表"
      >
        {visible.map((novel) => (
          <article className="novel-card" key={novel.novel_id}>
            <div className="novel-card-header">
              <span>{novel.status}</span>
              <small>JJWXC {novel.novel_id}</small>
            </div>
            <h2>
              <Link href={`/novels/${novel.novel_id}`}>{novel.title}</Link>
            </h2>
            <Link className="muted-link" href={`/authors/${novel.author_id}`}>
              {novel.author_display_name}
            </Link>
            <p className="novel-type">
              {novel.novel_type} · {novel.perspective ?? "视角未观测"}
            </p>
            <dl className="metric-strip metric-strip-expanded">
              <div>
                <dt>收藏</dt>
                <dd>{formatCount(novel.favorite_count)}</dd>
              </div>
              <div>
                <dt>书评</dt>
                <dd>{formatCount(novel.review_count)}</dd>
              </div>
              <div>
                <dt>字数</dt>
                <dd>{formatCount(novel.word_count)}</dd>
              </div>
              <div>
                <dt>非 V 章均点击</dt>
                <dd>
                  {novel.average_non_v_chapter_click_count === null
                    ? "未公开"
                    : formatCount(novel.average_non_v_chapter_click_count)}
                </dd>
              </div>
              <div>
                <dt>V 章均点击</dt>
                <dd>
                  {novel.average_v_chapter_click_count === null
                    ? "需作者授权"
                    : formatCount(novel.average_v_chapter_click_count)}
                </dd>
              </div>
              <div>
                <dt>V/非 V 留存比（代理）</dt>
                <dd>
                  {novel.v_to_non_v_click_retention_basis_points === null
                    ? "缺少作者授权 V 点击"
                    : `${(
                        novel.v_to_non_v_click_retention_basis_points / 100
                      ).toFixed(1)}%`}
                </dd>
              </div>
              <div>
                <dt>可见点击覆盖</dt>
                <dd>
                  {novel.chapter_click_coverage_count}/
                  {novel.non_v_chapter_count + novel.v_chapter_count || "—"}
                </dd>
              </div>
            </dl>
            {novel.synopsis_char_count !== null ? (
              <div className="synopsis-profile">
                <span>文案画像</span>
                <p>
                  {novel.synopsis_char_count} 字 · {novel.synopsis_sentence_count ?? "—"} 句
                  {novel.synopsis_theme_terms.length
                    ? ` · ${novel.synopsis_theme_terms.join(" / ")}`
                    : " · 暂无主题词命中"}
                </p>
              </div>
            ) : null}
            <div className="tag-row">
              {novel.tags.map((tag) => (
                <span key={tag}>#{tag}</span>
              ))}
            </div>
          </article>
        ))}
      </section>
      {visible.length === 0 ? (
        <p className="chart-empty">没有符合当前条件的小说。</p>
      ) : null}
    </>
  );
}
