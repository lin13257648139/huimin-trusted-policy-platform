const path = require("node:path");
const { test, expect, devices } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;


test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#runtime-status")).not.toContainText("正在连接服务");
});


test("辅助录入只生成草稿并在用户采用后进入逐项核对", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#ai-helper summary").click();
  await page.locator("#assistive-narrative").fill("广州天河区三口之家，每月收入3200元，最近没有发生急难事件。");
  await page.locator("#parse-assistive").click();
  await expect(page.locator("#assistive-extraction")).toBeVisible();
  await expect(page.locator("#assistive-extraction")).toContainText(/待核对信息|没有识别出/);
  await page.locator("[data-continue-assistive]").click();
  await expect(page.locator(".wizard-panel.active")).toBeVisible();
  await expect(page.locator(".wizard-panel.active input, .wizard-panel.active select").first()).toBeVisible();
});


test("补充情况执行原句锚定、冲突提示和用户确认闭环", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#load-demo").click();
  await page.locator("#narrative").fill("家庭每月总收入10000元，父亲去年住院花了很多钱。");
  await page.locator("#analyze-supplement").click();
  await expect(page.locator("#supplement-result")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("#supplement-result")).toContainText("与表单冲突");
  await expect(page.locator("#supplement-result")).toContainText("原句依据");
  await page.locator('[data-candidate-action="rejected"]').first().click();
  await expect(page.locator("#supplement-result")).toContainText("已由你选择不采用");
  await page.locator("#screening-consent").check();
  await page.locator("#screen-submit").click();
  await expect(page.locator("#results-zone")).toBeVisible();
  await expect(page.locator("#audit-trail-content")).toContainText("冲突由用户处理");
});


test("UNKNOWN可从结果页直接返回对应字段", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await expect(page.locator('[data-wizard-step="0"]')).toBeVisible();
  await page.locator("#district").selectOption("天河区");
  await page.locator("#household_size").fill("3");
  await page.locator("#wizard-next").click();
  await page.locator("#wizard-next").click();
  await page.locator("#special_person_category_confirmed").selectOption("false");
  await page.locator('input[name="urgent_event_choice"][value=""]').check();
  await page.locator("#wizard-next").click();
  await page.locator("#screening-consent").check();
  await page.locator("#screen-submit").click();
  await expect(page.locator("#resolution-panel")).toBeVisible();
  await page.locator("#resolution-actions button").filter({ hasText: "家庭人均月收入" }).click();
  await expect(page.locator('[data-wizard-step="1"]')).toBeVisible();
  await expect(page.locator("#monthly_income_total")).toBeFocused();
});


test("居民预筛按结果分层并可保存删除", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#load-demo").click();
  await page.locator("#screening-consent").check();
  await page.locator("#persist-screening").check();
  const created = page.waitForResponse((response) => response.url().includes("/api/v1/screenings?persist=true") && response.request().method() === "POST");
  await page.locator("#screen-submit").click();
  expect((await created).status()).toBe(200);
  await expect(page.locator("#results-zone")).toBeVisible();
  await expect(page.locator("#matched-results .benefit-card").first()).toBeVisible();
  await expect(page.locator("#calculation-summary")).toContainText("人均月收入");
  await expect(page.locator("#audit-trail-content")).toContainText("三态求值");

  page.once("dialog", (dialog) => dialog.accept());
  const deleted = page.waitForResponse((response) => response.url().includes("/api/v1/screenings/HM-") && response.request().method() === "DELETE");
  await page.locator("#delete-screening").click();
  expect((await deleted).status()).toBe(200);
  await expect(page.locator("#toast-region")).toContainText("已删除");
});


test("高收入且无急难时不强行推荐任何事项", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#query_date").fill("2026-09-30");
  await page.locator("#district").selectOption("天河区");
  await page.locator("#household_size").fill("3");
  await page.locator("#is_local_hukou").selectOption("true");
  await page.locator("#member_scope_confirmed").selectOption("true");
  await page.locator("#wizard-next").click();
  await page.locator("#monthly_income_total").fill("10000");
  await page.locator("#assets_eligible").selectOption("true");
  await page.locator("#wizard-next").click();
  await page.locator("#special_person_category_confirmed").selectOption("false");
  await page.locator('input[name="urgent_event_choice"][value="false"]').check();
  await page.locator("#rigid_expenses_12m").fill("0");
  await page.locator("#wizard-next").click();
  await page.locator("#screening-consent").check();
  await page.locator("#screen-submit").click();
  await expect(page.locator("#result-title")).toContainText("暂未发现匹配");
  await expect(page.locator("#matched-section")).toBeHidden();
  await expect(page.locator("#next-action-card")).toContainText("系统没有强行推荐任何事项");
  await expect(page.locator("#next-action-card")).not.toContainText("先核对：临时救助");
});


