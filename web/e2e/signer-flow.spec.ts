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

test("an operator deletes an unused document but not a signed one", async ({ page }) => {
  await loginAs(page, "Diane");
  const api = page.context().request;
  const stamp = Date.now();
  const upload = async (title: string) => {
    const res = await api.post("/api/documents", {
      multipart: {
        title,
        version_label: "1.0",
        file: { name: "d.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      },
    });
    return (await res.json()).versions[0].id as string;
  };
  const doomed = `Jetable ${stamp}`;
  await upload(doomed);

  await page.goto("/documents");
  await page.getByLabel("Rechercher un document").fill(doomed);
  const card = page.locator(".card", { hasText: doomed });
  await card.getByRole("button", { name: /Supprimer le document/ }).click();
  await expect(card).toBeVisible(); // the first click only asks
  await card.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.locator(".card", { hasText: doomed })).toHaveCount(0);

  // A document that has been signed stays, with the reason, and cannot be deleted.
  await page.getByLabel("Rechercher un document").fill("Charte informatique 2026");
  const signed = page.locator(".card", { hasText: "Charte informatique 2026" }).first();
  await expect(signed.getByText(/Conservée/).first()).toBeVisible();
  await expect(signed.getByRole("button", { name: /Supprimer/ })).toHaveCount(0);
});

test("an operator prepares a document by drag and drop, with elements for two people", async ({
  page,
}) => {
  // Tall enough to drop onto the page without scrolling mid-drag.
  await page.setViewportSize({ width: 1500, height: 1100 });
  await loginAs(page, "Diane");
  const api = page.context().request;
  const title = `Préparation ${Date.now()}`;
  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  const versionId = (await created.json()).versions[0].id as string;

  await page.goto(`/documents/versions/${versionId}/prepare`);
  const overlay = page.getByTestId("overlay-1");
  await expect(overlay).toBeVisible();

  // Drag a signature and a date onto the page (the first recipient)...
  await page.getByTestId("tool-SIGNATURE").dragTo(overlay, { targetPosition: { x: 200, y: 500 } });
  await page.getByTestId("tool-DATE").dragTo(overlay, { targetPosition: { x: 520, y: 500 } });
  // ... then add a second recipient and give them a free-text element.
  await page.getByRole("button", { name: "Ajouter un destinataire" }).click();
  await page.getByTestId("tool-TEXT").dragTo(overlay, { targetPosition: { x: 200, y: 300 } });

  await expect(page.getByTestId("field-SIGNATURE")).toHaveAttribute("data-role", "1");
  await expect(page.getByTestId("field-DATE")).toHaveAttribute("data-role", "1");
  await expect(page.getByTestId("field-TEXT")).toHaveAttribute("data-role", "2");
  await expect(page.getByTestId("prep-status")).toContainText("non enregistrées");

  // Move the signature with the mouse.
  const signature = page.getByTestId("field-SIGNATURE");
  const before = await signature.boundingBox();
  await page.mouse.move(before!.x + before!.width / 2, before!.y + before!.height / 2);
  await page.mouse.down();
  await page.mouse.move(before!.x + before!.width / 2 + 60, before!.y + before!.height / 2 - 40, { steps: 6 });
  await page.mouse.up();
  const after = await signature.boundingBox();
  expect(after!.x).toBeGreaterThan(before!.x + 40);
  expect(after!.y).toBeLessThan(before!.y - 25);

  // Label the text element, then save.
  await page.getByTestId("field-TEXT").click();
  await page.getByLabel("Libellé").fill("Fonction");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByTestId("prep-status")).toContainText("Enregistré — 3 élément(s)");

  // It persists, with its recipients.
  await page.reload();
  await expect(page.getByTestId("field-SIGNATURE")).toBeVisible();
  await expect(page.getByTestId("field-TEXT")).toHaveAttribute("data-role", "2");
  await expect(page.getByTestId("field-TEXT")).toContainText("Fonction");

  // Delete with the keyboard, then publish: the elements are frozen.
  await page.getByTestId("field-DATE").click();
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("field-DATE")).toHaveCount(0);
  await page.getByRole("button", { name: "Publier", exact: true }).click();
  await page.getByRole("button", { name: /Publier — les éléments seront figés/ }).click();
  await expect(page).toHaveURL(/\/documents$/);

  await page.goto(`/documents/versions/${versionId}/prepare`);
  await expect(page.getByText(/éléments sont figés/)).toBeVisible();
  await expect(page.getByTestId("tool-DATE")).toHaveCount(0);
  await expect(page.getByTestId("field-SIGNATURE")).toBeVisible();
});

