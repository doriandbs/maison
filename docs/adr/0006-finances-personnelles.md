# ADR 0006 – Finances personnelles, foyers partagés

Date : 2026-11-11 · Statut : accepté · Remplace en partie l'ADR 0002 (où vivent les comptes)

## Contexte

Un compte bancaire appartient à une personne, pas à un foyer : le même compte doit montrer le
même solde quel que soit le foyer d'où on le regarde, et on doit pouvoir gérer ses comptes sans
appartenir à aucun foyer.

## Décision

- **Chaque personne a un espace financier personnel** : comptes, opérations, imports,
  catégories, règles, budget, récap, crédits. Techniquement, c'est une ligne `Foyer` dont
  `personne` est renseignée, créée à la première connexion avec les catégories par défaut.
  Elle n'est jamais présentée comme un foyer (ni listée, ni « activable »). Tout le code
  « par foyer » (isolation, `du_foyer`, tests d'accès croisés) s'applique donc tel quel.
- **Un foyer partagé** (`personne` vide) regroupe des personnes et leurs **documents**. Il n'a
  plus de finances ; les documents ne sont plus reliés à des comptes ni à des opérations.
- **Accès croisé** : dans un foyer partagé, chaque membre accède à l'espace des autres membres
  avec le rôle qu'il a dans ce foyer (lecture seule → consultation, membre et plus →
  modification). Le sélecteur « Finances de » ne propose que les membres du foyer courant.
- **Deux contextes par requête** (`IntergicielFoyerCourant`) : `adhesion_foyer` (foyer
  partagé courant) et `adhesion` (espace affiché, adhésion calculée et jamais enregistrée pour
  l'espace d'un autre). Chaque vue déclare sa `portee` : « finances » ou « foyer ».
- Tout est relu en base à chaque requête : un membre retiré du foyer perd aussitôt l'accès aux
  espaces des autres, même si sa session les désigne encore.

## Migration

`foyers/0003` crée l'espace de chaque utilisateur et y range les finances de chaque foyer
partagé : celles-ci vont au propriétaire le plus ancien du foyer. Les catégories de même nom
sont fusionnées, un compte dont le nom est déjà pris est renommé. Rien n'est supprimé.

## Conséquences

- La fonction « déplacer des comptes vers un autre foyer » disparaît : un compte n'est plus
  dans un foyer.
- Un compte joint vit dans l'espace de celui qui le crée ; l'autre titulaire le voit et le
  gère par le foyer qu'ils partagent.
