# ADR 0003 – Modèle fonctionnel de la V1

Date : 2026-11-10 · Statut : accepté (réponses de Dorian aux questions de cadrage)

## Comptes et inscription

- Inscription ouverte à tous (`INSCRIPTION_OUVERTE=True`), sans confirmation de l'adresse e-mail
  (compte actif et connecté dès l'inscription), avec limitation de débit et verrouillage après 5 échecs de connexion.
- Devise unique : l'euro.

## Banque

- `Compte` : nom, type, établissement, titulaires, drapeau épargne, solde initial **et date
  d'ouverture**, archivage par `archive_le`.
- Tout est saisi à la main, aucune synchronisation bancaire.
- Comptes de placement (PEA, assurance vie, crypto…) : on saisit les opérations (versements,
  retraits) **et** un `ReleveSolde` en fin de mois ; la valeur du compte est le dernier relevé.
  `ReleveSolde` est donc livré en V1.
- `Categorie` : une seule table à deux niveaux (`parent`). Une opération se range toujours dans une
  sous-catégorie ; la catégorie parente est déduite.
- `Operation` : montant signé, pas de ventilation sur plusieurs catégories.
- Un virement interne est une paire d'opérations liées par `groupe_virement`, sans catégorie.
  Il n'y a donc pas de catégorie « Épargne » : alimenter un livret est un virement, pas une dépense.

## Budget

- Tableau mensuel et récap annuel sont calculés à la demande, jamais stockés.
- Taux d'épargne = (revenus − dépenses) / revenus.
- Prévisionnel : une ligne par catégorie (parente ou sous-catégorie) et par mois.
  Un budget posé « à partir de mars » vaut pour les mois suivants tant qu'il n'est pas remplacé ;
  un mois précis peut être surchargé.
  Le budget d'une parente non saisi est la somme de ses sous-catégories ; s'il est saisi, il fait foi.

## Documents

- Un document porte un émetteur en texte libre. Il n'y a pas de fiche fournisseur liée.
- La pièce jointe d'une opération est un `Document` lié : un seul circuit de dépôt et de
  téléchargement à sécuriser.

## Gestionnaires de comptes (V3)

Onglet indépendant des documents : espaces clients avec numéro client, identifiant et mot de passe
chiffré (clé hors base). La clé vit sur le même serveur : cela protège d'une fuite de sauvegarde,
pas d'une compromission du serveur.
