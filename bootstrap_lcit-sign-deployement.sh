#!/usr/bin/env bash
# LCIT Sign Manager: install, update, redeploy, reinstall and remove LCIT Sign.
#
#   ./bootstrap_lcit-sign-deployement.sh
#
# Needs Bash, Docker (with the Compose plugin) and Git. It only ever touches the Docker project
# "lcit-sign" (its containers, its two volumes, its images); the CrashTest, end-to-end and feature
# projects are refused by name. .env is created if missing and never overwritten.
#
# Advanced (tests of this script): LCIT_SIGN_PROJECT names another project, e.g. a throwaway one.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

PROJECT="${LCIT_SIGN_PROJECT:-lcit-sign}"
ENV_FILE="$ROOT/.env"

# --- presentation -------------------------------------------------------------------------------

if [ -t 1 ]; then
    BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
    BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

LOG="$(umask 077; mktemp "${TMPDIR:-/tmp}/lcit-sign-manager.XXXXXX")"
trap 'rm -f "$LOG"' EXIT

say()  { printf '%s\n' "$*"; }
warn() { printf '%s%s%s\n' "$YELLOW" "$*" "$RESET"; }
die()  { printf '%s%s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

banner() {
    say "${BOLD}╔══════════════════════════════════════════════╗"
    say "║              LCIT Sign Manager               ║"
    say "╚══════════════════════════════════════════════╝${RESET}"
    say ""
}

# ask "question" default(o|n) -> 0 when yes. An empty answer (or the end of the input) is the default.
ask() {
    local question="$1" default="$2" hint answer
    if [ "$default" = "o" ]; then hint="[O/n]"; else hint="[o/N]"; fi
    printf '%s %s ' "$question" "$hint"
    read -r answer || answer=""
    answer="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
    [ -n "$answer" ] || answer="$default"
    case "$answer" in o|oui|y|yes) return 0 ;; *) return 1 ;; esac
}

# confirm_typed "TEXT": the operator must type it exactly.
confirm_typed() {
    local expected="$1" answer
    say "Tapez exactement :"
    say ""
    say "    $expected"
    say ""
    printf '> '
    read -r answer || answer=""
    [ "$answer" = "$expected" ]
}

cancelled() { say "Annulé, rien n'a été modifié."; exit 0; }

# Progress lines: "[3/8] Label ............ OK". Numbered while STEP_TOTAL is set, plain otherwise.
STEP_TOTAL=0
STEP_NO=0
lead() {
    local head dots
    if [ "$STEP_TOTAL" -gt 0 ]; then
        STEP_NO=$((STEP_NO + 1))
        head="[$STEP_NO/$STEP_TOTAL] $1 "
    else
        head="$1 "
    fi
    dots="$(printf '%*s' $((52 - ${#head})) '' | tr ' ' '.')"
    printf '%s%s ' "$head" "$dots"
}
# Runs a command; its output goes to the log, and its tail is shown when it fails.
step() {
    local label="$1"; shift
    lead "$label"
    if "$@" >"$LOG" 2>&1; then
        say "${GREEN}OK${RESET}"
        return 0
    fi
    say "${RED}ÉCHEC${RESET}"
    tail -n 25 "$LOG" | sed 's/^/    /'
    return 1
}
step_skipped() { lead "$1"; say "${YELLOW}IGNORÉ${RESET}"; }

# --- environment ----------------------------------------------------------------------------------

# env_get KEY: the value Compose will see: the shell's own variable first, else the one in .env
# (empty when absent).
env_get() {
    if [ -n "${!1-}" ]; then printf '%s' "${!1}"; return 0; fi
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

# env_set KEY VALUE: replace the KEY= line of .env, or append it.
env_set() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp "$ROOT/.env.XXXXXX")"
    if grep -q "^$key=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$value" 'index($0, k "=") == 1 { print k "=" v; next } { print }' \
            "$ENV_FILE" >"$tmp"
    else
        cat "$ENV_FILE" >"$tmp"
        printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

