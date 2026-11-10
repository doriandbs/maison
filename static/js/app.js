// Petites finitions d'interface. Tout fonctionne sans ce script : il n'ajoute que du confort.
(() => {
  "use strict";

  const mouvementReduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const euros = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

  // Chiffres clés : défilent de 0 jusqu'à leur valeur, puis reprennent le texte du serveur.
  function animerCompteur(element) {
    const cible = Number.parseFloat(element.dataset.compteur);
    const texteFinal = element.textContent;
    if (!Number.isFinite(cible) || cible === 0) return;
    const duree = 1100;
    const debut = performance.now();
    const etape = (maintenant) => {
      const t = Math.min((maintenant - debut) / duree, 1);
      const adouci = 1 - Math.pow(1 - t, 4);
      element.textContent = euros.format(cible * adouci);
      if (t < 1) requestAnimationFrame(etape);
      else element.textContent = texteFinal;
    };
    requestAnimationFrame(etape);
  }

  // Notifications : bouton de fermeture, et disparition automatique des messages de succès.
  function brancherNotifications() {
    document.querySelectorAll(".toast").forEach((toast) => {
      toast.querySelector("[data-fermer]")?.addEventListener("click", () => toast.remove());
      if (toast.matches(".toast-success, .toast-info")) {
        setTimeout(() => toast.remove(), 6500);
      }
    });
  }

  // Menus <details> : se referment au clic ailleurs et avec Échap.
  function brancherMenus() {
    const menus = document.querySelectorAll("details.menu");
    document.addEventListener("click", (evenement) => {
      menus.forEach((menu) => {
        if (menu.open && !menu.contains(evenement.target)) menu.open = false;
      });
    });
    document.addEventListener("keydown", (evenement) => {
      if (evenement.key !== "Escape") return;
      menus.forEach((menu) => {
        if (!menu.open) return;
        menu.open = false;
        menu.querySelector("summary")?.focus();
      });
    });
  }

  document.addEventListener("click", (evenement) => {
    if (evenement.target.closest("[data-imprimer]")) window.print();
  });

  document.addEventListener("DOMContentLoaded", () => {
    if (!mouvementReduit) document.querySelectorAll("[data-compteur]").forEach(animerCompteur);
    brancherNotifications();
    brancherMenus();
  });
})();
