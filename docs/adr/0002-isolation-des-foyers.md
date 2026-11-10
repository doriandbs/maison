# ADR 0002 – Isolation des foyers

Date : 2026-11-10 · Statut : accepté

## Contexte

Un même déploiement sert plusieurs foyers étanches. Un utilisateur peut appartenir à plusieurs
foyers (le sien, celui de ses parents en lecture seule, des biens en location…).
Django n'a pas d'équivalent aux filtres Hibernate : rien ne filtre « tout seul » par locataire.

## Décision

1. **Colonne `foyer` partout.** Tout modèle métier hérite de `socle.ModeleDeFoyer`, y compris quand
   le foyer se déduit d'un parent. Seuls `Utilisateur` et `Foyer` y échappent.
2. **Filtrage explicite.** Le gestionnaire par défaut expose `objects.du_foyer(foyer)`. On a écarté
   le filtrage implicite par variable de contexte : il est invisible à la lecture et piégeux dans
   les commandes planifiées et le shell.
3. **Foyer courant en session, revérifié à chaque requête.** `IntergicielFoyerCourant` relit les
   adhésions en base et pose `request.adhesion`. Une session qui désigne un foyer dont on n'est
   pas (ou plus) membre retombe sur le foyer principal.
4. **Mixins de vue.** `AccesFoyerMixin` exige connexion, foyer courant et rôle (lecture : tout
   membre ; écriture : « membre » au minimum, donc jamais « lecture seule »).
   `VueDeFoyerMixin` restreint en plus le queryset des vues génériques : l'objet d'un autre foyer
   répond 404, jamais 403.
5. **Garde-fous automatiques** (`apps/socle/tests/test_isolation_structurelle.py`) : la suite échoue
   si un modèle n'est pas rattaché à un foyer, ou si une URL hors liste publique répond à un anonyme.
   Chaque app ajoute ses tests d'accès croisés (foyer A contre foyer B).

## Rôles

| Rôle | Lire | Modifier les données | Gérer membres et invitations | Gérer les propriétaires |
|---|---|---|---|---|
| Lecture seule | oui | non | non | non |
| Membre | oui | oui | non | non |
| Administrateur | oui | oui | oui | non |
| Propriétaire | oui | oui | oui | oui |

Un foyer garde toujours au moins un propriétaire. Chacun peut quitter un foyer.

## Foyer principal

`Adhesion.est_principal` : un seul par utilisateur (contrainte unique partielle en base).
C'est le foyer ouvert à la connexion ; les autres sont des foyers annexes.

## Invitations

- Le jeton n'est jamais stocké : seule son empreinte SHA-256 l'est. Validité 7 jours.
- Une invitation ne s'accepte **que par le lien reçu par e-mail** : l'inscription ne confirme
  pas l'adresse (ADR 0003), c'est donc le jeton qui prouve l'accès à la boîte aux lettres.
  Les invitations ne sont listées nulle part dans l'application pour le destinataire.
- Le compte qui accepte doit en plus avoir l'adresse de l'invitation : un lien transféré ne
  sert à personne d'autre.
- On n'invite pas directement un propriétaire ; un propriétaire promeut un membre.

## Prévu plus tard : visibilité par membre

En V1 tout membre voit tout le foyer. La restriction « ne voit que ses comptes » s'ajoutera par un
réglage sur `Adhesion` et une méthode `visibles_par(adhesion)` à côté de `du_foyer`, en s'appuyant
sur les titulaires des comptes. Le passage obligé par le gestionnaire rend cet ajout localisé.
