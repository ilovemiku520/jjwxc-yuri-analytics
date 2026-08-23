# Phase 2 normalized catalog

Migrations `20260822_0006`–`20260823_0008` add five `ingest.catalog_*` tables and bounded read
indexes inside the existing
PostgreSQL source of truth. Keeping the MVP in PostgreSQL avoids premature Elasticsearch,
ClickHouse or graph-database dependencies.

## Tables

|Table|Purpose|Reviewed source fields|
|-|-|-|
|`catalog_authors`|Stable author identity|`author_id`, `author_display_name`|
|`catalog_works`|Current work projection|work identity/title, author, creation time, page/dimensions and public counts|
|`catalog_tags`|Tag vocabulary|`tag_name`, `tag_translation`|
|`catalog_work_tags`|Ordered work-to-tag relation|work identity and public tags|
|`catalog_work_metric_snapshots`|Immutable metric history|observation time and public counts|

Every work and author projection references the exact validated immutable observation that
produced it. Projection fails closed when no matching `validation_status=valid` observation
exists. Fixture replay updates rows and replaces work-tag links transactionally, so repeated
offline ingest produces 1 author, 2 works, 2 tags and 3 links rather than duplicates.
Each unique validated work observation produces at most one metric snapshot; Fixture replay
keeps the PostgreSQL snapshot count at two.

Unreviewed fixture fields—including description, comments, followers, profile, region and
links—are intentionally discarded. Source URLs, payloads, object keys and credentials never
enter catalog tables.

## Read API

`GET /api/v1/works` supports opaque-cursor pagination and optional literal title (`q`), exact
`author_id`, and exact tag filters. `GET /api/v1/analytics/tags` returns work counts, while
`GET /api/v1/analytics/authors` returns work counts and sums of reviewed public metrics.
`GET /api/v1/works/{work_id}/metric-history` returns bounded observation history.
`GET /api/v1/analytics/metric-trends` keeps the last snapshot for each work/day before
aggregation and accepts at most a 366-day inclusive range. `GET /api/v1/analytics/freshness`
reports bounded catalog counts and the latest metric observation time.
All remain private-cache, read-only routes behind the existing deployment boundary.
