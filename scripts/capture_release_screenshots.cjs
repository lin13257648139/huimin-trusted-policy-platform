const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const root = path.resolve(__dirname, "..");
const output = path.join(root, "最终交付", "截图证据");
const baseURL = process.env.CAPTURE_BASE_URL || "http://127.0.0.1:8890";

async function shot(page, name) {
  await page.locator("#toast-region").evaluate((element) => {
    element.replaceChildren();
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(output, name), fullPage: false });
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
    colorScheme: "light",
  });
  const page = await context.newPage();
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#runtime-status").waitFor({ state: "visible" });
  await shot(page, "01_服务首页_v2.png");

  await page.locator('[data-route="screening"]').first().click();
  await page.locator("#query_date").fill("2026-09-30");
  await page.locator("#district").selectOption("天河区");
  await page.locator("#household_size").fill("1");
  await page.locator("#is_local_hukou").selectOption("true");
  await page.locator("#wizard-next").click();
  await page.locator("#monthly_income_total").fill("0");
  await page.locator("#assets_eligible").selectOption("true");
  await page.locator("#wizard-next").click();
  await page.locator("#special_person_category_confirmed").selectOption("true");
  await page.locator("#no_labor_capacity").selectOption("true");
  await page.locator("#no_livelihood_source").selectOption("true");
  await page.locator("#has_capable_legal_supporter").selectOption("false");
  await page.locator('input[name="urgent_event_choice"][value="false"]').check();
  await shot(page, "02_特困供养逐项核对_v2.png");
  await page.locator("#wizard-next").click();
  await page.locator("#screening-consent").check();
  await page.locator("#screen-submit").click();
  await page.locator("#matched-results").getByText("特困人员救助供养").first().waitFor();
  await shot(page, "03_特困供养可信结果_v2.png");

  await page.locator('[data-route="evidence"]').first().click();
  await page.locator("#evidence-query").fill("特困人员救助供养需要满足哪些条件，怎样申请？");
  await page.locator("#evidence-search").click();
  await page.locator("#evidence-results .answer-claim").first().waitFor({ timeout: 120000 });
  await shot(page, "04_有据政策问答_v2.png");

  await page.locator('[data-route="documents"]').first().click();
  await page.locator("#document-file").setInputFiles(path.join(root, "demo_assets", "合成_医疗支出凭据_清晰.png"));
  await page.locator("#document-consent").check();
  await page.locator("#check-document").click();
  await page.locator("#document-result").getByText(/已检查1份材料/).waitFor({ timeout: 120000 });
  await shot(page, "05_材料智能预检_v2.png");

  await page.locator('[data-route="trust"]').first().click();
  await shot(page, "06_可信机制说明_v2.png");

  await page.locator('[data-route="professional"]').click();
  await page.locator('[data-pro-tab="compiler"]').click();
  await page.locator("#compiler-use-llm").uncheck();
  await page.locator("#load-policy-sample").click();
  await page.locator("#compile-policy").click();
  await page.locator("#compiler-output").getByText(/候选规则|影响分析/).first().waitFor({ timeout: 120000 });
  await shot(page, "07_Policy2Rule工作台_v2.png");

  await page.locator('[data-pro-tab="governance"]').click();
  await page.locator("#admin-token").fill("release-admin-token-32-characters");
  await page.locator("#apply-admin-token").click();
  await page.locator("#admin-metrics article strong").first().waitFor();
  await page.waitForTimeout(500);
  await shot(page, "08_运行治理面板_v2.png");

  await browser.close();
  console.log(`CAPTURE_OK files=8 output=${output}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
