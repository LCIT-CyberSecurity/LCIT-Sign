import i18n from "./index";
import { ApiError } from "../api/client";

/** Phrases the server writes itself, mapped to catalogue keys so they follow the interface
 *  language. This only re-words the server's fixed sentences for display: the audit, the logs
 *  and the API answers are untouched, and anything not listed here (a provider's own error, a
 *  technical detail, something a user typed) is shown exactly as it came. */
type PhraseTable = [pattern: RegExp, key: string][];

const SERVER_ERRORS: PhraseTable = [
  [/^Not authenticated$/, "serverErrors.notAuthenticated"],
  [/^Session expired or invalid$/, "serverErrors.sessionExpired"],
  [/^User not found or inactive$/, "serverErrors.userInactive"],
  [/^Insufficient role$/, "serverErrors.insufficientRole"],
  [/^SSO is not configured$/, "serverErrors.ssoNotConfigured"],
  [/^SSO provider unreachable$/, "serverErrors.ssoUnreachable"],
  [/^Invalid login state$/, "serverErrors.invalidLoginState"],
  [/^Login failed$/, "serverErrors.loginFailed"],
  [/^Ce compte est désactivé$/, "serverErrors.accountDisabled"],
  [/^Trop de tentatives, réessayez plus tard$/, "serverErrors.tooManyAttempts"],
  [/^Identifiant ou mot de passe incorrect$/, "serverErrors.badCredentials"],
  [/^Adresse e-mail invalide$/, "serverErrors.invalidEmail"],
  [/^Un utilisateur avec cette adresse existe déjà$/, "serverErrors.userExists"],
  [/^Un compte local a besoin d'un mot de passe$/, "serverErrors.localNeedsPassword"],
  [/^Le mot de passe doit faire au moins (?<min>\d+) caractères$/, "serverErrors.passwordTooShort"],
  [/^Un compte SSO n'a pas de mot de passe ici$/, "serverErrors.ssoNoPassword"],
  [/^User not found$/, "serverErrors.userNotFound"],
  [/^Vous ne pouvez pas désactiver votre propre compte$/, "serverErrors.cannotDisableSelf"],
  [/^Vous ne pouvez pas supprimer votre propre compte$/, "serverErrors.cannotDeleteSelf"],
  [/^C'est le dernier administrateur actif : il ne peut pas être désactivé$/, "serverErrors.lastAdminDisable"],
  [/^C'est le dernier administrateur actif : son rôle ne peut pas être retiré$/, "serverErrors.lastAdminRole"],
  [/^C'est le dernier administrateur actif$/, "serverErrors.lastAdmin"],
  [/^Cet utilisateur ne peut pas être supprimé \((?<reasons>.*)\)\. Désactivez-le à la place\.$/, "serverErrors.userCannotBeDeleted"],
  [/^Signing key not found$/, "serverErrors.keyNotFound"],
  [/^Key is already revoked$/, "serverErrors.keyRevoked"],
  [/^LCIT_SIGN_MASTER_KEY is not configured$/, "serverErrors.masterKey"],
  [/^Mail connector is not configured$/, "serverErrors.mailNotConfigured"],
  [/^Only a Microsoft Graph connector can be isolation-tested$/, "serverErrors.graphOnly"],
  [/^SMTP target rejected: (?<why>.*)$/, "serverErrors.smtpRejected"],
  [/^Failed to send test email: (?<why>.*)$/, "serverErrors.testMailFailed"],
  [/^Campaign not found$/, "serverErrors.campaignNotFound"],
  [/^Vous ne pouvez pas agir sur cette campagne$/, "serverErrors.campaignForbidden"],
  [/^Le contenu de cette campagne est confidentiel : il faut en être le propriétaire ou un préparateur\.$/, "serverErrors.campaignConfidential"],
  [/^Campaign is no longer a draft$/, "serverErrors.notDraft"],
  [/^Cette campagne est terminée : elle ne se modifie plus$/, "serverErrors.campaignFinished"],
  [/^Seule une campagne en cours se modifie ainsi$/, "serverErrors.onlyRunning"],
  [/^Only a draft or published document version can be added to a campaign$/, "serverErrors.onlyDraftOrPublished"],
  [/^Ce document est déjà envoyé : il ne se retire plus\.$/, "serverErrors.docAlreadySent"],
  [/^Ce document est déjà envoyé\.$/, "serverErrors.docAlreadySentShort"],
  [/^This document is not in the campaign$/, "serverErrors.docNotInCampaign"],
  [/^Campaign has no documents to sign$/, "serverErrors.noDocuments"],
  [/^Target population is empty$/, "serverErrors.emptyPopulation"],
  [/^Only an active campaign can send reminders$/, "serverErrors.remindersActiveOnly"],
  [/^Only an active campaign can be closed$/, "serverErrors.closeActiveOnly"],
  [/^Cette campagne ne peut pas être supprimée \((?<reasons>.*)\)\.(?<tail>.*)$/, "serverErrors.campaignCannotDelete"],
  [/^Seule une campagne clôturée ou annulée peut être archivée$/, "serverErrors.archiveClosedOnly"],
  [/^Campaign cannot be cancelled from its current status$/, "serverErrors.cannotCancel"],
  [/^Cette personne est désactivée : un administrateur doit la réactiver\.$/, "serverErrors.personDisabled"],
  [/^Utilisateur introuvable ou désactivé$/, "serverErrors.userNotFoundOrDisabled"],
  [/^(?<name>.*) n'a pas le rôle Signataire \(ni Opérateur, ni Admin\) : donnez-lui d'abord ce rôle\.$/, "serverErrors.noSignerRole"],
  [/^(?<name>.*) est déjà propriétaire ou préparateur$/, "serverErrors.alreadyOwnerOrPreparer"],
  [/^Le propriétaire ne se retire pas : changez d'abord de propriétaire\.$/, "serverErrors.ownerStays"],
  [/^Cette personne n'est pas préparateur de la campagne$/, "serverErrors.notPreparer"],
  [/^Un document de la campagne n'est plus utilisable$/, "serverErrors.docUnusableInCampaign"],
  [/^L'échéance doit être après la date de début\.$/, "serverErrors.deadlineAfterStart"],
  [/^Ce document n'est plus utilisable$/, "serverErrors.docUnusable"],
  [/^Le créateur de la campagne n'existe plus$/, "serverErrors.creatorGone"],
  [/^Document not found$/, "serverErrors.docNotFound"],
  [/^Document version not found$/, "serverErrors.versionNotFound"],
  [/^Ce document est confidentiel : il n'est pas dans vos campagnes\.$/, "serverErrors.docConfidential"],
  [/^Only a draft version can be published$/, "serverErrors.draftOnlyPublish"],
  [/^Ce document comporte un logo d'entreprise, mais aucun logo n'est configuré \(Administration → Logo\)\.$/, "serverErrors.logoNotConfigured"],
  [/^Version is already archived$/, "serverErrors.alreadyArchived"],
  [/^An active campaign still uses this version$/, "serverErrors.usedByCampaign"],
  [/^Cette version fait partie de la preuve et ne peut pas être supprimée \((?<reasons>.*)\)\. Archivez-la à la place\.$/, "serverErrors.versionIsEvidence"],
  [/^Ce document contient des versions qui font partie de la preuve \((?<reasons>.*)\)\. Archivez les versions concernées à la place\.$/, "serverErrors.documentIsEvidence"],
  [/^Not authorized to view this document version$/, "serverErrors.notAuthorizedView"],
  [/^Document content missing from storage$/, "serverErrors.contentMissing"],
  [/^Les éléments d'une version publiée ne peuvent plus être modifiés$/, "serverErrors.publishedLocked"],
  [/^No logo configured$/, "serverErrors.noLogo"],
  [/^not configured$/, "serverErrors.providerNotConfigured"],
  [/^unknown provider$/, "serverErrors.unknownProvider"],
  [/^Le secret client est à renseigner$/, "serverErrors.secretRequired"],
  [/^Ceci ressemble à un identifiant, pas au secret : copiez la VALEUR du secret client \(visible une seule fois à sa création\), pas son ID\.$/, "serverErrors.secretLooksLikeId"],
  [/^L'ID du tenant doit ressembler à (?<example>\S+)$/, "serverErrors.tenantShape"],
  [/^L'ID de l'application \(client\) a la forme (?<example>\S+)$/, "serverErrors.appIdShape"],
  [/^L'ID client Google se termine par \.apps\.googleusercontent\.com$/, "serverErrors.googleIdShape"],
  [/^Report not found$/, "serverErrors.reportNotFound"],
  [/^Signing is not configured$/, "serverErrors.signingNotConfigured"],
  [/^Cette campagne n'est plus ouverte à la signature$/, "serverErrors.signAllClosed"],
  [/^Explicit consent is required to sign$/, "serverErrors.consentRequired"],
  [/^Rien à signer pour vous dans cette campagne\.$/, "serverErrors.nothingToSign"],
  [/^Not authorized to access this signature$/, "serverErrors.notAuthorizedSignature"],
  [/^Assignment not found$/, "serverErrors.assignmentNotFound"],
  [/^Only a published version can be signed$/, "serverErrors.publishedOnly"],
  [/^Aucune demande de signature active pour ce document$/, "serverErrors.noActiveRequest"],
  [/^Ce document vous est demandé par plusieurs campagnes : ouvrez-le depuis la demande de signature voulue pour préciser laquelle vous signez\.$/, "serverErrors.severalCampaigns"],
  [/^You have already signed this document version$/, "serverErrors.alreadySigned"],
  [/^Ce document n'est pas encore à signer : (?<who>.*) doit signer d'abord$/, "serverErrors.notYourTurn"],
  [/^Signature not found$/, "serverErrors.signatureNotFound"],
  [/^Aucun document signé pour cette sélection\.$/, "serverErrors.noSignedDocs"],
  [/^Trop de documents pour un seul export \((?<n>\d+), (?<max>\d+) au maximum\) : choisissez moins de campagnes ou affinez la recherche\.$/, "serverErrors.tooManyDocs"],
  [/^L'export dépasse la taille maximale : choisissez moins de campagnes\.$/, "serverErrors.exportTooBig"],
  [/^Aucun annuaire configuré\.$/, "serverErrors.directoryNone"],
  [/^Un seul annuaire est actif à la fois : '(?<active>[^']*)'\. Configurez '(?<source>[^']*)' pour le rendre actif\.$/, "serverErrors.directoryOnlyOne"],
  [/^unknown directory source '(?<source>[^']*)'$/, "serverErrors.directoryUnknown"],
  [/^connector '(?<source>[^']*)' is not configured$/, "serverErrors.directoryNotConfigured"],
  [/^À renseigner : (?<fields>.*)$/, "serverErrors.directoryFill"],
  [/^the local directory has no settings$/, "serverErrors.directoryNoSettings"],
  [/^the local directory has no secret$/, "serverErrors.directoryNoSecret"],
];

/** The fixed one-line details of the diagnostics page. */
const DIAGNOSTIC_DETAILS: PhraseTable = [
  [/^storage root is not writable$/, "diagnostics.detail.storageNotWritable"],
  [/^read\/write test$/, "diagnostics.detail.readWrite"],
  [/^master key is not configured$/, "diagnostics.detail.noMasterKey"],
  [/^no active key yet \(created at first signature\)$/, "diagnostics.detail.noActiveKey"],
  [/^master key does not match the stored signing key$/, "diagnostics.detail.masterKeyMismatch"],
  [/^active key (?<id>.*)$/, "diagnostics.detail.activeKey"],
  [/^issuer is not configured$/, "diagnostics.detail.noIssuer"],
  [/^discovery endpoint unreachable$/, "diagnostics.detail.discoveryUnreachable"],
  [/^discovery answered HTTP (?<status>\d+)$/, "diagnostics.detail.discoveryHttp"],
  [/^discovery reachable$/, "diagnostics.detail.discoveryOk"],
  [/^no synchronisation has run yet$/, "diagnostics.detail.noSync"],
  [/^last sync (?<source>\S+) succeeded \((?<when>.*)\)$/, "diagnostics.detail.syncOk"],
  [/^last sync (?<source>\S+) (?<status>\S+) \((?<when>.*)\)$/, "diagnostics.detail.syncBad"],
  [/^mail connector is not configured$/, "diagnostics.detail.mailNone"],
  [/^(?<failed>\d+) failed and (?<retry>\d+) retrying notification\(s\)$/, "diagnostics.detail.mailFailed"],
  [/^no failed notification$/, "diagnostics.detail.mailOk"],
  [/^background worker is disabled$/, "diagnostics.detail.workerOff"],
  [/^no cycle completed yet$/, "diagnostics.detail.workerNoCycle"],
  [/^worker has not completed a cycle recently$/, "diagnostics.detail.workerStale"],
  [/^last cycle completed$/, "diagnostics.detail.workerOk"],
  [/^built-in administrator is switched off$/, "diagnostics.detail.adminOff"],
  [/^built-in administrator is not in use$/, "diagnostics.detail.adminUnused"],
  [/^the initial password of the system account has not been changed$/, "diagnostics.detail.adminDefaultPassword"],
  [/^password changed$/, "diagnostics.detail.passwordChanged"],
  [/^version (?<v>.*)$/, "diagnostics.detail.version"],
];

/** Why a user cannot be deleted (the API sends a sentence per reason). */
const DELETE_BLOCKERS: PhraseTable = [
  [/^(?<count>\d+) signature\(s\)$/, "users.blockers.signatures"],
  [/^(?<count>\d+) document\(s\) à signer$/, "users.blockers.assignments"],
  [/^(?<count>\d+) document\(s\) créé\(s\)$/, "users.blockers.documents"],
  [/^(?<count>\d+) campagne\(s\) créée\(s\)$/, "users.blockers.campaigns"],
  [/^(?<count>\d+) campagne\(s\) dont il est propriétaire$/, "users.blockers.owner"],
  [/^(?<count>\d+) campagne\(s\) où il est préparateur$/, "users.blockers.preparer"],
  [/^(?<count>\d+) procès-verbal\(aux\) généré\(s\)$/, "users.blockers.reports"],
  [/^géré par la source « (?<source>.*) »$/, "users.blockers.source"],
  [/^elle est en cours ou programmée : annulez-la d'abord$/, "blockers.running"],
  [/^(?<count>\d+) signature\(s\) enregistrée\(s\)$/, "blockers.recordedSignatures"],
  [/^(?<count>\d+) procès-verbal\(aux\)$/, "blockers.reportsCount"],
  [/^utilisé par la campagne « (?<name>.*) »$/, "blockers.usedByCampaign"],
];

function translate(table: PhraseTable, text: string): string {
  for (const [pattern, key] of table) {
    const match = pattern.exec(text);
    if (!match) continue;
    const params: Record<string, string | number> = { ...match.groups };
    if (params.count !== undefined) params.count = Number(params.count);
    // A sentence that carries the reasons of a refusal: each reason is worded too.
    if (typeof params.reasons === "string") {
      params.reasons = params.reasons.split(" ; ").map(blockerText).join(" ; ");
    }
    return i18n.t(key, params);
  }
  return text;
}

/** "Signataire 2 — label": the server numbers the signing positions in French; the number and
 *  the label a person typed are kept, only the word is the interface's. */
export function roleLabelText(label: string): string {
  const match = /^Signataire (\d+)(.*)$/s.exec(label);
  return match ? `${i18n.t("signers.positionName", { n: match[1] })}${match[2]}` : label;
}

export function blockerText(text: string): string {
  return translate(DELETE_BLOCKERS, text);
}
export const diagnosticText = (text: string): string => translate(DIAGNOSTIC_DETAILS, text);
export const serverErrorText = (text: string): string => translate(SERVER_ERRORS, text);

/** What to show for a failed call: the server's message in the interface language when it is a
 *  known one, its own words otherwise, and the caller's fallback when there is no message. */
export function errorText(error: unknown, fallbackKey = "errors.generic"): string {
  if (error instanceof ApiError && error.message) return serverErrorText(error.message);
  return i18n.t(fallbackKey);
}
