import { createServer } from "node:http";

const observedAt = "2026-08-23T00:00:00Z";
const jjwxcNovels = [
  {
    novel_id: "90000001",
    title: "向晚潮声",
    author_id: "700001",
    author_display_name: "南汀",
    novel_type: "原创-百合-近代现代-爱情",
    perspective: "互攻",
    status: "连载",
    word_count: 182400,
    review_count: 1260,
    favorite_count: 18400,
    nutrition_count: 9200,
    points: 164800000,
    first_chapter_click_count: 36800,
    average_non_v_chapter_click_count: 18200,
    average_v_chapter_click_count: 9600,
    non_v_chapter_count: 18,
    v_chapter_count: 12,
    chapter_click_coverage_count: 30,
    v_to_non_v_click_retention_basis_points: 5275,
    nutrition_to_favorite_basis_points: 5000,
    first_click_to_favorite_basis_points: 20000,
    synopsis_char_count: 132,
    synopsis_sentence_count: 6,
    synopsis_theme_terms: ["都市", "成长"],
    tags: ["都市", "成长"],
    observed_at: observedAt,
    source_mode: "synthetic_fixture",
  },
  {
    novel_id: "90000002",
    title: "她从长夜来",
    author_id: "700002",
    author_display_name: "折春枝",
    novel_type: "原创-百合-架空历史-爱情",
    perspective: "主受",
    status: "完结",
    word_count: 468200,
    review_count: 3180,
    favorite_count: 32600,
    nutrition_count: 16300,
    points: 386500000,
    first_chapter_click_count: 32600,
    average_non_v_chapter_click_count: null,
    average_v_chapter_click_count: null,
    non_v_chapter_count: 20,
    v_chapter_count: 0,
    chapter_click_coverage_count: 0,
    v_to_non_v_click_retention_basis_points: null,
    nutrition_to_favorite_basis_points: 5000,
    first_click_to_favorite_basis_points: 10000,
    synopsis_char_count: 168,
    synopsis_sentence_count: 7,
    synopsis_theme_terms: ["救赎", "历史"],
    tags: ["强强", "救赎"],
    observed_at: observedAt,
    source_mode: "synthetic_fixture",
  },
];
const jjwxcAuthors = [
  {
    author_id: "700002",
    author_display_name: "折春枝",
    novel_count: 1,
    total_word_count: 468200,
    total_review_count: 3180,
    total_favorite_count: 32600,
    total_points: 386500000,
    ranking_appearance_count: 2,
    ranking_observed_day_count: 2,
  },
  {
    author_id: "700001",
    author_display_name: "南汀",
    novel_count: 1,
    total_word_count: 182400,
    total_review_count: 1260,
    total_favorite_count: 18400,
    total_points: 164800000,
    ranking_appearance_count: 3,
    ranking_observed_day_count: 2,
  },
];
const jjwxcMetrics = [
  "reviews",
  "favorites",
  "nutrition",
  "first_clicks",
  "loyalty",
  "click_favorite",
  "points",
  "words",
  "clicks",
  "v_clicks",
  "v_retention",
  "synopsis_chars",
];
const jjwxcMatrixMetrics = jjwxcMetrics.filter(
  (metric) => metric !== "v_clicks",
);
const jjwxcTimeline = [
  {
    day: "2026-08-22",
    observed_novel_count: 2,
    total_review_count: 4300,
    total_favorite_count: 50000,
    total_points: 540000000,
    total_word_count: 642000,
    click_coverage_count: 1,
    mean_non_v_chapter_click_count: 17900,
    v_click_coverage_count: 1,
    mean_v_chapter_click_count: 9400,
  },
  {
    day: "2026-08-23",
    observed_novel_count: 2,
    total_review_count: 4440,
    total_favorite_count: 51000,
    total_points: 551300000,
    total_word_count: 650600,
    click_coverage_count: 1,
    mean_non_v_chapter_click_count: 18200,
    v_click_coverage_count: 1,
    mean_v_chapter_click_count: 9600,
  },
];
const jjwxcNormalizedTimeline = [
  {
    day: "2026-08-22",
    values: {
      reviews: 10000,
      favorites: 10000,
      points: 10000,
      words: 10000,
      clicks: 10000,
      v_clicks: 10000,
    },
  },
  {
    day: "2026-08-23",
    values: {
      reviews: 10326,
      favorites: 10200,
      points: 10209,
      words: 10134,
      clicks: 10168,
      v_clicks: 10213,
    },
  },
];
const jjwxcSummaries = jjwxcMetrics.map((metric) => ({
  metric,
  label: {
    reviews: "总书评数",
    favorites: "当前被收藏数",
    nutrition: "营养液数",
    first_clicks: "首章点击数",
    loyalty: "营养液/收藏投入比（代理）",
    click_favorite: "首章点击/收藏转化比（代理）",
    points: "文章积分",
    words: "全文字数",
    clicks: "非 V 章节章均点击数",
    v_clicks: "V 章节章均点击数",
    v_retention: "V/非 V 点击留存比（代理）",
    synopsis_chars: "文案字符数",
  }[metric],
  observed_count:
    metric === "clicks" || metric === "v_clicks" || metric === "v_retention"
      ? 1
      : 2,
  missing_count:
    metric === "clicks" || metric === "v_clicks" || metric === "v_retention"
      ? 1
      : 0,
  coverage_basis_points:
    metric === "clicks" || metric === "v_clicks" || metric === "v_retention"
      ? 5000
      : 10000,
  minimum: 100,
  maximum: 200,
  mean: 150,
  median: 150,
  standard_deviation: 50,
  p25: 125,
  p75: 175,
  coefficient_of_variation: 0.333,
}));
const jjwxcCorrelationMatrix = jjwxcMatrixMetrics.flatMap((yMetric) =>
  jjwxcMatrixMetrics.map((xMetric) => ({
    x_metric: xMetric,
    y_metric: yMetric,
    paired_count:
      ["clicks", "v_retention"].includes(xMetric) ||
      ["clicks", "v_retention"].includes(yMetric)
        ? 1
        : 2,
    coefficient:
      ["clicks", "v_retention"].includes(xMetric) ||
      ["clicks", "v_retention"].includes(yMetric)
        ? null
        : 1,
  })),
);
const work = {
  work_id: "synthetic-work-1001",
  work_title: "Synthetic Work Alpha",
  author_id: "synthetic-author-501",
  author_display_name: "Synthetic Author",
  created_at: "2026-08-20T00:00:00Z",
  page_count: 4,
  width: 1200,
  height: 1600,
  public_view_count: 1200,
  public_bookmark_count: 180,
  public_like_count: 240,
  public_tags: [
    { tag_name: "synthetic-tag-a", tag_translation: "Synthetic Tag A" },
  ],
};
const secondWork = {
  ...work,
  work_id: "synthetic-work-1002",
  work_title: "Synthetic Work Beta",
  page_count: 1,
  public_view_count: 800,
  public_bookmark_count: 90,
  public_like_count: 120,
};

