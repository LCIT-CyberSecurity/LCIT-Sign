# Guide utilisateur — LCIT Sign

Ce guide explique comment utiliser LCIT Sign. Il est écrit pour trois profils :

| Profil | Ce qu'il fait | Chapitres |
|---|---|---|
| **Signataire** (tout le monde) | Utilisateur standard : signe ce qu'on lui demande, **prépare, envoie et suit ses propres campagnes** | [1](#1-se-connecter) · [2](#2-signer-un-document) · [3](#3-faire-signer-un-document) · [4](#4-suivre-relancer-récupérer) · [5](#5-la-bibliothèque-de-documents) |
| **Opérateur** | Administrateur métier : voit **toutes** les campagnes, change propriétaire et préparateurs ; ne lit pas le contenu confidentiel | [4](#4-suivre-relancer-récupérer) · [4 bis](#4-bis-qui-voit-quoi-dans-une-campagne) |
| **Administrateur** | Gère les accès, les annuaires, les e-mails, les clés ; accès complet | [6](#6-administration) · [7](#7-installation-et-premier-accès) |

Une même personne peut avoir plusieurs profils. Le menu à gauche n'affiche que ce que vous avez le droit
de faire.

---

## 1. Se connecter

En général, on se connecte avec le compte de l'entreprise, sans mot de passe à retenir.

1. Ouvrez l'adresse de LCIT Sign et cliquez sur **Continuer avec Microsoft**, **Continuer avec Google** ou
   **Continuer avec le SSO** (selon votre entreprise).
2. Choisissez ou saisissez votre compte d'entreprise sur la page de votre fournisseur.
3. Vous arrivez sur **Mes signatures**.

**Connexion locale.** Sous le bouton, **Connexion locale** ouvre un formulaire (identifiant ou e-mail, mot de
passe). Il sert au compte système et aux personnes pour qui un administrateur a créé un **compte local** ;
à leur première connexion, elles choisissent leur propre mot de passe. Si aucun SSO n'est configuré, ce
formulaire est la page de connexion.

> Si votre session reste inactive une heure, elle se ferme : il suffit de se reconnecter.

---

## 2. Signer un document

### Mes signatures

La page d'accueil regroupe tout ce qui vous concerne :

- **À signer** — les documents qu'on vous demande de signer, avec l'échéance éventuelle.
- **À venir** — les documents qui seront à vous après la signature d'une autre personne (par exemple
  le RSSI). Vous êtes prévenu par e-mail le moment venu.
- **Signés** — tout ce que vous avez signé, avec trois boutons : **Ouvrir** (le PDF signé dans le
  navigateur), **PDF signé** (téléchargement) et **Preuve et signataires**.

### Signer

1. Cliquez sur le document : il s'affiche **tel que vous allez le signer**, avec ce que les signataires
   précédents y ont déjà apposé et, en pointillés, ce qui sera ajouté pour vous.
2. Renseignez les champs demandés (signalés par *), par exemple « Fonction » ou « Société ».
3. Cochez la case de consentement.
4. Cliquez sur **Signer**.

Vous voyez alors **Document signé**, avec un identifiant du type `SIG-3F9A12C0B7D4`, et vous pouvez
télécharger le PDF signé et le certificat. Vous recevez aussi une confirmation par e-mail.

Toute personne à qui une signature a été demandée peut signer : aucun rôle particulier n'est nécessaire.

### Plusieurs documents d'une même demande : tout signer en un clic

Quand une demande contient plusieurs documents pour vous, un bouton **Signer les N documents** apparaît.
Les questions communes (« Fonction »…) ne sont posées **qu'une fois** ; un seul consentement et un seul
clic signent tout.

### Vérifier une signature

Depuis **Preuve et signataires**, vous voyez qui a signé le document, dans quel ordre, quand, et le résultat
de la **vérification** : l'identité figée au moment de la signature, l'empreinte du document d'origine et
celle du document signé, la clé qui a scellé la preuve. Si le fichier était modifié après coup, la
vérification l'indiquerait.

---

## 3. Faire signer un document

Menu **Faire signer** (opérateurs et administrateurs).

On y démarre par un **nom de demande** (« PSSI 2026 »), puis cinq écrans. Tout est enregistré au fur et à
mesure : on peut quitter et reprendre plus tard depuis la liste **En préparation**. Une demande en
préparation peut être supprimée (bouton **Supprimer**, avec confirmation) tant qu'elle n'est pas envoyée.

### Écran 1 — Signataires et planning

**Qui signe, dans quel ordre.** Ajoutez des signataires avec **Ajouter une personne** :

- une **personne précise** (par exemple le RSSI) : elle signe une seule fois pour toute la demande ;
- **Chaque destinataire** : une liste de personnes qui signent chacune leur propre copie. Cette liste
  se compose par équipes (groupes de l'annuaire), par personnes, ou en prenant tout le monde. Le
  compteur indique combien de personnes seront sollicitées (sans doublons).

Les signataires passent **dans l'ordre** : la position 2 n'est sollicitée qu'une fois la position 1
signée, et sa copie porte la signature précédente. « Chaque destinataire » est toujours en dernier.

**Une personne extérieure à l'entreprise** : **Ajouter une personne extérieure**, avec prénom, nom et
adresse e-mail. Elle est indiquée comme *externe*, reçoit un message qui lui explique comment se
connecter, et n'est jamais modifiée ni désactivée par une synchronisation d'annuaire.

**Planning** (tout est facultatif) :

- **Date de début** — aujourd'hui par défaut. Choisir une date future **programme** l'envoi : personne
  n'est prévenu avant.
- **Date d'échéance** — 30 jours après le début par défaut.
- **Relance** si pas de réponse — **aucune** par défaut ; sinon à la première relance au bout de N jours,
  puis tous les N jours, un nombre maximal de fois.
- **Renouvellement** — redemander la signature régulièrement (tous les N jours ou mois).

### Écran 2 — Documents

Déposez un ou plusieurs documents (glisser-déposer) ou choisissez dans la **bibliothèque**. Formats
acceptés : **PDF**, et **Word / LibreOffice** (convertis automatiquement en PDF). Un document pris dans
la bibliothèque sert de modèle et n'est jamais modifié.

### Écran 3 — Préparer

C'est l'éditeur : une bande en haut liste les documents, le suivant s'ouvre tout seul quand vous avez
terminé le précédent.

- Choisissez le **signataire** auquel vous donnez des éléments (Signataire 1, 2…).
- Glissez un élément sur la page : **signature**, **date**, **heure**, **nom complet**, **prénom**, **nom**,
  **e-mail**, **lieu**, **logo de l'entreprise**, ou un **texte à saisir** (que le signataire remplira).
- Déplacez ou redimensionnez à la souris ; les flèches du clavier ajustent finement ; **Suppr** supprime
  l'élément sélectionné.
- Un champ à saisir peut porter un **nom commun** : posé sur plusieurs documents, il n'est demandé
  qu'une fois au signataire.
- **Enregistrer**, puis **Terminer : vérifier et envoyer**.

Les éléments automatiques (nom, e-mail, date, signature) viennent du **compte** du signataire et de
l'horloge : on ne peut pas signer sous une autre identité.

### Écran 4 — Vérifier et envoyer

Un récapitulatif : signataires, documents, éléments placés, planning. Si quelque chose manque (aucun
destinataire, document sans élément, signataire sans signature à poser), l'écran dit **précisément quoi**
et ce qui est à faire.

**Envoyer pour signature** demande une confirmation (**Oui, envoyer maintenant**). Une fois envoyée, la
demande **ne se modifie plus** : pour changer quelque chose, on l'annule et on en crée une autre (on peut
cependant ajouter des personnes ou des documents, voir le chapitre suivant).

### Écran 5 — Documents signés

Les documents signés arrivent ici **au fur et à mesure**, avec leur preuve. **Actualiser** met à jour ;
**Ouvrir le suivi complet** mène à la page de suivi.

---

## 4. Suivre, relancer, récupérer

Menu **Suivi**.

### Onglet « Campagnes »

La liste des demandes, avec leur état (programmée, envoyée, clôturée, annulée, archivée), un tableau de
bord (signatures attendues, signées…) et des filtres. Ouvrez une campagne pour :

- voir **qui a signé et qui doit encore signer** (avec les dates) ;
- **relancer** une personne, ou toutes celles qui n'ont pas signé, avec un message libre si besoin ;
- **ajouter des personnes** ou **retirer** quelqu'un (ce qui était déjà signé est conservé) ;
- **ajouter un document** à une demande en cours, puis le libérer pour les signataires ;
- **télécharger** le PDF signé de chacun, ou ouvrir sa **preuve** ;
- **clôturer**, **annuler** (plus personne ne peut signer, ce qui est signé reste), **archiver** ;
- **générer le procès-verbal** (PV) : un document signé qui liste la campagne et ses signatures ;
- **supprimer** — seulement une campagne qui n'a jamais produit de preuve ; sinon elle est *conservée* et
  on l'archive. La page dit pourquoi.

### Onglet « Documents signés »

Tous les documents signés, pour **une ou plusieurs campagnes** au choix, avec recherche. **Exporter en
ZIP** télécharge les PDF signés (et leurs preuves) en une fois.

---

## 4 bis. Qui voit quoi dans une campagne

Chaque campagne a un **propriétaire** (celui qui la conduit) et peut avoir d'autres **préparateurs**. On
voit la mention « Créée par » si c'est quelqu'un d'autre : l'historique n'est jamais réécrit.

| | Signataire propriétaire ou préparateur de la campagne | Signataire d'une autre campagne (ou simple signataire de celle-ci) | Opérateur | Administrateur |
|---|---|---|---|---|
| Voir la campagne, son état, ses signataires, sa progression | oui | **non** (elle n'existe pas pour lui) | oui, toutes | oui |
| Relancer, annuler, clôturer, archiver | oui | non | oui | oui |
| Changer le propriétaire, ajouter ou retirer un préparateur | oui | non | oui | oui |
| **Lire le contenu** : documents, PDF signés, certificats, preuves, exports, procès-verbaux | oui | **non** | **non**, sauf s'il est préparateur de cette campagne | oui |
| Préparer, modifier, envoyer | oui | non | non | oui |

**Une absence, un départ.** Alice (RH) est absente : un opérateur ajoute Sophie comme préparatrice, puis
la désigne propriétaire. Alice reste préparatrice tant qu'on ne la retire pas ; l'historique, les
signatures et le journal d'audit sont conservés.

**Accès exceptionnel.** Un opérateur qui doit vraiment lire le contenu s'ajoute lui-même comme préparateur
de la campagne : l'opération est **tracée dans le journal d'audit**.

Dans la page d'une campagne, la carte **Propriétaire et préparateurs** montre qui conduit la campagne, et
permet d'**Ajouter un préparateur** et de **Changer le propriétaire**. Sans accès au contenu, la page le
dit et masque les documents signés, les preuves et les procès-verbaux.

## 5. La bibliothèque de documents

Menu **Documents** : les documents réutilisables (modèles). Pour chacun : titre, description, catégorie,
**versions**. Une version **publiée est immuable** : pour corriger, on crée une nouvelle version, jamais en
modifiant l'ancienne, de sorte qu'une signature se rapporte toujours au texte exact que la personne a vu.
Les fichiers sont contrôlés à l'envoi (vrai PDF, pas de JavaScript, pas de macros pour les fichiers Office).

---

## 6. Administration

Menu **Administration** (administrateurs).

### Utilisateurs et rôles

Liste des personnes, d'où elles viennent (annuaire, ajout manuel, SSO), leurs rôles :

| Rôle | Droits |
|---|---|
| **Signataire** | Rôle de l'utilisateur standard, donné **par défaut à tout compte actif** : préparer des documents, créer et conduire des campagnes (les siennes, et celles dont il est préparateur), se choisir ou choisir d'autres signataires, et **signer**. Sans ce rôle, aucune signature n'est acceptée, même avec une demande en attente |
| **Opérateur** | Administrateur métier : voir toutes les campagnes, changer propriétaire et préparateurs ; pas le contenu confidentiel |
| **Administrateur** | Tout ce qui est administratif : utilisateurs, annuaire, e-mail, clés, audit ; accès complet |

On peut **ajouter** une personne à la main en choisissant sa **méthode d'authentification** : **SSO** (aucun
mot de passe ici) ou **Compte local** (un mot de passe initial, obligatoire, que la personne change à sa
première connexion ; il n'est jamais affiché ni journalisé). On choisit aussi ses rôles. On peut ensuite la
**désactiver** (et la réactiver) ou la **supprimer** —
sauf si elle a signé : son historique est alors conservé, avec la raison indiquée.

### Logo

Le logo de l'entreprise s'affiche en haut à gauche et sur la page de connexion. On le remplace par un
fichier image, on peut revenir au logo LCIT.

### Identités & accès

Une seule page, deux sections : **Connexion** (comment les gens s'authentifient) et **Annuaire** (d'où
viennent personnes et groupes). Les deux sont indépendants, même si Microsoft Entra ID sert aux deux.

- **Connexion** : **un seul** fournisseur SSO est actif (Microsoft Entra ID ou Google) ; la page de
  connexion ne propose que lui, plus la **connexion locale**, toujours disponible. Enregistrer un
  fournisseur l'active ; « Utiliser ce fournisseur » bascule sur un autre déjà configuré. Si les variables
  `LCIT_SIGN_OIDC_*` du serveur sont définies, elles imposent le SSO (la page le signale).
- **Annuaire** : **un seul** annuaire est actif, le seul qui se synchronise. Toute personne qui
  s'authentifie peut entrer dans LCIT Sign (un compte désactivé reste refusé) ; ses rôles disent ce
  qu'elle y fait. Un nouveau compte actif est **Signataire** d'office ; un rôle retiré par un
  administrateur n'est jamais redonné par une synchronisation.

#### Annuaire : les sources

Choisissez la **source** des personnes et des équipes : *local* (démonstration), **Microsoft Entra ID**,
**Google Workspace** ou **LDAP / Active Directory**. Chaque formulaire a une **bulle d'aide** et un
exemple sur chaque champ, et une section « Comment préparer … » pas à pas. Les secrets sont saisis ici,
chiffrés, et **jamais réaffichés**.

- **D'où vient le nom de l'équipe ?** Des groupes de l'annuaire, d'un attribut (service, unité
  d'organisation…), ou des deux.
- **Synchroniser maintenant** lance une synchronisation ; l'historique montre ce qui a changé. Elle
  peut aussi être planifiée (toutes les N minutes).
- Une personne qui **disparaît** de l'annuaire est **désactivée**, jamais supprimée : ses signatures
  restent. Une personne ajoutée à la main, ou extérieure, n'est jamais touchée par la synchronisation.

### E-mail

Choisissez comment LCIT Sign envoie ses messages : **SMTP**, **Microsoft Graph** ou **Gmail**. Un
bouton teste la connexion et un autre envoie un message d'essai. Voir
[`microsoft-graph-setup.md`](microsoft-graph-setup.md) pour Graph.

### Clés de signature

Les signatures sont scellées par une clé de la plateforme. On peut **renouveler** la clé : les anciennes
signatures restent vérifiables, car les anciennes clés publiques sont conservées.

### Audit

Le journal de toutes les actions sensibles, **chaîné** pour détecter une altération ; un bouton vérifie
l'intégrité de la chaîne.

### Diagnostic

L'état de la plateforme : base de données, stockage, clé de signature, SSO, messagerie et worker.
Un rappel s'y affiche tant que le mot de passe initial du compte système n'a pas été changé.

---

## 7. Installation et premier accès

Voir le [README](../README.md) pour installer. À la première mise en route :

1. **Se connecter avec le compte système local** (identifiant `admin`, par « Connexion locale »). Son mot
   de passe initial est `SecretPassword` : l'application demande de **le changer tout de suite** (mot de
   passe fort exigé) et le rappelle à chaque connexion tant que ce n'est pas fait. Une installation neuve
   ne contient **que ce compte** (aucune personne fictive).
2. **Configurer le SSO** (variables d'environnement, voir [`entra-sso-test.md`](entra-sso-test.md)) : la page
   de connexion affiche alors le bouton de votre fournisseur. Les autres personnes se connectent par SSO,
   ou avec un compte local que vous leur créez.
3. Dans **Administration** : brancher l'**annuaire**, l'**e-mail**, importer le **logo**, donner les rôles.
4. Dans **Faire signer** : une première demande de test avec deux collègues.

## Questions fréquentes

**Je ne vois pas le menu « Faire signer ».** Il faut le rôle opérateur ou administrateur.

**Je n'ai pas reçu l'e-mail « à signer ».** Vérifiez l'e-mail dans **Administration → E-mail** (test
d'envoi), et que la demande n'est pas programmée à une date future. Le document est toujours dans **Mes
signatures**.

**« Ce document vous est demandé par plusieurs campagnes. »** Le même document vous est demandé deux fois
par deux demandes : ouvrez-le depuis la demande voulue (la liste **À signer**) ; chaque demande se signe
séparément.

**Une signature est refusée avec « La clé maître du serveur ne correspond pas… ».** La clé maître du serveur
a été changée sans que la clé de signature suive : prévenez un administrateur, qui peut renouveler la clé
de signature. Rien n'est signé tant que ce n'est pas réglé.

**Puis-je annuler une signature ?** Non : une signature est définitive. On peut annuler la **demande**
pour les personnes qui n'ont pas encore signé.
