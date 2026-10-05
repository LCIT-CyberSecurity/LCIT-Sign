# Tester la connexion avec Microsoft Entra ID (compte LCIT)

Objectif : se connecter à LCIT Sign avec son compte Microsoft 365 existant, **sans créer de compte**,
en ne donnant à l'application que le strict nécessaire (nom et e-mail de la personne qui se connecte).
Rien n'est lu dans l'annuaire de l'entreprise, rien n'est écrit dans Microsoft 365.

## Le vocabulaire Microsoft, en clair

| Terme | Ce que c'est | Où le trouver |
|---|---|---|
| **ID de l'annuaire (locataire / tenant)** | L'identifiant de *votre* Microsoft 365 (LCIT). Un code du type `1b2c…`. Il dit à Microsoft « les comptes de LCIT ». | Entra → Vue d'ensemble → *ID de locataire* |
| **ID de l'application (client)** | L'identifiant de la fiche « LCIT Sign » que vous créez dans Entra. C'est la carte d'identité de l'application. | Fiche de l'application → Vue d'ensemble → *ID d'application (client)* |
| **Secret client** | Le mot de passe de l'*application* (pas d'une personne). Il prouve à Microsoft que c'est bien LCIT Sign. Affiché **une seule fois** à la création. | Fiche → Certificats et secrets → *Nouveau secret client* → copier la **Valeur** |

Ces trois valeurs ne sont pas secrètes de la même façon : les deux identifiants peuvent être partagés,
**le secret ne doit jamais être collé dans un chat, un ticket ou Git**.

## Étapes (à faire par quelqu'un qui peut inscrire des applications dans Entra)

1. **Entra admin center → Applications → Inscriptions d'applications → Nouvelle inscription**
   - Nom : `LCIT Sign (test)`.
   - Types de comptes : *Comptes dans cet annuaire organisationnel uniquement* (un seul locataire).
   - URI de redirection : plateforme **Web**, valeur `http://localhost:4180/api/auth/callback`
     (Microsoft accepte le HTTP uniquement pour `localhost`).
2. Notez l'**ID d'application (client)** et l'**ID de l'annuaire (locataire)**.
3. **Certificats et secrets → Nouveau secret client** : durée courte (90 jours). Copiez la *Valeur*.
4. **Autorisations d'API** : ne gardez que Microsoft Graph, déléguées : `openid`, `profile`, `email`
   (vous pouvez retirer `User.Read`). N'ajoutez **aucune** autorisation d'application.
5. **Applications d'entreprise → LCIT Sign (test) → Propriétés → Affectation requise : Oui**, puis
   **Utilisateurs et groupes** : ajoutez uniquement vos comptes de test. Seuls eux pourront se connecter.
6. (Facultatif) **Configuration des jetons → Ajouter une revendication facultative → ID → `email`**.

## Côté LCIT Sign (sur la VM)

Le secret est déposé **par vous** dans un fichier, jamais dans le dépôt :

```bash
cd ~/Git/LCIT-Sign
mkdir -p -m 700 secrets
# colle le secret au prompt, puis Ctrl-D (rien n'est affiché ni gardé dans l'historique du shell)
install -m 600 /dev/stdin secrets/oidc_client_secret
```

Dans le `.env` de la VM (ce fichier n'est pas versionné) :

```text
LCIT_SIGN_OIDC_ISSUER=https://login.microsoftonline.com/<ID-DE-LANNUAIRE>/v2.0
LCIT_SIGN_OIDC_CLIENT_ID=<ID-DE-LAPPLICATION>
LCIT_SIGN_OIDC_CLIENT_SECRET_FILE=/run/secrets/lcit-sign/oidc_client_secret
LCIT_SIGN_PUBLIC_BASE_URL=http://localhost:4180
LCIT_SIGN_COOKIE_SECURE=false
LCIT_SIGN_BOOTSTRAP_ADMIN=<votre-adresse-mail>
```

(retirez du `.env` les deux lignes « mode navigateur » si elles y sont : `PUBLIC_BASE_URL=https://192.168.1.5:4443`
et `COOKIE_SECURE=true`), puis `docker compose up -d --force-recreate api webui`.

Depuis votre poste : `ssh -L 4180:127.0.0.1:4180 vm-integrations`, puis ouvrez `http://localhost:4180`
et cliquez sur « Se connecter avec le SSO ».

## Ce qui se passe, et ce qui ne se passe pas

- Au premier passage, LCIT Sign crée un profil avec votre nom et votre e-mail (aucun mot de passe) ;
  la personne indiquée dans `BOOTSTRAP_ADMIN` devient administrateur, les autres n'ont aucun droit
  tant qu'un administrateur ne leur en donne pas.
- LCIT Sign ne lit pas l'annuaire : il ne connaît que les personnes qui se sont connectées au moins une fois.
- Le formulaire **Annuaire → Microsoft Entra ID** de l'application est **autre chose** : il sert à *importer*
  tous les utilisateurs et groupes, avec une autre inscription d'application et des autorisations de lecture
  de l'annuaire à faire approuver par un administrateur. Inutile pour tester la connexion.

## Retour en arrière

Supprimer le secret ou l'application dans Entra coupe immédiatement l'accès ; remettre les anciennes
valeurs dans `.env` rétablit le faux SSO de test.