function payloadFor(url) {
  const path = url.pathname;
  if (path === "/health/live") return { status: "alive" };
  if (path === "/api/v1/jjwxc/overview")
    return {
      data_mode: "synthetic_fixture",
      novel_count: 2,
      author_count: 2,
      total_word_count: 650600,
      total_review_count: 4440,
      total_favorite_count: 51000,
      click_coverage_count: 1,
      synopsis_feature_coverage_count: 2,
      latest_observed_at: observedAt,
    };
  if (path === "/api/v1/jjwxc/trends")
    return { data_mode: "synthetic_fixture", items: jjwxcTimeline };
  if (path === "/api/v1/jjwxc/analytics/multivariate") {
    const selectedIds = (url.searchParams.get("novel_ids") ?? "")
      .split(",")
      .filter(Boolean);
    const cohortItems = selectedIds.length
      ? jjwxcNovels.filter((item) => selectedIds.includes(item.novel_id))
      : jjwxcNovels;
    return {
      data_mode: "synthetic_fixture",
      history_source: "project_snapshot_fixture",
      interpretation: "descriptive_association_only",
      click_definition: "average_non_v_chapter_click_count",
      v_click_definition: "average_v_chapter_click_count",
      v_retention_definition:
        "average_v_chapter_click_count / average_non_v_chapter_click_count",
      correlation_method: "pearson_log1p_zscore_pairwise_complete",
      available_days: ["2026-08-22", "2026-08-23"],
      selected_novel_ids: selectedIds,
      cohort_items: cohortItems,
      timeline: jjwxcTimeline,
      normalized_timeline: jjwxcNormalizedTimeline,
      summaries: jjwxcSummaries,
      correlation_matrix: jjwxcCorrelationMatrix,
      research_indicators: {
        cohort_count: cohortItems.length,
        nutrition_observed_count: cohortItems.length,
        nutrition_coverage_basis_points: 10000,
        loyalty_ratio: 0.5,
        click_favorite_observed_count: cohortItems.length,
        median_click_favorite_ratio: 1.5,
        serial_nutrition_observed_count: 1,
        serial_nutrition_mean: 9200,
        completed_nutrition_observed_count: 1,
        completed_nutrition_mean: 16300,
        completed_to_serial_nutrition_ratio: 1.7717,
      },
    };
  }
  if (path === "/api/v1/jjwxc/analytics/ratings")
    return {
      data_mode: "synthetic_fixture",
      model_version: "jjwxc-public-performance-v1",
      interpretation: "cohort_relative_public_data_performance",
      selected_day: "2026-08-23",
      available_days: ["2026-08-23"],
      default_weights: {
        reviews: 2700,
        favorites: 2900,
        points: 2100,
        words: 1100,
        clicks: 1200,
      },
      author_default_weights: {
        nonlocked_works: 1000,
        author_favorites: 2500,
        work_favorites: 2500,
        words: 1500,
        points: 2500,
      },
      effective_weights: {
        reviews: 2700,
        favorites: 2900,
        points: 2100,
        words: 1100,
        clicks: 1200,
      },
      novels: [
        {
          entity_id: "90000002",
          title: "她从长夜来",
          author_display_name: "折春枝",
          score_basis_points: 10000,
          grade: "SSS",
          coverage_basis_points: 8000,
          component_scores: {
            nonlocked_works: 10000,
            author_favorites: 10000,
            work_favorites: 10000,
            points: 10000,
            words: 10000,
          },
          raw_values: {
            nonlocked_works: 8,
            author_favorites: 36000,
            work_favorites: 32600,
            points: 386500000,
            words: 468200,
          },
        },
        {
          entity_id: "90000001",
          title: "向晚潮声",
          author_display_name: "南汀",
          score_basis_points: 1200,
          grade: "B",
          coverage_basis_points: 10000,
          component_scores: {
            nonlocked_works: 0,
            author_favorites: 0,
            work_favorites: 0,
            points: 0,
            words: 0,
          },
          raw_values: {
            nonlocked_works: 2,
            author_favorites: 1200,
            work_favorites: 18400,
            points: 164800000,
            words: 182400,
          },
        },
      ],
      authors: [
        {
          entity_id: "700002",
          title: "折春枝",
          author_display_name: "折春枝",
          score_basis_points: 10000,
          grade: "SSS",
          coverage_basis_points: 8000,
          component_scores: {
            reviews: 10000,
            favorites: 10000,
            points: 10000,
            words: 10000,
            clicks: null,
          },
        },
        {
          entity_id: "700001",
          title: "南汀",
          author_display_name: "南汀",
          score_basis_points: 1200,
          grade: "B",
          coverage_basis_points: 10000,
          component_scores: {
            reviews: 0,
            favorites: 0,
            points: 0,
            words: 0,
            clicks: 10000,
          },
        },
      ],
    };
  if (path === "/api/v1/jjwxc/novels")
    return {
      data_mode: "synthetic_fixture",
      sort: url.searchParams.get("sort") ?? "favorites",
      items: jjwxcNovels,
      total: jjwxcNovels.length,
    };
  if (path === "/api/v1/jjwxc/search") {
    const query = (url.searchParams.get("query") ?? "").toLowerCase();
    const items = jjwxcNovels.filter(
      (item) =>
        item.title.toLowerCase().includes(query) ||
        item.author_display_name.toLowerCase().includes(query),
    );
    return {
      data_mode: "synthetic_fixture",
      query,
      match_fields: ["title", "author_display_name"],
      items,
      total: items.length,
      limit: 20,
      offset: 0,
    };
  }
  if (path === "/api/v1/jjwxc/catalog-search") {
    const query = (url.searchParams.get("query") ?? "").toLowerCase();
    const items = jjwxcNovels
      .filter(
        (item) =>
          item.title.toLowerCase().includes(query) ||
          item.author_display_name.toLowerCase().includes(query),
      )
      .map((item) => ({
        novel_id: item.novel_id,
        title: item.title,
        author_id: item.author_id,
        author_display_name: item.author_display_name,
        novel_type: item.novel_type,
        status: item.status,
        word_count: item.word_count,
        points: item.points,
        published_at: null,
        last_seen_at: item.observed_at,
        detail_available: true,
      }));
    return {
      data_mode: "synthetic_fixture",
      query,
      coverage: "progressive_official_bookbase_index",
      match_fields: ["title", "author_display_name"],
      items,
      total: items.length,
      limit: 100,
      offset: 0,
    };
  }
  if (path === "/api/v1/jjwxc/channel-rankings") {
    const key = url.searchParams.get("ranking_key") ?? "channel_gold";
    return {
      ranking_key: key,
      label: key === "newcomer" ? "新手金榜" : "频道金榜",
      observation_day: "2026-08-23",
      items: [],
    };
  }
  if (path.startsWith("/api/v1/jjwxc/novels/"))
    return jjwxcNovels.find((item) => path.endsWith(item.novel_id));
  if (path === "/api/v1/jjwxc/authors")
    return {
      data_mode: "synthetic_fixture",
      sort: url.searchParams.get("sort") ?? "favorites",
      items: jjwxcAuthors,
    };
  if (path.startsWith("/api/v1/jjwxc/authors/")) {
    const author = jjwxcAuthors.find((item) => path.endsWith(item.author_id));
    return author
      ? {
          author,
          novels: jjwxcNovels.filter(
            (item) => item.author_id === author.author_id,
          ),
        }
      : undefined;
  }
  if (path === "/api/v1/analytics/freshness") {
    return {
      latest_observed_at: observedAt,
      author_count: 1,
      work_count: 2,
      tag_count: 1,
      metric_snapshot_count: 2,
    };
  }
  if (path === "/api/v1/rankings/works") {
    return {
      metric: "likes",
      items: [
        {
          work_id: work.work_id,
          work_title: work.work_title,
          author_id: work.author_id,
          author_display_name: work.author_display_name,
          score: 240,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/analytics/metric-trends") {
    return {
      date_from: url.searchParams.get("date_from"),
      date_to: url.searchParams.get("date_to"),
      items: [
        {
          day: "2026-08-23",
          observed_work_count: 2,
          total_public_view_count: 2000,
          total_public_bookmark_count: 270,
          total_public_like_count: 360,
        },
      ],
    };
  }
  if (path === "/api/v1/rankings/authors") {
    const metric = url.searchParams.get("metric") ?? "likes";
    const scores = {
      likes: 360,
      bookmarks: 270,
      views: 2000,
      works: 2,
      average_likes: 18000,
      average_bookmarks: 13500,
    };
    const scoreScale = metric.startsWith("average_") ? 100 : 1;
    return {
      metric,
      items: [
        {
          author_id: work.author_id,
          author_display_name: work.author_display_name,
          work_count: 2,
          metric_coverage_count: 2,
          score: scores[metric] ?? 0,
          score_scale: scoreScale,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/works") {
    if (url.searchParams.get("q") === "force-unavailable") return null;
    const q = url.searchParams.get("q")?.toLowerCase();
    const items = [work, secondWork].filter(
      (item) => !q || item.work_title.toLowerCase().includes(q),
    );
    return { items, next_cursor: null };
  }
  if (
    path === `/api/v1/works/${work.work_id}` ||
    path === `/api/v1/works/${secondWork.work_id}`
  ) {
    return path.endsWith(secondWork.work_id) ? secondWork : work;
  }
  if (path.endsWith("/metric-history")) {
    return {
      work_id: path.split("/")[4],
      items: [
        {
          observed_at: observedAt,
          public_view_count: 1200,
          public_bookmark_count: 180,
          public_like_count: 240,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/analytics/authors") {
    return {
      items: [
        {
          author_id: work.author_id,
          author_display_name: work.author_display_name,
          work_count: 2,
          total_public_view_count: 2000,
          total_public_bookmark_count: 270,
          total_public_like_count: 360,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/analytics/authors/quality-map") {
    return {
      sampled_author_count: 1,
      sample_truncated: false,
      work_count_threshold_x100: 200,
      average_bookmark_threshold_x100: 13500,
      items: [
        {
          author_id: work.author_id,
          author_display_name: work.author_display_name,
          work_count: 2,
          bookmark_coverage_count: 2,
          average_public_bookmark_count_x100: 13500,
          like_coverage_count: 2,
          total_public_like_count: 360,
          quadrant: "core",
        },
      ],
    };
  }
  if (path === "/api/v1/analytics/authors/influence-ranking") {
    const bookmarkWeight = Number(
      url.searchParams.get("bookmark_weight") ?? 4375,
    );
    const likeWeight = Number(url.searchParams.get("like_weight") ?? 3750);
    const productionWeight = Number(
      url.searchParams.get("production_weight") ?? 1875,
    );
    return {
      model_version: "allowed-metadata-v1",
      weights: {
        bookmark: bookmarkWeight,
        like: likeWeight,
        production: productionWeight,
      },
      sampled_author_count: 1,
      sample_truncated: false,
      items: [
        {
          author_id: work.author_id,
          author_display_name: work.author_display_name,
          work_count: 2,
          complete_metric_work_count: 2,
          average_public_bookmark_count_x100: 13500,
          average_public_like_count_x100: 18000,
          bookmark_component_basis_points: 10000,
          like_component_basis_points: 10000,
          production_component_basis_points: 10000,
          influence_score_basis_points: 10000,
        },
      ],
    };
  }
  if (path === `/api/v1/analytics/authors/${work.author_id}/profile`) {
    return {
      author_id: work.author_id,
      author_display_name: work.author_display_name,
      analyzed_work_count: 2,
      first_work_created_at: "2026-08-20T00:00:00Z",
      latest_work_created_at: "2026-08-21T00:00:00Z",
      total_page_count: 5,
      total_public_view_count: 2000,
      total_public_bookmark_count: 270,
      total_public_like_count: 360,
      public_bookmark_rate_basis_points: 1350,
      public_like_rate_basis_points: 1800,
      metric_coverage: {
        public_view_count: 2,
        public_bookmark_count: 2,
        public_like_count: 2,
      },
      top_public_tags: [
        {
          tag_name: "synthetic-tag-a",
          tag_translation: "Synthetic Tag A",
          work_count: 2,
          work_share_basis_points: 10000,
        },
      ],
    };
  }
  if (path === `/api/v1/analytics/authors/${work.author_id}/metric-trends`) {
    return {
      author_id: work.author_id,
      date_from: url.searchParams.get("date_from"),
      date_to: url.searchParams.get("date_to"),
      items: [
        {
          day: "2026-08-22",
          observed_work_count: 2,
          public_view_coverage_count: 2,
          public_bookmark_coverage_count: 2,
          public_like_coverage_count: 2,
          total_public_view_count: 1800,
          total_public_bookmark_count: 240,
          total_public_like_count: 320,
        },
        {
          day: "2026-08-23",
          observed_work_count: 2,
          public_view_coverage_count: 2,
          public_bookmark_coverage_count: 2,
          public_like_coverage_count: 2,
          total_public_view_count: 2000,
          total_public_bookmark_count: 270,
          total_public_like_count: 360,
        },
      ],
    };
  }
  if (path === `/api/v1/analytics/authors/${work.author_id}/growth`) {
    return {
      author_id: work.author_id,
      date_from: url.searchParams.get("date_from"),
      date_to: url.searchParams.get("date_to"),
      start_observed_work_count: 2,
      end_observed_work_count: 2,
      matched_work_count: 2,
      start_only_work_count: 0,
      end_only_work_count: 0,
      public_views: {
        complete_work_count: 2,
        start_total: 1800,
        end_total: 2000,
        absolute_change: 200,
        growth_basis_points: 1111,
      },
      public_bookmarks: {
        complete_work_count: 2,
        start_total: 240,
        end_total: 270,
        absolute_change: 30,
        growth_basis_points: 1250,
      },
      public_likes: {
        complete_work_count: 2,
        start_total: 320,
        end_total: 360,
        absolute_change: 40,
        growth_basis_points: 1250,
      },
    };
  }
  if (path === `/api/v1/authors/${work.author_id}`) {
    return {
      author_id: work.author_id,
      author_display_name: work.author_display_name,
      work_count: 2,
      total_public_view_count: 2000,
      total_public_bookmark_count: 270,
      total_public_like_count: 360,
      first_seen_at: "2026-08-20T00:00:00Z",
      last_seen_at: observedAt,
    };
  }
  if (path === "/api/v1/analytics/tags/co-occurrence") {
    const anchor = url.searchParams.get("anchor_tag");
    const allEdges = [
      {
        left: {
          tag_name: "synthetic-tag-a",
          tag_translation: "Synthetic Tag A",
          sampled_work_count: 2,
        },
        right: {
          tag_name: "synthetic-tag-b",
          tag_translation: "Synthetic Tag B",
          sampled_work_count: 2,
        },
        cooccurrence_work_count: 2,
        sample_support_basis_points: 10000,
        jaccard_basis_points: 10000,
        pmi_milli_bits: 0,
      },
      {
        left: {
          tag_name: "synthetic-tag-a",
          tag_translation: "Synthetic Tag A",
          sampled_work_count: 2,
        },
        right: {
          tag_name: "synthetic-tag-c",
          tag_translation: null,
          sampled_work_count: 1,
        },
        cooccurrence_work_count: 1,
        sample_support_basis_points: 5000,
        jaccard_basis_points: 5000,
        pmi_milli_bits: 0,
      },
    ];
    const edges = anchor
      ? allEdges.filter(
          (edge) =>
            edge.left.tag_name === anchor || edge.right.tag_name === anchor,
        )
      : allEdges;
    return {
      interpretation: "descriptive_association_only",
      semantic_classification_performed: false,
      catalog_work_count: 2,
      sampled_work_count: 2,
      sample_truncated: false,
      observed_tag_count: 3,
      eligible_edge_count: edges.length,
      result_truncated: false,
      anchor_tag: anchor,
      minimum_cooccurrence: Number(
        url.searchParams.get("minimum_cooccurrence") ?? 1,
      ),
      edges,
    };
  }
  if (path === "/api/v1/analytics/tags/association-sensitivity") {
    const anchor = url.searchParams.get("anchor_tag");
    const candidates =
      anchor === "missing"
        ? []
        : [
            {
              rank: 1,
              left_tag_name: "synthetic-tag-a",
              left_tag_translation: "Synthetic Tag A",
              right_tag_name: "synthetic-tag-b",
              right_tag_translation: "Synthetic Tag B",
              cooccurrence_work_count: 2,
              sample_support_basis_points: 10000,
              jaccard_basis_points: 10000,
              pmi_milli_bits: 0,
              survives_minimum_cooccurrence: [1, 2],
              review_state: "pending_human_review",
            },
          ];
    return {
      interpretation: "descriptive_association_only",
      semantic_classification_performed: false,
      catalog_work_count: 2,
      sampled_work_count: 2,
      sample_truncated: false,
      anchor_tag: anchor,
      thresholds: [1, 2, 3, 5, 10],
      baseline_edge_count: candidates.length,
      baseline_result_truncated: false,
      points: [
        {
          minimum_cooccurrence: 1,
          eligible_edge_count: candidates.length,
          returned_edge_count: candidates.length,
          baseline_edge_retention_basis_points: candidates.length ? 10000 : 0,
          stability_comparable: true,
        },
        {
          minimum_cooccurrence: 2,
          eligible_edge_count: candidates.length,
          returned_edge_count: candidates.length,
          baseline_edge_retention_basis_points: candidates.length ? 10000 : 0,
          stability_comparable: true,
        },
        {
          minimum_cooccurrence: 3,
          eligible_edge_count: 0,
          returned_edge_count: 0,
          baseline_edge_retention_basis_points: 0,
          stability_comparable: true,
        },
        {
          minimum_cooccurrence: 5,
          eligible_edge_count: 0,
          returned_edge_count: 0,
          baseline_edge_retention_basis_points: 0,
          stability_comparable: true,
        },
        {
          minimum_cooccurrence: 10,
          eligible_edge_count: 0,
          returned_edge_count: 0,
          baseline_edge_retention_basis_points: 0,
          stability_comparable: true,
        },
      ],
      review_candidates: candidates,
    };
  }
  if (path === "/api/v1/analytics/tags") {
    return {
      items: [
        {
          tag_name: "synthetic-tag-a",
          tag_translation: "Synthetic Tag A",
          work_count: 2,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/tags/synthetic-tag-a") {
    return {
      tag_name: "synthetic-tag-a",
      tag_translation: "Synthetic Tag A",
      work_count: 2,
    };
  }
  if (path === "/api/v1/schema-definitions") {
    return {
      items: [
        {
          id: 1,
          entity_type: "work",
          fingerprint: "a".repeat(64),
          sample_count: 2,
          status: "approved",
          compatible_parser_min: "0.1.0",
          compatible_parser_max: "0.1.0",
          first_seen_at: "2026-08-20T00:00:00Z",
          last_seen_at: observedAt,
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/operations/runs") {
    return {
      items: [
        {
          id: 1,
          run_type: "offline_fixture_ingest",
          provider: "synthetic_fixture",
          status: "completed",
          task_count: 3,
          succeeded_task_count: 3,
          failed_task_count: 0,
          started_at: "2026-08-23T00:00:00Z",
          finished_at: "2026-08-23T00:00:01Z",
          created_at: "2026-08-23T00:00:00Z",
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/operations/tasks") {
    return {
      items: [
        {
          id: 1,
          run_id: 1,
          task_type: "fixture_fetch",
          status: "succeeded",
          priority: 0,
          attempt_count: 1,
          last_error_code: null,
          available_at: "2026-08-23T00:00:00Z",
          updated_at: "2026-08-23T00:00:01Z",
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/operations/quarantine") {
    return {
      items: [
        {
          id: 1,
          entity_type: "work",
          error_code: "schema_drift",
          status: "open",
          first_failed_at: "2026-08-23T00:00:00Z",
          last_failed_at: "2026-08-23T00:00:01Z",
        },
      ],
      next_cursor: null,
    };
  }
  if (path === "/api/v1/operations/security-status") {
    return {
      shared_rate_limit_backend: "postgres",
      durable_access_audit_sink: "postgres",
      identity_adapter_configured: false,
      external_publication_approved: false,
      rate_limit_window_count: 1,
      audit_event_count: 12,
      oldest_audit_at: "2026-08-22T00:00:00Z",
      latest_audit_at: "2026-08-23T00:00:00Z",
      audit_retention_days: 30,
    };
  }
  return undefined;
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1:8000");
  if (
    request.method === "POST" &&
    url.pathname === "/api/v1/jjwxc/analytics/cohorts/import"
  ) {
    let body = "";
    for await (const chunk of request) body += chunk;
    const payload = JSON.parse(body);
    const items = payload.novel_ids.map((novelId) => ({
      novel_id: novelId,
      status: jjwxcNovels.some((novel) => novel.novel_id === novelId)
        ? "ready"
        : "failed",
      error_code: jjwxcNovels.some((novel) => novel.novel_id === novelId)
        ? null
        : "collection_failed",
    }));
    response.writeHead(200, {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    });
    response.end(
      JSON.stringify({
        accepted_count: items.length,
        ready_count: items.filter((item) => item.status === "ready").length,
        minimum_analysis_sample: 30,
        items,
      }),
    );
    return;
  }
  if (request.method !== "GET") {
    response.writeHead(405, {
      "Content-Type": "application/json",
      Allow: "GET",
    });
    response.end('{"detail":"method_not_allowed"}');
    return;
  }
  const payload = payloadFor(url);
  const status = payload === undefined ? 404 : payload === null ? 503 : 200;
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(
    JSON.stringify(
      payload ?? {
        detail: status === 503 ? "data_service_unavailable" : "not_found",
      },
    ),
  );
});

server.listen(8000, "127.0.0.1");
