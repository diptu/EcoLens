import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 2400 } });
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));

await page.goto("http://localhost:3000/dashboard/executive", { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(6000);
await page.screenshot({ path: "/private/tmp/claude-501/-Users-macbook-Project-research-EcoLens/dcbdf894-8137-4f9e-9669-81a9b8376efd/scratchpad/exec-01.png", fullPage: true });

console.log("CONSOLE ERRORS:", JSON.stringify(consoleErrors, null, 2));
await browser.close();