test("特困供养按三项法定条件完成预筛并展示逐项依据", async ({ page }) => {
  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#query_date").fill("2026-09-30");
  await page.locator("#district").selectOption("天河区");
  await page.locator("#household_size").fill("1");
  await page.locator("#is_local_hukou").selectOption("true");
  await page.locator("#wizard-next").click();
  await page.locator("#wizard-next").click();
  await page.locator("#special_person_category_confirmed").selectOption("true");
  await expect(page.locator("#special-hardship-fields")).toBeVisible();
  await page.locator("#no_labor_capacity").selectOption("true");
  await page.locator("#no_livelihood_source").selectOption("true");
  await page.locator("#has_capable_legal_supporter").selectOption("false");
  await page.locator('input[name="urgent_event_choice"][value="false"]').check();
  await page.locator("#wizard-next").click();
  await page.locator("#screening-consent").check();
  await page.locator("#screen-submit").click();
  await expect(page.locator("#matched-results")).toContainText("特困人员救助供养");
  await expect(page.locator("#matched-results")).toContainText("无劳动能力");
  await expect(page.locator("#matched-results")).toContainText("无生活来源");
  await expect(page.locator("#matched-results")).toContainText("法定义务人");
});


test("有据政策问答支持键盘操作、逐条引用与时态审计", async ({ page }) => {
  await page.locator('[data-route="evidence"]').first().click();
  const query = page.locator("#evidence-query");
  await query.fill("最低生活保障收入");
  await query.press("Enter");
  await expect(page.locator("#evidence-results .answer-claim").first()).toBeVisible();
  await expect(page.locator("#evidence-results .evidence-card").first()).toBeVisible();
  await expect(page.locator("#evidence-results")).toContainText("以下结论均可回到政策原文核对");
  await expect(page.locator("#evidence-results")).toContainText("政策逐字原文");
  await expect(page.locator("#evidence-results")).toContainText("已排除");
});


test("材料包执行真实图片预检", async ({ page }) => {
  await page.locator('[data-route="documents"]').first().click();
  await page.locator("#document-file").setInputFiles(path.join(__dirname, "..", "..", "demo_assets", "合成_医疗支出凭据_清晰.png"));
  await expect(page.locator("#selected-file-title")).toContainText("已选择 1 份材料");
  await page.locator("#document-consent").check();
  await page.locator("#check-document").click();
  await expect(page.locator("#document-result")).toContainText("已检查1份材料", { timeout: 90_000 });
  await expect(page.locator("#document-result")).toContainText(/质量|分/);
});


test("治理接口默认拒绝匿名访问并接受正确令牌", async ({ page }) => {
  await page.locator('[data-route="professional"]').click();
  await page.locator('[data-pro-tab="governance"]').click();
  await expect(page.locator("#toast-region")).toContainText("管理员令牌");
  await page.locator("#admin-token").fill("e2e-admin-token-32-characters-long");
  const response = page.waitForResponse((item) => item.url().endsWith("/api/v1/admin/dashboard") && item.status() === 200);
  await page.locator("#apply-admin-token").click();
  await response;
  await expect(page.locator("#admin-metrics article strong").first()).not.toHaveText("—");
});


test("首页通过WCAG A/AA自动扫描", async ({ page }) => {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
});


test.describe("移动端与键盘", () => {
  const pixel = devices["Pixel 7"];
  test.use({ viewport: pixel.viewport, userAgent: pixel.userAgent, deviceScaleFactor: pixel.deviceScaleFactor, isMobile: pixel.isMobile, hasTouch: pixel.hasTouch });

  test("移动端导航可由键盘打开并关闭", async ({ page }) => {
    const menu = page.locator("#mobile-menu");
    await menu.focus();
    await page.keyboard.press("Enter");
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("#page-home")).toBeVisible();
  });
});
