import { expect, test, type Browser, type Page } from "@playwright/test";

// Fictional CrashTest identities of the mock OIDC provider. The stack must
// hold the CrashTests dataset (scripts/integration-seed.sh).
async function loginAs(page: Page, name: string) {
  await page.goto("/");
  await page.getByRole("link", { name: /Se connecter avec le SSO/ }).click();
  await page.getByRole("link", { name: new RegExp(name) }).click();
  // The login page also says "LCIT Sign": wait for something only a session shows.
  await expect(page.getByLabel("Compte et réglages")).toBeVisible();
}

test("a signer sees nothing of the operator and admin areas", async ({ page }) => {
  await loginAs(page, "Erwan");
  await expect(page.getByRole("link", { name: "Mes documents" })).toBeVisible();
  await expect(page.getByText("Administration")).toHaveCount(0);
  await page.goto("/admin/diagnostics");
  await expect(page).toHaveURL(/\/$/); // bounced back by the route guard
});

// A one-page PDF generated with pypdf (the server validates PDF structure).
const MINIMAL_PDF = Buffer.from(
  "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgMjAwIDIwMCBdCi9QYXJlbnQgMiAwIFIKPj4KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDU0IDAwMDAwIG4gCjAwMDAwMDAxMTMgMDAwMDAgbiAKMDAwMDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjI1NgolJUVPRgo=",
  "base64",
);

/** As an operator, publish a fresh document and ask `signerEmail` to sign it,
 *  so the test never depends on what earlier runs already signed. */
async function askToSign(browser: Browser, signerEmail: string, title: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginAs(page, "Diane");
  const api = context.request;

  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "e2e.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  expect(created.status()).toBe(201);
  const versionId = (await created.json()).versions[0].id as string;
  expect((await api.post(`/api/documents/versions/${versionId}/publish`)).status()).toBe(200);

  const users = (await (await api.get("/api/campaigns/_meta/users")).json()) as {
    id: string;
    email: string;
  }[];
  const signer = users.find((u) => u.email === signerEmail);
  expect(signer, `${signerEmail} must exist (run the seed first)`).toBeTruthy();

  const campaign = await (await api.post("/api/campaigns", { data: { name: title } })).json();
  await api.post(`/api/campaigns/${campaign.id}/documents`, {
    data: { document_version_id: versionId },
  });
  const launch = await api.post(`/api/campaigns/${campaign.id}/launch`, {
    data: { user_ids: [signer!.id] },
  });
  expect(launch.status()).toBe(200);
  await context.close();
}

test("a signer reads a document, consents and signs", async ({ page, browser }) => {
  const title = `E2E ${Date.now()}`;
  await askToSign(browser, "bob.dupont@lcit-test.local", title);

  await loginAs(page, "Bob");
  await page.getByRole("link", { name: new RegExp(title) }).click();

  const sign = page.getByRole("button", { name: /^Signer/ });
  await expect(sign).toBeDisabled(); // no signature without consent
  await page.getByRole("checkbox").check();
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByText("Document signé")).toBeVisible();
  await expect(page.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);
});

test("an administrator reaches the diagnostics page", async ({ page }) => {
  await loginAs(page, "Alice");
  await page.getByRole("link", { name: "Diagnostic" }).click();
  await expect(page.getByRole("heading", { name: /Diagnostic/ })).toBeVisible();
  await expect(page.getByTestId("check-database")).toBeVisible();
});

test("an operator sees the dashboard and can filter a campaign's follow-up", async ({ page }) => {
  await loginAs(page, "Diane");
  await page.getByRole("link", { name: "Campagnes" }).click();
  await expect(page.getByRole("region", { name: "Tableau de bord" })).toBeVisible();
  await expect(page.getByTestId("stat-Signatures attendues")).not.toHaveText("0");

  await page.getByRole("link", { name: /Campagne sécurité 2026/ }).first().click();
  const table = page.locator("table.simple-table").first();
  await expect(table.getByRole("row")).not.toHaveCount(1);
  await page.getByLabel("Statut").selectOption("SIGNED");
  await expect(table.getByText("SIGNED").first()).toBeVisible();
  await expect(table.getByText("PENDING")).toHaveCount(0);
});

test("an operator targets a whole directory group in one click", async ({ page }) => {
  await loginAs(page, "Diane");
  const api = page.context().request;
  const title = `Ciblage ${Date.now()}`;
  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "g.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  const versionId = (await created.json()).versions[0].id as string;
  await api.post(`/api/documents/versions/${versionId}/publish`);
  const campaign = await (await api.post("/api/campaigns", { data: { name: title } })).json();
  await api.post(`/api/campaigns/${campaign.id}/documents`, { data: { document_version_id: versionId } });

  await page.goto(`/campaigns/${campaign.id}`);
  await expect(page.getByText(`${title} — v1.0`).first()).toBeVisible(); // a title, not a raw id

  await page.getByLabel("Rechercher un groupe").fill("IT");
  await page.getByRole("button", { name: /^IT/ }).click();
  // The IT group of the CrashTests directory has four members.
  await expect(page.getByTestId("recipient-count")).toContainText("4 destinataire(s)");
});

test("the campaign document picker is alphabetical and explains drafts", async ({ page }) => {
  await loginAs(page, "Diane");
  const api = page.context().request;
  const stamp = Date.now();
  const upload = async (title: string, publish: boolean) => {
    const res = await api.post("/api/documents", {
      multipart: {
        title,
        version_label: "1.0",
        file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      },
    });
    const versionId = (await res.json()).versions[0].id as string;
    if (publish) await api.post(`/api/documents/versions/${versionId}/publish`);
  };
  await upload(`Zzz ordre ${stamp}`, true);
  await upload(`Aaa ordre ${stamp}`, true);
  await upload(`Mmm brouillon ${stamp}`, false);
  const campaign = await (await api.post("/api/campaigns", { data: { name: `Ordre ${stamp}` } })).json();

  await page.goto(`/campaigns/${campaign.id}`);
  // The documents load asynchronously: wait for them before reading the list.
  await expect(page.locator("select option", { hasText: `Zzz ordre ${stamp}` })).toHaveCount(1);
  const options = await page.locator("select option:not([disabled])").allTextContents();
  const ours = options.filter((o) => o.includes(`ordre ${stamp}`));
  expect(ours).toEqual([`Aaa ordre ${stamp} — v1.0`, `Zzz ordre ${stamp} — v1.0`]); // A before Z
  // The draft is not silently missing: it is listed, disabled, with the reason.
  await expect(page.locator("select option[disabled]", { hasText: `Mmm brouillon ${stamp}` })).toHaveCount(1);
  await expect(page.getByTestId("draft-hint")).toContainText("brouillon");
});