test("a signer fills the text the operator asked for, and it is stamped on the signed PDF", async ({
  page,
  browser,
}) => {
  const title = `Champ texte ${Date.now()}`;
  const context = await browser.newContext();
  const op = await context.newPage();
  await loginAs(op, "Diane");
  const api = context.request;
  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  const versionId = (await created.json()).versions[0].id as string;
  const placed = await api.put(`/api/documents/versions/${versionId}/fields`, {
    data: {
      fields: [
        { page: 1, x: 0.1, y: 0.7, width: 0.3, height: 0.06, kind: "SIGNATURE", role: 1 },
        { page: 1, x: 0.5, y: 0.7, width: 0.2, height: 0.04, kind: "DATE", role: 1 },
        { page: 1, x: 0.1, y: 0.5, width: 0.4, height: 0.04, kind: "TEXT", role: 1, label: "Fonction" },
      ],
    },
  });
  expect(placed.status()).toBe(200);
  await api.post(`/api/documents/versions/${versionId}/publish`);
  const users = (await (await api.get("/api/campaigns/_meta/users")).json()) as { id: string; email: string }[];
  const bob = users.find((u) => u.email === "bob.dupont@lcit-test.local")!;
  const campaign = await (await api.post("/api/campaigns", { data: { name: title } })).json();
  await api.post(`/api/campaigns/${campaign.id}/documents`, { data: { document_version_id: versionId } });
  await api.post(`/api/campaigns/${campaign.id}/launch`, { data: { user_ids: [bob.id] } });
  await context.close();

  await loginAs(page, "Bob");
  await page.getByRole("link", { name: new RegExp(title) }).click();
  const sign = page.getByRole("button", { name: "Signer", exact: true });
  await page.getByRole("checkbox").check();
  await expect(sign).toBeDisabled(); // "Fonction" is required and still empty
  await expect(page.getByText(/votre signature, la date de signature/)).toBeVisible();
  await page.getByLabel(/Fonction/).fill("Directeur général");
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);

  const signatureId = (await page.getByTestId("signature-id").textContent()) as string;
  expect(signatureId).toBeTruthy();
  const list = (await (await page.context().request.get("/api/signatures/me")).json()) as {
    id: string;
    display_id: string;
  }[];
  const mine = list.find((s) => s.display_id === signatureId)!;
  const evidence = await (await page.context().request.get(`/api/signatures/${mine.id}/evidence`)).json();
  expect(evidence.field_values.map((v: { kind: string }) => v.kind).sort()).toEqual(["DATE", "SIGNATURE", "TEXT"]);
  expect(evidence.field_values.find((v: { kind: string }) => v.kind === "TEXT").value).toBe("Directeur général");
  const verdict = await (await page.context().request.get(`/api/signatures/${mine.id}/verify`)).json();
  expect(verdict.valid).toBe(true);
});

test("the system account signs in with the default password and is reminded to change it", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("Compte système (administrateur local)").click();
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("wrong-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("incorrect");

  await page.getByLabel("Mot de passe").fill("SecretPassword");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByLabel("Compte et réglages")).toBeVisible();

  // The reminder is there on every page, and the change dialog opens by itself.
  await expect(page.getByTestId("password-reminder")).toContainText("n'a pas été changé");
  await expect(page.getByRole("dialog", { name: /Changer le mot de passe/ })).toBeVisible();
  await page.getByRole("button", { name: "Plus tard" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("password-reminder")).toBeVisible(); // still nagging
  await page.goto("/admin/users");
  await expect(page.getByTestId("password-reminder")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0); // not re-opened by a page load

  // A weak new password is refused (the account is left as it was).
  await page.getByRole("button", { name: "Le changer maintenant" }).click();
  await page.getByLabel("Mot de passe actuel").fill("SecretPassword");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill("password1234");
  await page.getByLabel("Confirmer le nouveau mot de passe").fill("password1234");
  await page.getByRole("button", { name: "Changer le mot de passe" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "refusé" })).toBeVisible();
});

test("an administrator adds, disables and deletes a user from the interface", async ({ page }) => {
  await loginAs(page, "Alice");
  const email = `e2e.${Date.now()}@lcit-test.local`;
  await page.goto("/admin/users");
  const form = page.getByRole("form", { name: "Ajouter un utilisateur" });
  await form.getByLabel("Adresse e-mail").fill(email);
  await form.getByLabel("Prénom").fill("Essai");
  await form.getByLabel("Nom", { exact: true }).fill("Navigateur");
  await form.getByRole("button", { name: "Ajouter" }).click();
  const row = page.getByTestId(`user-${email}`);
  await expect(row).toContainText("Essai Navigateur");
  await expect(row).toContainText("Ajouté à la main");
  await expect(row).toContainText("Actif");

  await row.getByRole("button", { name: "Désactiver" }).click();
  await row.getByRole("button", { name: "Confirmer la désactivation" }).click();
  await expect(row).toContainText("Désactivé");
  await row.getByRole("button", { name: "Réactiver" }).click();
  await expect(row).toContainText("Actif");

  await row.getByRole("button", { name: /Supprimer/ }).click();
  await row.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.getByTestId(`user-${email}`)).toHaveCount(0);

  // People who signed are kept, with the reason.
  await page.getByLabel("Rechercher un utilisateur").fill("erwan.petit");
  const erwan = page.getByTestId("user-erwan.petit@lcit-test.local");
  await expect(erwan).toContainText("Conservé");
  await expect(erwan.getByRole("button", { name: /Supprimer/ })).toHaveCount(0);
});

test("directory settings explain themselves with a bubble and an example", async ({ page }) => {
  await loginAs(page, "Alice");
  await page.goto("/admin/directory");
  await page.getByTestId("source-entra").getByRole("button", { name: "Configurer" }).click();
  const hint = page.getByRole("button", { name: "Aide : ID du tenant" });
  await hint.hover();
  await expect(page.getByRole("tooltip").filter({ hasText: "ID de locataire" })).toBeVisible();
  await expect(page.getByRole("tooltip").filter({ hasText: "1b2c3d4e-5f60" })).toBeVisible();
});
