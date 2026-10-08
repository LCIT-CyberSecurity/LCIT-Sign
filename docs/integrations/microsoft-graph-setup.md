# Microsoft 365 setup for LCIT Sign (mail sending via Graph)

> **Do not run these steps until the Graph connector is ready to be tested**
> (local tests, smoke tests and the Integrations VM must already be green).
> The steps below modify the Microsoft tenant; an administrator performs them
> deliberately, one at a time. Nothing in this repository changes a tenant.

Goal: LCIT Sign sends e-mail **only as one dedicated shared mailbox**
(for example `lcit-sign@your-domain`), with the least privilege Microsoft
supports. No paid user licence is created for this: an app registration is
free, and a shared mailbox needs no licence within standard limits (50 GB).

Architecture:

```text
LCIT Sign ──client credentials──▶ Service principal
                                     │  application permission Mail.Send
                                     ▼
                        Exchange Online Application RBAC
                          (scope: that one mailbox only)
                                     ▼
                              lcit-sign@your-domain
```

An unrestricted application `Mail.Send` lets the app send as **anyone** in the
tenant. Step 6 removes that power and step 9 proves it is gone.

## 1. Create the app registration

Entra admin center → *App registrations* → *New registration*. Single tenant,
no redirect URI. Note the **Application (client) ID** and the **Directory
(tenant) ID**.

## 2. Create a credential

*Certificates & secrets* → *New client secret* (shortest lifetime you can
operate, e.g. 6 months; note the renewal date). Copy the **value** immediately.
Never put it in Git, a ticket or a chat. A certificate is preferable when you
can manage one; LCIT Sign currently uses a client secret.

## 3. Grant only the permission needed

*API permissions* → *Add a permission* → *Microsoft Graph* → *Application
permissions* → **`Mail.Send`**. Nothing else (no `Mail.Read`, no `User.Read.All`).

## 4. Admin consent

*Grant admin consent for <tenant>*. After this step, and until step 6 is done,
the application can send as any mailbox. Do steps 5 and 6 without delay.

## 5. Create or choose the shared mailbox

Exchange admin center → *Recipients* → *Mailboxes* → *Add a shared mailbox*
(`lcit-sign@your-domain`). Do not give it a licence or an interactive
sign-in.

## 6. Confine the application to that mailbox (Exchange Application RBAC)

Microsoft's current mechanism, replacing the older Application Access
Policies. In Exchange Online PowerShell (as an Exchange admin):

```powershell
# 1. Register the app's service principal in Exchange
New-ServicePrincipal -AppId <client-id> -ObjectId <enterprise-app-object-id> `
    -DisplayName "LCIT Sign"

# 2. A management scope containing only the dedicated mailbox
New-ManagementScope -Name "LCIT Sign mailbox" `
    -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'lcit-sign@your-domain'"

# 3. Assign the Mail.Send application role, limited to that scope
New-ManagementRoleAssignment -App <client-id> -Role "Application Mail.Send" `
    -CustomResourceScope "LCIT Sign mailbox"
```

Then, **in Entra, remove the tenant-wide consent for `Mail.Send`** if your
design relies solely on RBAC for Exchange (Microsoft documents both models;
follow the current Microsoft Learn page "Role Based Access Control for
Applications in Exchange Online" for the exact order in your tenant). Role
assignments can take up to about 30 minutes to apply.

## 7. Test access

Enter the connector in LCIT Sign (*Administration → Email*, kind
*Microsoft Graph*): tenant ID, client ID, client secret (stored encrypted),
and the dedicated mailbox as sender. Click **Tester la connexion**: the
`token` step must read `OK`.

## 8. Test `Mail.Send`

Click **Envoyer un mail de test** to your own address. It must arrive, sent
from `lcit-sign@your-domain`.

## 9. Negative test (mandatory)

In the same screen use **Test d'isolation**: give a *different* mailbox
(e.g. a colleague's) and your own address as recipient. LCIT Sign tries to
send as that other mailbox.

- Result `isolated: true` → Exchange refused (HTTP 403/404). The connector is
  correctly confined. Nothing was sent.
- Result `isolated: false` → the application **can** send as other mailboxes
  (a mail was delivered to your own address only). **Stop**: fix step 6, wait
  for propagation, repeat. Do not put this connector into service.

The result is recorded in the audit trail.

## 10. Store the secret in LCIT Sign

Done in step 7: the secret is entered through the UI and stored encrypted
(AES-256-GCM under `LCIT_SIGN_MASTER_KEY`). Remove any other copy (notes,
clipboard, shell history). Record the secret's expiry date and rotate it
before then by entering the new value in the same screen.
