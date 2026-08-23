import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ownerEmail = "ilovemiku520@outlook.com";

test("shows JJWXC product identity, ownership, and research boundary", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "百合小说的 近实时脉搏" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: ownerEmail })).toHaveAttribute(
    "href",
    `mailto:${ownerEmail}`,
  );
  await expect(
    page.getByText("不采集正文、评论内容", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "JJWXC 百合小说书评与收藏趋势图" }),
  ).toBeVisible();
});

test("filters and reorders novels without triggering source collection", async ({
  page,
}) => {
  await page.goto("/novels");
  await expect(
    page.getByRole("heading", { name: "百合小说分析" }),
  ).toBeVisible();
  await page.getByLabel("检索").fill("长夜");
  await expect(page.getByText("她从长夜来")).toBeVisible();
  await expect(page.getByText("向晚潮声")).toHaveCount(0);
  await page.getByLabel("检索").fill("");
  await page.getByLabel("进度").selectOption("连载");
  await expect(page.getByText("向晚潮声")).toBeVisible();
  await expect(page.getByText("她从长夜来")).toHaveCount(0);
  await page.getByLabel("进度").selectOption("全部");
  await page.getByRole("button", { name: "书评" }).click();
  await expect(page.getByRole("button", { name: "书评" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("navigates novel and author aggregate details", async ({ page }) => {
  await page.goto("/novels/90000002");
  await expect(page.getByRole("heading", { name: "她从长夜来" })).toBeVisible();
  await expect(page.getByText("总书评数")).toBeVisible();
  await page.getByRole("link", { name: "折春枝" }).click();
  await expect(page).toHaveURL(/\/authors\/700002$/u);
  await expect(page.getByRole("heading", { name: "折春枝" })).toBeVisible();
  await expect(page.getByText("公开聚合快照").first()).toBeVisible();
});

test("publishes consistent JJWXC source and non-commercial statements", async ({
  page,
}) => {
  await page.goto("/about/data-policy");
  await expect(
    page.getByRole("heading", { name: "数据使用与来源说明" }),
  ).toBeVisible();
  await expect(
    page.getByText("严禁商业用途、二次分发", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("与晋江文学城不存在隶属、合作、背书或授权关系", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("不保存文案原文", { exact: false }),
  ).toBeVisible();
});

test("explores multi-metric history, adjustable ratings, and the correlation matrix", async ({
  page,
}) => {
  await page.goto("/analytics");
  await expect(
    page.getByRole("heading", { name: "时间与变量 交互分析" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "JJWXC 多指标时间轴图" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "作品指标 Pearson 相关矩阵热力图" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "作品与作者公开数据表现评级" }),
  ).toBeVisible();
  await expect(page.getByLabel("作品评分排行")).toBeVisible();
  await page.getByRole("button", { name: "作者", exact: true }).click();
  await expect(page.getByLabel("作者评分排行")).toBeVisible();
  await page.getByLabel("收藏权重").fill("5000");
  await expect(page.getByText("41.3%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "恢复数据校准权重" }).click();
  await expect(page.getByText("29.0%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "切换为原值" }).click();
  await expect(page.getByText("左轴 · 总书评 · 求和统计 · 千条").first()).toBeVisible();
  await expect(page.getByText("右轴 · 总收藏 · 求和统计 · 万次")).toBeVisible();
  await expect(
    page.getByText("右轴（外侧） · 非 V 章均点击 · 跨作品均值 · 万次/章"),
  ).toBeVisible();
  await page.getByRole("button", { name: "非 V 章均点击" }).first().click();
  await expect(
    page.getByRole("button", { name: "非 V 章均点击" }).first(),
  ).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByText("单量，多时间窗口")).toHaveCount(0);
  await expect(
    page.getByText("文案仅保存字符数", { exact: false }),
  ).toBeVisible();
});

test("shows one-request candidate status without mutation controls", async ({
  page,
}) => {
  await page.goto("/operations/imports");
  await expect(
    page.getByRole("heading", { name: "真实样本候选" }),
  ).toBeVisible();
  await expect(page.getByText("公开元数据候选已生成")).toBeVisible();
  await expect(page.getByText("1 / 1")).toBeVisible();
  await expect(page.getByText("BLOCKED")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /采集|入库|重试|删除/u }),
  ).toHaveCount(0);
});

test("has no serious or critical accessibility violations on JJWXC routes", async ({
  page,
}) => {
  for (const route of [
    "/",
    "/novels",
    "/novels/90000001",
    "/authors",
    "/authors/700001",
    "/analytics",
    "/about/data-policy",
    "/operations/imports",
  ]) {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = results.violations.filter(
      (item) => item.impact === "critical" || item.impact === "serious",
    );
    expect(
      blocking,
      `${route}: ${blocking.map((item) => item.id).join(", ")}`,
    ).toEqual([]);
  }
});
