/* =========================================================
   MENU VAN DE WEBSITE
   Hier staan alle pagina's. Voeg je een nieuwe pagina toe?
   Zet hem dan ook in deze lijst, dan verschijnt hij vanzelf
   op de voorpagina en in het menu bovenaan elke pagina.

   klaar: true  = de pagina is af
   klaar: false = er staat nog "binnenkort" bij
   ========================================================= */

const PAGINAS = [
  { bestand: "salaris.html",     titel: "Wat is het salaris?",          kort: "Loondienst of zzp, en wat reken je per paard?",           klaar: true },
  { bestand: "opleiding.html",   titel: "Welke opleiding heb je nodig?", kort: "Hoe word je hoefsmid en hoe lang duurt dat?",             klaar: true },
  { bestand: "werkdag.html",     titel: "Hoe ziet een werkdag eruit?",   kort: "Van de eerste stal tot het laatste paard.",               klaar: true },
  { bestand: "gereedschap.html", titel: "Het gereedschap",               kort: "Hoefmes, rasp, tang, aambeeld en het schootsvel.",        klaar: true },
  { bestand: "de-hoef.html",     titel: "Proces van het bekappen van een paard", kort: "Hoe gaat bekappen en beslaan, stap voor stap?",           klaar: true },
  { bestand: "waarom.html",      titel: "Waarom mijn droombaan?",        kort: "Waarom ik dit onderwerp koos, met mijn paard en pony.",     klaar: true },
];

(function () {
  const huidige = location.pathname.split("/").pop() || "index.html";

  // Kaartjes op de voorpagina
  const inhoud = document.getElementById("inhoud");
  if (inhoud) {
    inhoud.innerHTML = PAGINAS.map(p => `
      <li class="kaartje${p.klaar ? "" : " nog-niet-klaar"}">
        <a href="${p.bestand}">
          <span class="tape" aria-hidden="true"></span>
          <span class="kaartje-titel">${p.titel}</span>
          <span class="kaartje-tekst">${p.kort}</span>
          <span class="kaartje-status">${p.klaar ? "Lees verder" : "Binnenkort meer"}</span>
        </a>
      </li>`).join("");
  }

  // Menu bovenaan de krantenpagina's
  const menu = document.getElementById("menu");
  if (menu) {
    const items = [{ bestand: "index.html", titel: "Voorpagina" }, ...PAGINAS];
    menu.innerHTML = items.map(p =>
      `<li><a href="${p.bestand}"${p.bestand === huidige ? ' aria-current="page"' : ""}>${p.titel.replace("?", "")}</a></li>`
    ).join("");
  }

  // Vorige / volgende onderaan
  const bladeren = document.getElementById("bladeren");
  if (bladeren) {
    const i = PAGINAS.findIndex(p => p.bestand === huidige);
    const vorige = i > 0 ? PAGINAS[i - 1] : { bestand: "index.html", titel: "Voorpagina" };
    const volgende = i >= 0 && i < PAGINAS.length - 1 ? PAGINAS[i + 1] : null;
    bladeren.innerHTML =
      `<a href="${vorige.bestand}">&larr; ${vorige.titel}</a>` +
      (volgende ? `<a href="${volgende.bestand}">${volgende.titel} &rarr;</a>` : "");
  }
})();