random_hex() {
    if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"; else
        head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

dc() { docker compose -p "$PROJECT" -f "$ROOT/compose.yaml" "$@"; }

prefix()     { local p; p="$(env_get LCIT_SIGN_PREFIX)"; printf '%s' "${p:-lcit-sign}"; }
https_port() { local p; p="$(env_get LCIT_SIGN_HTTPS_PORT)"; printf '%s' "${p:-4443}"; }
http_port()  { local p; p="$(env_get LCIT_SIGN_HTTP_PORT)"; printf '%s' "${p:-4180}"; }

public_url() {
    local base fqdn
    base="$(env_get LCIT_SIGN_PUBLIC_BASE_URL)"
    fqdn="$(env_get LCIT_SIGN_FQDN)"
    if [ -n "$fqdn" ]; then printf 'https://%s:%s' "$fqdn" "$(https_port)"
    else printf 'https://localhost:%s  (ou %s)' "$(https_port)" "${base:-http://127.0.0.1:$(http_port)}"; fi
}

# --- safety -----------------------------------------------------------------------------------------

check_project_name() {
    case "$PROJECT" in
        lcit-sign-crashtest|lcit-e2e|lcit-sign-feature)
            die "Refusé : « $PROJECT » est un projet de test (CrashTest / end-to-end / feature), pas une installation." ;;
    esac
    [[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "Nom de projet invalide : $PROJECT"
    if [ "$PROJECT" != "lcit-sign" ]; then
        warn "Projet Docker alternatif : $PROJECT (LCIT_SIGN_PROJECT)."
    fi
}

check_prerequisites() {
    command -v docker >/dev/null 2>&1 || { echo "Docker est introuvable."; return 1; }
    docker info >/dev/null 2>&1 || { echo "Le démon Docker ne répond pas (droits ou service arrêté)."; return 1; }
    docker compose version >/dev/null 2>&1 || { echo "Le plugin Docker Compose est introuvable."; return 1; }
    command -v git >/dev/null 2>&1 || { echo "Git est introuvable."; return 1; }
    [ -f "$ROOT/compose.yaml" ] || { echo "compose.yaml est introuvable à côté de ce script."; return 1; }
}

# --- detection --------------------------------------------------------------------------------------

project_containers() { docker ps -a -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null; }
project_volumes()    { docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null; }

is_installed() {
    [ -n "$(project_containers)" ] || [ -n "$(project_volumes)" ]
}

git_branch()  { git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "(inconnue)"; }
git_version() { git -C "$ROOT" log -1 --format='%h %s' 2>/dev/null || echo "(pas un dépôt Git)"; }

remote_version() {
    local sha
    sha="$(timeout 10 git -C "$ROOT" ls-remote --heads origin main 2>/dev/null | cut -c1-7)"
    if [ -n "$sha" ]; then printf '%s' "$sha"; else printf '(inaccessible)'; fi
}

show_status() {
    say "Installation        : projet Docker « $PROJECT »"
    say "Version locale      : $(git_version)"
    say "Branche             : $(git_branch)"
    say "Version origin/main : $(remote_version)"
    say "Services            :"
    local services
    services="$(dc ps -a --format '{{.Service}}|{{.Status}}' 2>/dev/null)"
    if [ -n "$services" ]; then
        printf '%s\n' "$services" | while IFS='|' read -r name state; do
            printf '    %-10s %s\n' "$name" "$state"
        done
    else
        say "    (aucun conteneur)"
    fi
    say "URL                 : $(public_url)"
    say ""
}

# --- building blocks -----------------------------------------------------------------------------------

create_env() {
    [ -f "$ENV_FILE" ] && return 0
    [ -f "$ROOT/.env.example" ] || { echo ".env.example est introuvable."; return 1; }
    ( umask 077; cp "$ROOT/.env.example" "$ENV_FILE" )
    env_set LCIT_SIGN_DB_PASSWORD "$(random_hex 24)"
    env_set LCIT_SIGN_SESSION_SECRET "$(random_hex 32)"
    env_set LCIT_SIGN_MASTER_KEY "$(random_hex 32)"
}

# Optional: an HTTPS production setup, asked once at the first installation.
configure_production() {
    ask "Configurer maintenant une exploitation en production (HTTPS, nom de domaine) ?" n || return 0
    local fqdn
    printf "Nom d'accès des utilisateurs (ex. sign.example.org) : "
    read -r fqdn || fqdn=""
    if [[ ! "$fqdn" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
        warn "Nom invalide : configuration production ignorée (développement par défaut, modifiable dans .env)."
        return 0
    fi
    env_set LCIT_SIGN_ENVIRONMENT production
    env_set LCIT_SIGN_COOKIE_SECURE true
    env_set LCIT_SIGN_FQDN "$fqdn"
    env_set LCIT_SIGN_PUBLIC_BASE_URL "https://$fqdn:$(https_port)"
}

prepare_certs() { mkdir -p "$ROOT/certs" && chmod 700 "$ROOT/certs"; }
check_compose() { dc config -q; }
build_images()  { dc build; }
start_stack()   { dc up -d --wait --wait-timeout 300; }

api_health() {
    for _ in $(seq 1 40); do
        if dc exec -T api python -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" \
            >/dev/null 2>&1; then return 0; fi
        sleep 3
    done
    echo "L'API ne répond pas sur /api/health."
    return 1
}

# A fresh database holds the local administrator only.
check_fresh_bootstrap() {
    local q
    q="$(dc exec -T postgres psql -U lcit_sign -d lcit_sign -Atc \
        "select (select count(*) from users) || ' ' || (select count(*) from users where must_change_password and password_hash is not null) || ' ' || (select count(*) from campaigns)")" \
        || return 1
    [ "$q" = "1 1 0" ] || { echo "Base inattendue (utilisateurs / admin à changer / campagnes) : $q"; return 1; }
}

# Backup through ops/admin/backup.sh (one verified .tar.bz2). The database must be running.
make_backup() {
    dc up -d --wait postgres >/dev/null 2>&1 || { echo "PostgreSQL ne démarre pas."; return 1; }
    LCIT_SIGN_PROJECT="$PROJECT" LCIT_SIGN_DATA_VOLUME="$(prefix)-data" "$ROOT/ops/admin/backup.sh"
}

# offer_backup "operation": returns 0 when done or declined, 1 when it failed.
offer_backup() {
    if ask "Créer une sauvegarde avant $1 ?" o; then
        lead "Sauvegarde"
        if make_backup >"$LOG" 2>&1; then
            say "${GREEN}OK${RESET}"
            grep '^Backup written to' "$LOG" | sed 's/^/    /'
            warn "    Rappel : LCIT_SIGN_MASTER_KEY (dans .env) n'est pas dans la sauvegarde ; conservez-la ailleurs."
            return 0
        fi
        say "${RED}ÉCHEC${RESET}"
        tail -n 15 "$LOG" | sed 's/^/    /'
        return 1
    fi
    lead "Sauvegarde"
    say "${YELLOW}IGNORÉE${RESET}"
    warn "Sauvegarde ignorée à la demande de l'utilisateur."
    return 0
}

final_summary() {
    say ""
    say "${GREEN}Terminé.${RESET}"
    say "URL : $(public_url)"
}

# --- operations -----------------------------------------------------------------------------------------

do_install() {
    banner
    say "Installation de LCIT Sign (projet Docker « $PROJECT »)."
    say ""
    local new_env="non"
    [ -f "$ENV_FILE" ] || new_env="oui"
    [ "$new_env" = "oui" ] && configure_production
    STEP_TOTAL=7
    step "Vérification des prérequis" check_prerequisites || return 1
    step "Fichier .env" create_env || return 1
    step "Dossier des certificats" prepare_certs || return 1
    step "Vérification Compose" check_compose || return 1
    step "Construction des images" build_images || return 1
    step "Démarrage et migrations" start_stack || return 1
    step "Vérification de santé" api_health || return 1
    final_summary
    say ""
    say "Compte initial : admin / SecretPassword (à changer à la première connexion)."
    say "Ni SSO, ni annuaire, ni donnée fictive : configurez-les dans Administration."
    if [ "$new_env" = "oui" ]; then
        warn "Sauvegardez LCIT_SIGN_MASTER_KEY (fichier .env) dans un endroit sûr, à part :"
        warn "elle est indispensable pour signer et relire les identifiants enregistrés ; ne la changez jamais."
    fi
}

git_checks() {
    git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
        || { echo "Ce dossier n'est pas un dépôt Git : la mise à jour est impossible."; return 1; }
    local branch
    branch="$(git_branch)"
    [ "$branch" = "main" ] \
        || { echo "La branche courante est « $branch », pas « main » : mise à jour refusée (changez de branche vous-même)."; return 1; }
    local dirty
    dirty="$(git -C "$ROOT" status --porcelain)"
    if [ -n "$dirty" ]; then
        echo "Des modifications locales existent, mise à jour refusée :"
        printf '%s\n' "$dirty" | sed 's/^/    /'
        return 1
    fi
    git -C "$ROOT" fetch origin || { echo "git fetch origin a échoué (réseau ?)."; return 1; }
}

do_update() {
    banner
    say "MISE À JOUR / REDÉPLOIEMENT — les données sont conservées."
    say ""
    STEP_TOTAL=8
    step "Vérification des prérequis" check_prerequisites || return 1
    step "Vérification Git" git_checks || return 1

    local head origin
    head="$(git -C "$ROOT" rev-parse HEAD)"
    origin="$(git -C "$ROOT" rev-parse origin/main)"
    local new_version="oui"
    if [ "$head" = "$origin" ]; then
        new_version="non"
        say ""
        say "Aucune nouvelle version : origin/main est identique à la version installée."
        ask "Redéployer la version actuelle ?" n || cancelled
    elif git -C "$ROOT" merge-base --is-ancestor "$origin" "$head"; then
        die "Votre main local est en avance sur origin/main : mise à jour refusée (rien n'est modifié)."
    elif ! git -C "$ROOT" merge-base --is-ancestor "$head" "$origin"; then
        die "Votre main local a divergé de origin/main : résolvez-le vous-même (rien n'est modifié)."
    fi

    say ""
    offer_backup "la mise à jour" || die "La sauvegarde a échoué : mise à jour interrompue, rien n'a été modifié."
    if [ "$new_version" = "oui" ]; then
        step "Mise à jour origin/main" git -C "$ROOT" merge --ff-only origin/main || return 1
    else
        step_skipped "Mise à jour origin/main (déjà à jour)"
    fi
    step "Vérification Compose" check_compose || return 1
    step "Construction des images" build_images || return 1
    step "Démarrage et migrations" start_stack || return 1
    step "Vérification de santé" api_health || return 1
    final_summary
}

do_reinstall() {
    banner
    say "${RED}${BOLD}ATTENTION — RÉINSTALLATION À NEUF${RESET}"
    say ""
    say "Seront supprimés :"
    say "  - PostgreSQL"
    say "  - utilisateurs"
    say "  - campagnes"
    say "  - documents"
    say "  - signatures"
    say "  - données applicatives"
    say ""
    say "Seront conservés :"
    say "  - .env"
    say "  - certificats"
    say ""
    check_prerequisites >"$LOG" 2>&1 || { cat "$LOG"; return 1; }
    offer_backup "la suppression" || die "La sauvegarde a échoué : réinstallation interrompue, rien n'a été modifié."
    say ""
    confirm_typed "REINSTALLER" || cancelled
    say ""
    STEP_TOTAL=6
    step "Suppression des conteneurs et volumes de $PROJECT" dc down -v --remove-orphans || return 1
    step "Vérification Compose" check_compose || return 1
    step "Construction des images" build_images || return 1
    step "Démarrage et migrations" start_stack || return 1
    step "Vérification de santé" api_health || return 1
    step "Base neuve (admin seul, aucune donnée)" check_fresh_bootstrap || return 1
    final_summary
    say "Compte initial : admin / SecretPassword (à changer à la première connexion)."
}

do_uninstall() {
    banner
    say "${RED}${BOLD}ATTENTION — SUPPRESSION COMPLÈTE${RESET}"
    say ""
    say "Seront supprimés :"
    say "  - conteneurs LCIT Sign"
    say "  - volumes"
    say "  - PostgreSQL"
    say "  - documents"
    say "  - signatures"
    say "  - certificats"
    say ""
    local remove_env="non"
    ask "Supprimer également .env ?" n && remove_env="oui"
    check_prerequisites >"$LOG" 2>&1 || { cat "$LOG"; return 1; }
    offer_backup "la suppression" || die "La sauvegarde a échoué : suppression interrompue, rien n'a été modifié."
    say ""
    confirm_typed "SUPPRIMER LCIT SIGN" || cancelled
    say ""
    local pfx
    pfx="$(prefix)"
    STEP_TOTAL=4
    step "Suppression des conteneurs et volumes de $PROJECT" dc down -v --remove-orphans || return 1
    step "Suppression des images" docker image rm -f "$pfx-api:latest" "$pfx-webui:latest" "$pfx-converter:latest" || true
    if [ -d "$ROOT/certs" ] && [ ! -L "$ROOT/certs" ]; then
        step "Suppression des certificats" rm -rf -- "$ROOT/certs" || warn "Certificats non supprimés (droits ?) : $ROOT/certs"
    else
        step_skipped "Suppression des certificats (aucun dossier certs)"
    fi
    if [ "$remove_env" = "oui" ]; then
        step "Suppression de .env" rm -f -- "$ENV_FILE" || return 1
    else
        step_skipped "Suppression de .env (conservé)"
    fi
    say ""
    say "${GREEN}LCIT Sign est supprimé.${RESET} Le dépôt Git ($ROOT) est conservé."
}

# --- menus ----------------------------------------------------------------------------------------------

main() {
    check_project_name
    banner
    if ! check_prerequisites >"$LOG" 2>&1; then
        cat "$LOG" >&2
        die "Prérequis manquants."
    fi
    if is_installed; then
        show_status
        say "OPÉRATIONS"
        say ""
        say "[1] Mettre à jour / redéployer"
        say "    Conserve toutes les données."
        say "[2] Réinstaller à neuf"
        say "    Supprime les données. Conserve .env et les certificats."
        say "[3] Supprimer complètement LCIT Sign"
        say "    Supprime l'application ET les données."
        say "[0] Quitter"
        say ""
        local choice
        printf 'Votre choix : '
        read -r choice || choice="0"
        case "$choice" in
            1) say ""; do_update ;;
            2) say ""; do_reinstall ;;
            3) say ""; do_uninstall ;;
            *) say "Au revoir."; exit 0 ;;
        esac
    else
        say "Aucune installation LCIT Sign détectée."
        say ""
        say "[1] Installer LCIT Sign"
        say "[0] Quitter"
        say ""
        local choice
        printf 'Votre choix : '
        read -r choice || choice="0"
        case "$choice" in
            1) say ""; do_install ;;
            *) say "Au revoir."; exit 0 ;;
        esac
    fi
}

main "$@"
