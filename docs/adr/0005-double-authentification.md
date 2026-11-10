# ADR 0005 – Double authentification obligatoire

Date : 2026-11-10 · Statut : accepté

## Contexte

Les données sont financières et personnelles. Le risque le plus probable n'est pas une faille
du code mais un mot de passe réutilisé ailleurs puis divulgué, ou hameçonné.

## Décision

- **Obligatoire pour tous les comptes** (`DOUBLE_AUTH_OBLIGATOIRE`). À la première connexion,
  aucune page ne s'ouvre tant que l'application n'est pas configurée.
- **Codes TOTP** (application d'authentification) avec `django-otp`, qui gère la tolérance
  d'horloge, le refus d'un code déjà utilisé et le freinage des essais ; QR code par `segno`.
- **10 codes de secours** à usage unique, affichés une seule fois, régénérables.
- **Connexion en deux temps** : après le mot de passe, `IntergicielDoubleAuthentification`
  n'autorise que la saisie du code et la déconnexion. Aucun foyer n'est chargé : même le nom
  du foyer reste invisible à qui ne connaît que le mot de passe.
- **Appareil de confiance (30 jours)** : cookie signé, `HttpOnly`, préfixe `__Host-` en HTTPS,
  lié au compte. Le mot de passe reste demandé. Révoqué par « Tout oublier », un changement
  ou une réinitialisation du mot de passe, et un changement de téléphone.
- **Admin Django** : sa propre page de connexion est remplacée par celle du site (code et
  limitation des essais compris), l'accès exige une session vérifiée, et son adresse
  (`ADMIN_CHEMIN`) est imprévisible en production.
- **Perte totale** (téléphone et codes) : seule la commande serveur `retirer_double_auth`
  peut lever la protection, après vérification de l'identité hors du site.

## Écarté

- SMS : payant, vulnérable au détournement de carte SIM.
- Code par e-mail : la boîte mail permet déjà de réinitialiser le mot de passe, ce serait
  un seul facteur déguisé en deux.
- Clés d'accès (WebAuthn) : meilleure protection contre l'hameçonnage, à ajouter plus tard
  en complément.
