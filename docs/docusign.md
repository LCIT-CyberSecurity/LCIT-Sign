# Signature eIDAS avec DocuSign

LCIT Sign sait faire signer avec **DocuSign** au lieu de sa propre signature. Le choix se fait
**pour chaque demande**, à l'écran 1 de « Faire signer » :

- **Signature LCIT** (par défaut) : identité par le SSO, empreinte du document, horodatage et preuve
  signée par la clé de l'application. C'est une signature électronique *simple* (eIDAS).
- **Signature eIDAS (DocuSign)** : chaque signataire reçoit un e-mail de DocuSign et signe **chez
  DocuSign**. Le niveau (simple, avancée, qualifiée) dépend de l'offre DocuSign du compte.

## Comment ça marche

1. À l'envoi, rien n'est signé ici : quand c'est le tour d'une personne, LCIT Sign met une
   **enveloppe** DocuSign en file d'attente (une enveloppe par signataire et par document).
2. Le *worker* (toutes les 30 s) l'envoie : le document, le signataire et les éléments placés
   (signature, date, nom, e-mail, texte…) partent chez DocuSign, qui prévient la personne.
3. Le worker interroge DocuSign. Quand l'enveloppe est **terminée**, il rapatrie le **PDF signé** et le
   **certificat d'achèvement** DocuSign, enregistre la signature comme les autres (fiche, preuve avec
   l'identifiant d'enveloppe, empreinte, clé LCIT) et passe au signataire suivant. Le PDF signé d'un
   signataire est ce que reçoit le suivant.
4. Le signataire peut cliquer sur **Actualiser** (page du document) pour ne pas attendre le worker.
5. Une demande **annulée** retire (« void ») ses enveloppes en cours. Un refus chez DocuSign est
   enregistré (« refusé »). Une enveloppe qui échoue est retentée 5 fois, puis marquée en échec avec
   le message de DocuSign, visible par le signataire.

Pas de webhook (« Connect ») : DocuSign devrait joindre le serveur depuis Internet. Le suivi se fait
donc par interrogation.

## Limites de cette première version

- Le logo et l'heure placés sur un document ne sont pas repris par DocuSign.
- « Tout signer en un clic » n'existe pas pour une demande DocuSign : chaque document se signe chez
  DocuSign.
- Un signataire sans compte LCIT (personne extérieure) reçoit aussi l'e-mail de DocuSign, comme les autres.

## Réglages (Administration → DocuSign)

Un administrateur saisit : l'environnement (bac à sable ou production), la clé d'intégration,
l'ID utilisateur, l'ID de compte API et la **clé privée RSA** (chiffrée, jamais réaffichée). La
page explique les étapes chez DocuSign (compte développeur gratuit, application, clé RSA,
consentement) et propose « Tester la connexion ».

## Le DocuSign de test (sans compte)

La pile de test (CrashTest, `crashtest/start.sh`) contient un **faux DocuSign** (`mock_docusign/`), sans aucune
valeur légale : il imite l'API utilisée, et remplace l'e-mail de DocuSign par une boîte de réception
(`/mock-docusign/`) où l'on ouvre l'enveloppe et clique « Signer (simulation) ». Dans l'administration,
« Utiliser le DocuSign de test » règle tout en un clic (clé jetable). Ce bouton n'existe pas quand
`LCIT_SIGN_ENVIRONMENT=production`.

Passer au vrai DocuSign = saisir les identifiants du compte de développement (puis de production) :
rien d'autre ne change.
