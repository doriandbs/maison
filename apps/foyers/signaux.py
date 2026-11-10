from django.dispatch import Signal

# Émis dans la transaction de création, avec l'argument `foyer`. Les apps métier s'y
# abonnent pour initialiser leurs données sans que `foyers` ait à les connaître.
foyer_cree = Signal()
