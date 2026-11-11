# ADR 0006 – Finances personnelles, foyers réunis

Date : 2026-11-11 · Statut : accepté · Remplace en partie l'ADR 0002 (où vivent les comptes)

## Contexte

Un compte bancaire appartient à une personne, pas à un foyer : le même compte doit montrer le
même solde quel que soit le foyer d'où on le regarde, et on doit pouvoir gérer ses comptes sans
appartenir à aucun foyer. Dans un foyer, tout doit pourtant se voir et se gérer ensemble, dans
les mêmes écrans, en distinguant seulement à qui appartient chaque compte.

## Décision

- **Chaque personne a un espace** : ses comptes, opérations, relevés et crédits. C'est une
  ligne `Foyer` dont `personne` est renseignée, créée à la première connexion avec les
  catégories par défaut, jamais présentée comme un foyer.
- **Dans un foyer partagé, les écrans de finances réunissent les espaces de tous ses membres**
  (`socle.perimetre.Perimetre`). Comptes, opérations, crédits, budget, récap et accueil
  montrent tout le monde ; le titulaire de chaque compte est indiqué. Sans foyer : son espace.
- **Le classement est commun au foyer** : catégories, règles d'import et budget prévisionnel
  appartiennent au foyer (`porte_le_classement`). Un nouveau foyer part de ceux de son
  créateur. Les opérations restent dans l'espace de leur compte ; le budget du foyer range
  chaque opération **par nom de catégorie** (« Alimentation › Courses » d'une personne compte
  dans celle du foyer), ce qui évite toute migration quand quelqu'un rejoint un foyer.
- **Droits** : dans un foyer, son rôle s'applique à tout l'écran (lecture seule → consultation,
  membre et plus → modification, comptes des autres compris). Sans foyer : propriétaire.
- **Crédit à plusieurs** : des co-emprunteurs, choisis parmi les personnes avec qui l'on partage
  un foyer, ont les mêmes droits que celui qui l'a saisi, même hors de ce foyer. Le crédit
  compte en entier dans le patrimoine de chacun, et une seule fois dans celui du foyer.
- **Documents** : au foyer, sans lien avec les comptes ni les opérations.
- `du_foyer()` et `FormulaireDeFoyer` acceptent un périmètre : vues et services sont restés
  ceux d'un foyer unique. Tout est relu à chaque requête : un membre retiré perd aussitôt
  l'accès aux comptes des autres.

## Migrations

- `foyers/0003` : crée l'espace de chacun et y range les finances de chaque foyer partagé
  (au propriétaire le plus ancien) ; les documents restent au foyer. Rien n'est supprimé.
- `foyers/0004` : chaque foyer partagé reçoit un classement commun, recopié de l'espace de son
  propriétaire (catégories, règles, budget).

## Conséquences

- Un compte joint vit dans l'espace de qui le crée ; l'autre titulaire le voit et le gère dans
  le foyer qu'ils partagent.
- Quelqu'un de plusieurs foyers voit, dans chacun, les comptes de ses membres : les comptes
  de ses parents dans le foyer « Parents », ceux de son couple dans le foyer du couple.
